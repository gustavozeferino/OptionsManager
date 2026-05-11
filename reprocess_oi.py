import os
import re
import pandas as pd
import django
from datetime import datetime
from decimal import Decimal
import unicodedata

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from dadosb3.models import PosicaoAberta, LogProcessamento
from django.conf import settings

def slugify(text):
    return "".join(c for c in unicodedata.normalize('NFD', str(text)) if unicodedata.category(c) != 'Mn').lower().strip()

def get_val(row, columns, terms):
    for i, col in enumerate(columns):
        c = slugify(col)
        if all(t in c for t in terms):
            return row.iloc[i]
    return None

def parse_decimal(val):
    if pd.isna(val) or val == '' or val == '-':
        return None
    val = str(val).replace('.', '').replace(',', '.')
    try:
        return Decimal(val)
    except:
        return None

def parse_int(val):
    if pd.isna(val) or val == '' or val == '-':
        return None
    try:
        val = str(val).replace('.', '')
        return int(val)
    except:
        return None

def extract_date(filename):
    # Format: dd-mm-aaaa
    match = re.search(r'(\d{2})-(\d{2})-(\d{4})', filename)
    if match:
        try:
            return datetime.strptime(match.group(0), '%d-%m-%Y').date()
        except:
            return None
    return None

def reprocess():
    print("--- INICIANDO REPROCESSAMENTO DE POSIÇÕES EM ABERTO ---")
    
    print("Apagando dados existentes na tabela posicao_aberta...")
    count_deleted, _ = PosicaoAberta.objects.all().delete()
    print(f"Registros apagados: {count_deleted}")
    
    base_path = 'input_data/Open Interest'
    
    # Percorre recursivamente para pegar arquivos em subpastas
    files_to_process = []
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith('.csv'):
                files_to_process.append(os.path.join(root, file))
    
    print(f"Total de arquivos encontrados: {len(files_to_process)}")
    
    for file_path in files_to_process:
        filename = os.path.basename(file_path)
        date_ref = extract_date(filename)
        
        if not date_ref:
            print(f"AVISO: Data não encontrada no nome do arquivo '{filename}'. Pulando...")
            continue
            
        print(f"Processando: {filename} (Data Ref: {date_ref})")
        
        # Detecção da linha de cabeçalho
        skip = 0
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f):
                    if i > 15: break
                    if 'Instrumento' in line and 'ISIN' in line:
                        skip = i
                        break
        except Exception as e:
            print(f"Erro ao ler cabeçalho de {filename}: {e}")
            continue
        
        chunksize = 5000
        total_imported = 0
        
        try:
            # Lendo em chunks para eficiência
            for chunk in pd.read_csv(file_path, sep=';', skiprows=skip, encoding='utf-8-sig', chunksize=chunksize, dtype=str):
                cols = chunk.columns
                instances = []
                for _, row in chunk.iterrows():
                    ticker = str(get_val(row, cols, ['instrumento', 'financeiro']) or '').strip()
                    isin = str(get_val(row, cols, ['codigo', 'isin']) or '').strip()
                    
                    # Regra de validação: ISIN deve estar preenchido
                    if not isin or isin.lower() == 'nan' or isin == '':
                        continue
                    
                    if not ticker or ticker.lower() == 'nan' or ticker == '':
                        continue
                    
                    instances.append(PosicaoAberta(
                        data=date_ref,
                        ticker=ticker,
                        isin=isin,
                        codigo_expiracao=str(get_val(row, cols, ['codigo', 'expiracao']) or '').strip()[:100],
                        contratos_abertos=parse_int(get_val(row, cols, ['contratos', 'aberto'])),
                        qtd_coberta=parse_int(get_val(row, cols, ['quantidade', 'coberta'])),
                        qtd_descoberta=parse_int(get_val(row, cols, ['quantidade', 'descoberta'])),
                        preco_termo=parse_decimal(get_val(row, cols, ['preco', 'termo'])),
                    ))
                
                if instances:
                    PosicaoAberta.objects.bulk_create(instances)
                    total_imported += len(instances)
            
            print(f"  > Sucesso! {total_imported} registros importados.")
            LogProcessamento.objects.create(nome_arquivo=filename, status='Sucesso', descricao_falha='-')
        except Exception as e:
            print(f"  > ERRO ao processar {filename}: {e}")
            LogProcessamento.objects.create(nome_arquivo=filename, status='Erro', descricao_falha=str(e))

    print("\n--- REPROCESSAMENTO CONCLUÍDO ---")

if __name__ == '__main__':
    reprocess()
