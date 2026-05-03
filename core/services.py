"""
Serviços para importação de dados da B3.
"""
import pandas as pd
from django.db import transaction
from decimal import Decimal, InvalidOperation
from datetime import datetime
from .models import AtivoB3


def importar_csv_b3(file_path):
    """
    Importa um arquivo CSV do Cadastro de Instrumentos da B3.
    
    Args:
        file_path (str): Caminho para o arquivo CSV
        
    Returns:
        dict: Estatísticas do processamento {
            'total_lidas': int,
            'filtradas': int,
            'criadas': int,
            'atualizadas': int,
            'erros': list
        }
    """
    # Lista de ativos monitorados no dashboard
    from .models import AtivoMonitorado
    ATIVOS_PERMITIDOS = list(AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True))
    
    stats = {
        'total_lidas': 0,
        'filtradas': 0,
        'criadas': 0,
        'atualizadas': 0,
        'erros': []
    }
    
    try:
        # Lê o CSV pulando as 2 primeiras linhas (cabeçalho informativo)
        # O cabeçalho real está na linha 3 (índice 2 após skiprows=2)
        df = pd.read_csv(
            file_path,
            sep=';',
            skiprows=2,
            encoding='utf-8',
            on_bad_lines='skip',
            dtype=str  # Lê tudo como string para processar depois
        )
        
        # Remove a última linha (rodapé informativo)
        if len(df) > 0:
            df = df.iloc[:-1]
        
        stats['total_lidas'] = len(df)
        
        # Filtra apenas os ativos permitidos
        if 'Ativo' in df.columns:
            df_filtrado = df[df['Ativo'].isin(ATIVOS_PERMITIDOS)].copy()
            stats['filtradas'] = len(df_filtrado)
        else:
            stats['erros'].append({
                'linha': 'geral',
                'erro': 'Coluna "Ativo" não encontrada no CSV',
                'ticker': 'N/A'
            })
            return stats
        
        if df_filtrado.empty:
            return stats
        
        ativos_objetos_tocados = set()
        
        # Processa cada linha
        with transaction.atomic():
            for index, row in df_filtrado.iterrows():
                try:
                    # Mapeamento de colunas CSV para campos do modelo
                    ticker = str(row.get('Instrumento financeiro', '')).strip()
                    if not ticker or ticker == 'nan':
                        continue
                    
                    # Campos básicos
                    ativo_objeto = str(row.get('Ativo', '')).strip()
                    descricao_ativo = str(row.get('Descrição do ativo', '')).strip()
                    segmento = str(row.get('Segmento', '')).strip()
                    mercado = str(row.get('Mercado', '')).strip()
                    categoria = str(row.get('Categoria', '')).strip()
                    
                    # Conversão de datas (formato DD/MM/YYYY)
                    data_expiracao = _converter_data(row.get('Data de expiração', ''))
                    data_inicio_negocio = _converter_data(row.get('Data início negócio', ''))
                    data_fim_negocio = _converter_data(row.get('Data fim negócio', ''))
                    data_inicio_evento_corp = _converter_data(row.get('Data início evento corp.', ''))
                    
                    # Códigos
                    codigo_isin = str(row.get('Código ISIN', '')).strip()
                    codigo_cfi = str(row.get('Código CFI', '')).strip()
                    codigo_especificacao = str(row.get('Cód. de especificação', '')).strip()
                    
                    # Conversão de inteiros
                    id_distribuicao = _converter_inteiro(row.get('Identificador distribuição', ''))
                    tamanho_lote = _converter_inteiro(row.get('Tamanho de lote', ''))
                    fator_preco = _converter_inteiro(row.get('Fator de preço', ''))
                    dias_liquidacao = _converter_inteiro(row.get('Dias para liquidação', ''))
                    
                    # Conversão de decimais (formato com vírgula: '7,6')
                    preco_exercicio = _converter_decimal(row.get('Preço de exercício', ''))
                    capital_social = _converter_decimal(row.get('Capital social', ''))
                    
                    # Campos de texto
                    tipo_opcao = str(row.get('Tipo de opção', '')).strip()
                    estilo_opcao = str(row.get('Estilo de opção', '')).strip()
                    moeda_negociada = str(row.get('Moeda negociada', '')).strip()
                    tipo_entrega = str(row.get('Tipo de entrega', '')).strip()
                    tipo_serie = str(row.get('Tipo de série', '')).strip()
                    ind_protecao = str(row.get('Indicador de proteção', '')).strip()
                    nivel_governanca = str(row.get('Nível governança', '')).strip()
                    tipo_tratamento_custodia = str(row.get('Tipo tratamento custódia', '')).strip()
                    nome_instituicao = str(row.get('Nome da instituição', '')).strip()
                    
                    # Conversão de booleanos
                    ind_premio_antecipado = _converter_booleano(row.get('Ind. prêmio antecipado', ''))
                    exercicio_automatico = _converter_booleano(row.get('Exercício automático', ''))
                    
                    # Busca ou cria o registro
                    ativo_b3, created = AtivoB3.objects.update_or_create(
                        ticker=ticker,
                        defaults={
                            'ativo_objeto': ativo_objeto,
                            'descricao_ativo': descricao_ativo,
                            'segmento': segmento,
                            'mercado': mercado,
                            'categoria': categoria,
                            'data_expiracao': data_expiracao,
                            'data_inicio_negocio': data_inicio_negocio,
                            'data_fim_negocio': data_fim_negocio,
                            'data_inicio_evento_corp': data_inicio_evento_corp,
                            'codigo_isin': codigo_isin,
                            'codigo_cfi': codigo_cfi,
                            'codigo_especificacao': codigo_especificacao,
                            'id_distribuicao': id_distribuicao,
                            'tipo_opcao': tipo_opcao,
                            'preco_exercicio': preco_exercicio,
                            'estilo_opcao': estilo_opcao,
                            'tamanho_lote': tamanho_lote,
                            'moeda_negociada': moeda_negociada,
                            'tipo_entrega': tipo_entrega,
                            'capital_social': capital_social,
                            'ind_premio_antecipado': ind_premio_antecipado,
                            'exercicio_automatico': exercicio_automatico,
                            'fator_preco': fator_preco,
                            'dias_liquidacao': dias_liquidacao,
                            'tipo_serie': tipo_serie,
                            'ind_protecao': ind_protecao,
                            'nivel_governanca': nivel_governanca,
                            'tipo_tratamento_custodia': tipo_tratamento_custodia,
                            'nome_instituicao': nome_instituicao,
                        }
                    )
                    
                    if created:
                        stats['criadas'] += 1
                    else:
                        stats['atualizadas'] += 1
                        
                    ativos_objetos_tocados.add(ativo_objeto)
                    
                except Exception as e:
                    stats['erros'].append({
                        'linha': index + 3,  # +3 porque pulamos 2 linhas e index começa em 0
                        'erro': str(e),
                        'ticker': str(row.get('Instrumento financeiro', 'N/A'))
                    })
            # Após processar tudo, classificar vencimentos (Mensal/Semanal)
            for ao in ativos_objetos_tocados:
                AtivoB3.classificar_vencimentos(ativo_objeto=ao)
    
    except Exception as e:
        stats['erros'].append({
            'linha': 'geral',
            'erro': f'Erro ao processar arquivo: {str(e)}',
            'ticker': 'N/A'
        })
    
    return stats


