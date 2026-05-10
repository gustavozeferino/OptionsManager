import re
import unicodedata
import pandas as pd
from decimal import Decimal, InvalidOperation
from datetime import datetime

def normalize_str(s):
    """Remove acentos e padroniza string para busca/comparação."""
    if not s:
        return ""
    return "".join(
        c for c in unicodedata.normalize('NFD', str(s))
        if unicodedata.category(c) != 'Mn'
    ).upper().strip()

def find_column(keywords, df_cols):
    """
    Localiza uma coluna em um DataFrame baseada em palavras-chave.
    Tenta match exato primeiro, depois parcial (contém).
    """
    normalized_cols = {normalize_str(c): c for c in df_cols}
    for k in keywords:
        norm_k = normalize_str(k)
        # Match exato
        if norm_k in normalized_cols:
            return normalized_cols[norm_k]
        # Match parcial
        for norm_c, original_c in normalized_cols.items():
            if norm_k in norm_c:
                return original_c
    return None

def convert_to_decimal(value, default=Decimal('0.00')):
    """
    Converte diversos formatos de string (R$, 1.000,50, etc) para Decimal.
    Suporta formatos PT-BR e internacional.
    """
    if pd.isna(value) or str(value).strip() in ('', '-', 'nan'):
        return default
    
    s = str(value).replace('R$', '').replace(' ', '').strip()
    try:
        if ',' in s and '.' in s:
            # Formato 1.234,56
            s = s.replace('.', '').replace(',', '.')
        elif ',' in s:
            # Formato 1234,56
            s = s.replace(',', '.')
        elif s.count('.') > 1:
            # Formato 1.234.567 (milhar sem decimal ou com decimal inconsistente)
            s = s.replace('.', '')
        
        # Remove caracteres residuais não numéricos exceto ponto e sinal
        s = ''.join(c for c in s if c.isdigit() or c in '.-')
        if not s:
            return default
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return default

def convert_to_int(value, default=0):
    """Converte string para inteiro, removendo separadores de milhar."""
    if pd.isna(value) or str(value).strip() in ('', '-', 'nan'):
        return default
    
    s = str(value).replace('.', '').replace(' ', '').strip()
    if ',' in s:
        s = s.split(',')[0]
    
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return default

def convert_to_date(value, format='%d/%m/%Y'):
    """Converte string de data para objeto date."""
    if not value or pd.isna(value) or str(value).strip() in ('', '-', 'nan'):
        return None
    
    value_str = str(value).strip()
    try:
        # Tenta formato específico primeiro
        return datetime.strptime(value_str, format).date()
    except (ValueError, TypeError):
        try:
            # Tenta via pandas (mais flexível)
            dt = pd.to_datetime(value_str, dayfirst=True, errors='coerce')
            if pd.notna(dt):
                return dt.date()
        except:
            pass
    return None

def convert_to_bool(value):
    """Converte string para booleano (S/N, Sim/Não, True/False)."""
    if not value or pd.isna(value) or str(value).strip() in ('', '-', 'nan'):
        return False
    
    s = str(value).strip().upper()
    true_values = ['S', 'SIM', 'TRUE', '1', 'Y', 'YES', 'VERDADEIRO']
    return s in true_values
