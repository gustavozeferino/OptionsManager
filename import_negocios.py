import os
import io
import pandas as pd
import django
import unicodedata
import datetime
from django.db import transaction

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from django.db import connection
# Aumenta o timeout para evitar 'database is locked' em SQLite
with connection.cursor() as cursor:
    cursor.execute('PRAGMA busy_timeout = 30000;')

from core.models import AtivoB3, HistoricoPreco, AtivoMonitorado

def clean_numeric(value):
    """Trata R$, pontos de milhar e vírgulas decimais para formato brasileiro ou internacional."""
    if pd.isna(value) or str(value).strip() in ('', '-', 'nan'):
        return 0.0
    s = str(value).replace('R$', '').replace(' ', '').strip()
    
    try:
        if ',' in s:
            s = s.replace('.', '').replace(',', '.')
        elif '.' in s:
            if s.count('.') > 1:
                s = s.replace('.', '')
            else:
                s = s.replace('.', '')
        return float(s)
    except (ValueError, TypeError):
        return 0.0

def clean_int(val):
    if pd.isna(val) or str(val).strip() in ('', '-', 'nan'): return 0
    try:
        s = str(val).replace('.', '').replace(',', '')
        return int(float(s))
    except:
        return 0

import re

def normalize_str(s):
    if not s: return ""
    # Remove acentos
    s = "".join(
        c for c in unicodedata.normalize('NFD', str(s))
        if unicodedata.category(c) != 'Mn'
    )
    # Remove qualquer caractere que não seja letra ou número
    s = re.sub(r'[^a-zA-Z0-9]', '', s)
    return s.upper().strip()

def find_col(keywords, df_cols):
    """Localiza coluna por keywords, ignorando acentos e sendo tolerante a encoding."""
    normalized_cols = {normalize_str(c): c for c in df_cols}
    # Tenta match exato primeiro
    for k in keywords:
        norm_k = normalize_str(k)
        if norm_k in normalized_cols:
            return normalized_cols[norm_k]
            
    # Tenta match parcial (se a keyword está na coluna ou vice-versa)
    for k in keywords:
        norm_k = normalize_str(k)
        for norm_c, original_c in normalized_cols.items():
            if norm_k in norm_c or norm_c in norm_k:
                return original_c
    return None

def importar_arquivo(file_path):
    print(f"\n[*] Processando: {file_path}")
    
    # 1. Localizar cabeçalho
    try:
        with open(file_path, 'rb') as f:
            preview_raw = f.read(100000).decode('latin1', errors='ignore').splitlines()
    except Exception as e:
        print(f"Erro ao ler preview: {e}")
        return
    
    linha_cabecalho = None
    for i, texto_linha in enumerate(preview_raw):
        if 'ISIN' in texto_linha.upper():
            linha_cabecalho = i
            break
            
    if linha_cabecalho is None:
        print(f"ERRO: Cabeçalho 'ISIN' não encontrado em {file_path}")
        return

    # 2. Ler CSV - Tenta utf-8-sig, cp1252 e latin1
    print(f"Lendo dataframe (linha {linha_cabecalho})...")
    for enc in ['utf-8-sig', 'cp1252', 'latin1']:
        try:
            df = pd.read_csv(file_path, sep=';', skiprows=linha_cabecalho, engine='c', on_bad_lines='skip', dtype=str, encoding=enc)
            print(f"Sucesso com encoding: {enc}")
            break
        except:
            continue
    else:
        print(f"Erro ao ler CSV: Nao foi possivel detectar encoding.")
        return
    
    coluna_isin = next((c for c in df.columns if 'ISIN' in c.upper()), None)
    if not coluna_isin:
        print("ERRO: Coluna ISIN não identificada após leitura.")
        return
    
    # 3. Filtrar
    ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True)
    mapa_objetos = {a.codigo_isin: a for a in AtivoB3.objects.filter(ativo_objeto__in=ativos_monitorados)}
    set_isins = set(mapa_objetos.keys())
    
    col_segmento = find_col(['Segmento'], df.columns)
    if col_segmento:
        segmentos_permitidos = ['CASH', 'EQUITY CALL', 'EQUITY PUT']
        df[col_segmento] = df[col_segmento].astype(str).str.strip().str.upper()
        df = df[df[col_segmento].isin(segmentos_permitidos)]

    df[coluna_isin] = df[coluna_isin].astype(str).str.strip()
    df_filtrado = df[df[coluna_isin].isin(set_isins)].copy()
    
    if df_filtrado.empty:
        print("AVISO: Nenhum ativo monitorado encontrado neste arquivo.")
        return

    # 4. Mapear colunas
    cols = {
        'abertura': find_col(['Abertura', 'ABR', 'PRECO ABR'], df.columns),
        'maximo': find_col(['Maximo', 'MAX'], df.columns),
        'minimo': find_col(['Minimo', 'MNIMO', 'MIN'], df.columns),
        'fechamento': find_col(['Fechamento', 'FECH', 'Ultimo', 'ULT'], df.columns),
        'ajuste': find_col(['Ajuste', 'AJUST'], df.columns),
        'qtd_neg': find_col(['Negocios', 'NEGOC', 'NEGOCIOS'], df.columns),
        'vol_fin': find_col(['Volume', 'VOL'], df.columns),
        'qtd_contratos': find_col(['Contratos', 'QTD CONTRATOS'], df.columns),
        'data_neg': find_col(['Data'], df.columns)
    }

    # Validação
    faltando = [k for k, v in cols.items() if v is None and k not in ['ajuste']]
    if faltando:
        print(f"ERRO: Colunas obrigatórias não encontradas: {faltando}")
        print(f"Colunas disponíveis no arquivo: {list(df.columns)}")
        return

    total = len(df_filtrado)
    print(f"Gravando {total} registros...")
    
    count = 0
    total_sucesso = 0
    # Processamos em lotes para não travar o banco por muito tempo
    for _, row in df_filtrado.iterrows():
        try:
            isin = row[coluna_isin]
            ativo_obj = mapa_objetos.get(isin)
            
            data_linha = row.get(cols['data_neg'])
            if pd.isna(data_linha) or str(data_linha).strip() == '-': continue
            
            dt_pregao = pd.to_datetime(data_linha, dayfirst=True).date()

            HistoricoPreco.objects.update_or_create(
                ativo=ativo_obj,
                data_pregao=dt_pregao,
                defaults={
                    'abertura': clean_numeric(row.get(cols['abertura'])),
                    'maximo': clean_numeric(row.get(cols['maximo'])),
                    'minimo': clean_numeric(row.get(cols['minimo'])),
                    'fechamento': clean_numeric(row.get(cols['fechamento'])),
                    'ajuste': clean_numeric(row.get(cols['ajuste'])),
                    'quantidade_negocios': clean_int(row.get(cols['qtd_neg'])),
                    'volume_financeiro': clean_numeric(row.get(cols['vol_fin'])),
                    'quantidade_contratos': clean_int(row.get(cols['qtd_contratos'])),
                }
            )
            total_sucesso += 1
            count += 1
            if count % 1000 == 0:
                print(f"  > {count}/{total}...")
        except Exception as e:
            pass
    print(f"SUCESSO: {total_sucesso} registros importados.")

if __name__ == '__main__':
    arquivos = [
        'input_data/negocios/negocios 2026-04.csv',
        'input_data/negocios/negocios 2026-03.csv',
        'input_data/negocios/negocios 2026-02.csv'
    ]
    for arq in arquivos:
        if os.path.exists(arq):
            importar_arquivo(arq)
        else:
            print(f"Arquivo não encontrado: {arq}")