def _converter_data(valor):
    """
    Converte string de data no formato DD/MM/YYYY para objeto date.
    
    Args:
        valor: String com data no formato DD/MM/YYYY ou None
        
    Returns:
        date ou None
    """
    if not valor or str(valor).strip() == '' or str(valor).lower() == 'nan':
        return None
    
    try:
        valor_str = str(valor).strip()
        # Tenta parsear formato DD/MM/YYYY
        data = datetime.strptime(valor_str, '%d/%m/%Y')
        return data.date()
    except (ValueError, TypeError):
        try:
            # Tenta parsear outros formatos com pandas
            data = pd.to_datetime(valor_str, errors='coerce', dayfirst=True)
            if pd.notna(data):
                return data.date()
        except Exception:
            pass
    return None


def _converter_decimal(valor):
    """
    Converte string com número decimal (formato brasileiro com vírgula) para Decimal.
    Exemplo: '7,6' -> Decimal('7.6')
    
    Args:
        valor: String com número decimal ou None
        
    Returns:
        Decimal ou None
    """
    if not valor or str(valor).strip() == '' or str(valor).lower() == 'nan':
        return None
    
    try:
        valor_str = str(valor).strip()
        # Remove espaços e substitui vírgula por ponto
        valor_limpo = valor_str.replace(' ', '').replace(',', '.')
        # Remove caracteres não numéricos (exceto ponto e sinal negativo)
        valor_limpo = ''.join(c for c in valor_limpo if c.isdigit() or c in '.-')
        if valor_limpo:
            return Decimal(valor_limpo)
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def _converter_inteiro(valor):
    """
    Converte string para inteiro.
    
    Args:
        valor: String com número inteiro ou None
        
    Returns:
        int ou None
    """
    if not valor or str(valor).strip() == '' or str(valor).lower() == 'nan':
        return None
    
    try:
        valor_str = str(valor).strip().replace(' ', '')
        return int(float(valor_str))  # Converte via float primeiro para lidar com decimais
    except (ValueError, TypeError):
        return None


