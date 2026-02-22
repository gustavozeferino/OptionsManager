import os
import pandas as pd
import django
from decimal import Decimal
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from core.models import AtivoB3

def limpar_decimal(valor):
    if pd.isna(valor) or str(valor).strip() in ('', '-'): return None
    try:
        # Remove possíveis aspas, pontos de milhar e ajusta a vírgula
        s_valor = str(valor).replace('"', '').replace("'", "").strip()
        s_valor = s_valor.replace('.', '').replace(',', '.')
        return Decimal(s_valor)
    except:
        return None

def limpar_data(valor):
    if pd.isna(valor) or str(valor).strip() in ('', '-'): return None
    try:
        return datetime.strptime(str(valor).strip(), '%d/%m/%Y').date()
    except:
        return None

def importar():
    csv_path = 'input_data/Cadastro de instrumentos-18-02-2026.csv'
    
    if not os.path.exists(csv_path):
        print(f"ERRO: Arquivo não encontrado em {csv_path}")
        return

    print(f"Lendo {csv_path}...")
    # Usamos latin-1 para ler, mas vamos normalizar os nomes das colunas logo depois
    df = pd.read_csv(csv_path, sep=';', skiprows=2, encoding='latin-1', low_memory=False)
    df = df[:-1] 

    # --- NORMALIZAÇÃO DAS COLUNAS ---
    # Isso remove os caracteres estranhos e espaços dos nomes das colunas
    df.columns = [
        c.encode('latin-1').decode('utf-8', 'ignore').strip() 
        if isinstance(c, str) else c 
        for c in df.columns
    ]
    
    # Caso a decodificação acima falhe, vamos renomear manualmente as principais colunas por posição
    # para garantir que o script funcione independente do encoding do cabeçalho
    mapeamento = {
        'Instrumento financeiro': 'ticker',
        'Ativo': 'ativo_objeto',
        'Código ISIN': 'isin',
        'Tipo de opção': 'tipo',
        'Preço de exercício': 'strike',
        'Data de expiração': 'vencimento'
    }
    
    print("Colunas normalizadas:", df.columns.tolist())

    ativos_interesse = ['BOVA11', 'PETR4', 'VALE3']
    # Filtra removendo espaços extras que podem vir no CSV
    df['Ativo'] = df['Ativo'].astype(str).str.strip()
    df_filtrado = df[df['Ativo'].isin(ativos_interesse)].copy()

    print(f"Linhas para processar: {len(df_filtrado)}")

    contagem = 0
    for _, row in df_filtrado.iterrows():
        try:
            # Busca dinâmica: tenta o nome correto ou o nome com erro de encoding
            isin = row.get('Código ISIN') or row.get('Código ISIN')
            ticker = row.get('Instrumento financeiro')

            # Captura o segmento tratando possíveis erros de encoding no nome da coluna
            segmento_valor = row.get('Segmento') or row.get('Segmento') # Caso haja variação
            
            if not isin or pd.isna(isin):
                continue

            # Limpeza dos dados
            isin = str(isin).strip()
            ticker = str(ticker).strip()

            AtivoB3.objects.update_or_create(
                codigo_isin=isin,
                defaults={
                    'ticker': ticker,
                    'ativo_objeto': row.get('Ativo'),
                    'descricao_ativo': row.get('Descrição do ativo') or row.get('Descrição do ativo', ''),
                    'data_expiracao': limpar_data(row.get('Data de expiração') or row.get('Data de expiração')),
                    'tipo_opcao': row.get('Tipo de opção') or row.get('Tipo de opção', ''),
                    'preco_exercicio': limpar_decimal(row.get('Preço de exercício') or row.get('Preço de exercício')),
                    'mercado': row.get('Mercado', ''),
                    'segmento': segmento_valor,
                }
            )
            contagem += 1
            if contagem % 500 == 0:
                print(f"Importados {contagem}...")

        except Exception as e:
            print(f"Erro no registro {row.get('Instrumento financeiro')}: {e}")

    print(f"\n--- SUCESSO! {contagem} registros no banco de dados. ---")

if __name__ == '__main__':
    importar()