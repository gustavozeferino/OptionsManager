import os
import io
import pandas as pd
import django
import unicodedata
import datetime
from django.db import transaction

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from core.models import AtivoB3, HistoricoPreco, AtivoMonitorado

def clean_numeric(val):
    if pd.isna(val) or str(val).strip() in ('', '-', 'nan'): return 0
    try:
        s = str(val).replace('.', '').replace(',', '.')
        return float(s)
    except:
        return 0

def clean_int(val):
    if pd.isna(val) or str(val).strip() in ('', '-', 'nan'): return 0
    try:
        s = str(val).replace('.', '').replace(',', '')
        return int(float(s))
    except:
        return 0

def normalize_str(s):
    if not s: return ""
    return "".join(
        c for c in unicodedata.normalize('NFD', str(s))
        if unicodedata.category(c) != 'Mn'
    ).upper().strip()

def find_col(keywords, df_cols):
    normalized_cols = {normalize_str(c): c for c in df_cols}
    for k in keywords:
        norm_k = normalize_str(k)
        if norm_k in normalized_cols:
            return normalized_cols[norm_k]
        for norm_c, original_c in normalized_cols.items():
            if norm_k in norm_c:
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

    # 2. Ler CSV
    print(f"Lendo dataframe (linha {linha_cabecalho})...")
    try:
        df = pd.read_csv(file_path, sep=None, skiprows=linha_cabecalho, engine='python', on_bad_lines='skip', dtype=str, encoding='latin1')
    except Exception as e:
        print(f"Erro ao ler CSV: {e}")
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
        'abertura': find_col(['Preço de abertura'], df.columns),
        'maximo': find_col(['Preço máximo'], df.columns),
        'minimo': find_col(['Preço mínimo'], df.columns),
        'fechamento': find_col(['Preço de fechamento'], df.columns),
        'ajuste': find_col(['Ajuste'], df.columns),
        'qtd_neg': find_col(['Quantidade de negócios'], df.columns),
        'vol_fin': find_col(['Volume financeiro'], df.columns),
        'qtd_contratos': find_col(['Quantidade de contratos'], df.columns),
        'data_neg': find_col(['Data do negócio', 'Data'], df.columns)
    }

    total = len(df_filtrado)
    print(f"Gravando {total} registros...")
    
    count = 0
    with transaction.atomic():
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
                count += 1
                if count % 1000 == 0:
                    print(f"  > {count}/{total}...")
            except Exception as e:
                pass
    print(f"SUCESSO: {count} registros importados.")

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