def _converter_booleano(valor):
    """
    Converte string para booleano.
    Aceita: 'S', 'SIM', 'TRUE', '1', 'Y', 'YES' -> True
    Outros -> False
    
    Args:
        valor: String com valor booleano ou None
        
    Returns:
        bool
    """
    if not valor or str(valor).strip() == '' or str(valor).lower() == 'nan':
        return False
    
    valor_str = str(valor).strip().upper()
    valores_true = ['S', 'SIM', 'TRUE', '1', 'Y', 'YES', 'VERDADEIRO']
    return valor_str in valores_true

import re
import io
import unicodedata
from .models import OpenInterest, AtivoMonitorado

def _normalize_str(s):
    if not s: return ""
    return "".join(
        c for c in unicodedata.normalize('NFD', str(s))
        if unicodedata.category(c) != 'Mn'
    ).upper().strip()

def _find_col(keywords, df_cols):
    normalized_cols = {_normalize_str(c): c for c in df_cols}
    for k in keywords:
        norm_k = _normalize_str(k)
        if norm_k in normalized_cols:
            return normalized_cols[norm_k]
        for norm_c, original_c in normalized_cols.items():
            if norm_k in norm_c:
                return original_c
    return None

def _converter_inteiro_csv_oi(valor):
    if not valor or str(valor).strip() in ('', '-', 'nan'):
        return None
    try:
        valor_str = str(valor).strip().replace('.', '').replace(' ', '')
        return int(float(valor_str))
    except (ValueError, TypeError):
        return None

def processar_csv_open_interest(file_content, filename):
    stats = {'novos': 0, 'atualizados': 0, 'erros': []}
    
    match = re.search(r'(\d{2}-\d{2}-\d{4})', filename)
    if not match:
        stats['erros'].append("Não foi possível extrair a data do nome do arquivo (esperado formato dd-mm-YYYY).")
        return stats
    
    data_str = match.group(1)
    data_referencia = datetime.strptime(data_str, '%d-%m-%Y').date()
    
    try:
        conteudo_decodificado = file_content.decode('utf-8-sig')
    except UnicodeDecodeError:
        conteudo_decodificado = file_content.decode('latin1', errors='ignore')

    preview_raw = conteudo_decodificado[:50000].splitlines()
    linha_cabecalho = None
    for i, texto_linha in enumerate(preview_raw):
        # Usamos uma busca insensível a acentos no cabeçalho
        linha_norm = _normalize_str(texto_linha)
        if 'ISIN' in linha_norm or 'INSTRUMENTO' in linha_norm:
            linha_cabecalho = i
            break
            
    if linha_cabecalho is None:
        stats['erros'].append("Cabeçalho não encontrado no arquivo.")
        return stats

    try:
        io_string = io.StringIO(conteudo_decodificado)
        df = pd.read_csv(io_string, sep=';', skiprows=linha_cabecalho, engine='python', on_bad_lines='skip', dtype=str)
    except Exception as e:
        stats['erros'].append(f"Erro ao ler CSV: {e}")
        return stats
        
    coluna_isin = _find_col(['ISIN'], df.columns)
    if not coluna_isin:
        stats['erros'].append("Coluna ISIN não identificada no arquivo.")
        return stats

    ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True)
    mapa_objetos = {a.codigo_isin: a for a in AtivoB3.objects.filter(ativo_objeto__in=ativos_monitorados)}
    set_isins = set(mapa_objetos.keys())
    
    df[coluna_isin] = df[coluna_isin].astype(str).str.strip()
    df_filtrado = df[df[coluna_isin].isin(set_isins)].copy()
    
    if df_filtrado.empty:
        stats['erros'].append("Nenhum ativo monitorado encontrado neste arquivo.")
        return stats

    cols = {
        'ticker': _find_col(['Instrumento financeiro'], df.columns),
        'ativo_objeto': _find_col(['Ativo'], df.columns),
        'codigo_expiracao': _find_col(['Código de expiração', 'Expiração'], df.columns),
        'segmento': _find_col(['Segmento'], df.columns),
        'contratos_em_aberto': _find_col(['Contratos em aberto'], df.columns),
        'variacao_contratos': _find_col(['Variação de contratos em aberto'], df.columns),
        'id_distribuicao': _find_col(['Identificador da distribuição'], df.columns),
        'quantidade_coberta': _find_col(['Quantidade coberta'], df.columns),
        'total_travas': _find_col(['Total de posições bloqueadas', 'BLOQUEADAS'], df.columns),
        'quantidade_descoberta': _find_col(['Quantidade descoberta'], df.columns),
        'total_posicoes': _find_col(['Total de posições'], df.columns),
        'quantidade_tomadores': _find_col(['Quantidade de tomadores'], df.columns),
        'quantidade_doadores': _find_col(['Quantidade de doadores'], df.columns),
        'quantidade_atual': _find_col(['Quantidade atual'], df.columns),
        'contratos_travados': _find_col(['Contratos travados'], df.columns),
        'contratos_transferencia': _find_col(['Contratos baixados por transferência'], df.columns),
        'preco_termo': _find_col(['Preço a termo'], df.columns)
    }

    with transaction.atomic():
        for _, row in df_filtrado.iterrows():
            try:
                isin = row[coluna_isin]
                ativo_obj = mapa_objetos.get(isin)
                
                ticker_val = row.get(cols['ticker']) if cols['ticker'] else ''
                if not ticker_val or pd.isna(ticker_val): continue
                
                defaults = {
                    'ticker': str(ticker_val).strip(),
                    'ativo_objeto': ativo_obj.ativo_objeto if ativo_obj else (str(row.get(cols['ativo_objeto'])).strip() if cols['ativo_objeto'] else ''),
                    'codigo_expiracao': str(row.get(cols['codigo_expiracao'])).strip() if cols['codigo_expiracao'] else '',
                    'segmento': str(row.get(cols['segmento'])).strip() if cols['segmento'] else '',
                    'contratos_em_aberto': _converter_inteiro_csv_oi(row.get(cols['contratos_em_aberto'])),
                    'variacao_contratos': _converter_inteiro_csv_oi(row.get(cols['variacao_contratos'])),
                    'id_distribuicao': str(row.get(cols['id_distribuicao'])).strip() if cols['id_distribuicao'] else '',
                    'quantidade_coberta': _converter_inteiro_csv_oi(row.get(cols['quantidade_coberta'])),
                    'total_travas': _converter_inteiro_csv_oi(row.get(cols['total_travas'])),
                    'quantidade_descoberta': _converter_inteiro_csv_oi(row.get(cols['quantidade_descoberta'])),
                    'total_posicoes': _converter_inteiro_csv_oi(row.get(cols['total_posicoes'])),
                    'quantidade_tomadores': _converter_inteiro_csv_oi(row.get(cols['quantidade_tomadores'])),
                    'quantidade_doadores': _converter_inteiro_csv_oi(row.get(cols['quantidade_doadores'])),
                    'quantidade_atual': _converter_inteiro_csv_oi(row.get(cols['quantidade_atual'])),
                    'contratos_travados': _converter_inteiro_csv_oi(row.get(cols['contratos_travados'])),
                    'contratos_transferencia': _converter_inteiro_csv_oi(row.get(cols['contratos_transferencia'])),
                    'preco_termo': _converter_decimal(row.get(cols['preco_termo']))
                }
                # Replace None defaults with 0 for integer fields
                for k, v in defaults.items():
                    if v is None and k not in ('ticker', 'ativo_objeto', 'codigo_expiracao', 'segmento', 'id_distribuicao', 'preco_termo'):
                        defaults[k] = 0
                
                # Recalcula o total de posições como a soma solicitada
                defaults['total_posicoes'] = defaults['contratos_em_aberto'] + defaults['quantidade_descoberta'] + defaults['total_travas']
                
                obj, created = OpenInterest.objects.update_or_create(
                    ativo=ativo_obj,
                    data_referencia=data_referencia,
                    defaults=defaults
                )
                
                if created:
                    stats['novos'] += 1
                else:
                    stats['atualizados'] += 1
            except Exception as e:
                stats['erros'].append(f"Erro na linha ISIN {isin}: {e}")

    return stats
