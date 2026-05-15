import logging
import pandas as pd
from django.db import transaction
from .models import AtivoB3, OpenInterest, AtivoMonitorado
from core.utils.converters import (
    convert_to_date, convert_to_decimal, convert_to_int, 
    convert_to_bool, normalize_str, find_column
)

logger = logging.getLogger(__name__)

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
                    data_expiracao = convert_to_date(row.get('Data de expiração', ''))
                    data_inicio_negocio = convert_to_date(row.get('Data início negócio', ''))
                    data_fim_negocio = convert_to_date(row.get('Data fim negócio', ''))
                    data_inicio_evento_corp = convert_to_date(row.get('Data início evento corp.', ''))
                    
                    # Códigos
                    codigo_isin = str(row.get('Código ISIN', '')).strip()
                    codigo_cfi = str(row.get('Código CFI', '')).strip()
                    codigo_especificacao = str(row.get('Cód. de especificação', '')).strip()
                    
                    # Conversão de inteiros
                    id_distribuicao = convert_to_int(row.get('Identificador distribuição', ''))
                    tamanho_lote = convert_to_int(row.get('Tamanho de lote', ''))
                    fator_preco = convert_to_int(row.get('Fator de preço', ''))
                    dias_liquidacao = convert_to_int(row.get('Dias para liquidação', ''))
                    
                    # Conversão de decimais (formato com vírgula: '7,6')
                    preco_exercicio = convert_to_decimal(row.get('Preço de exercício', ''))
                    capital_social = convert_to_decimal(row.get('Capital social', ''))
                    
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
                    ind_premio_antecipado = convert_to_bool(row.get('Ind. prêmio antecipado', ''))
                    exercicio_automatico = convert_to_bool(row.get('Exercício automático', ''))
                    
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


import re
import io

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
        linha_norm = normalize_str(texto_linha)
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
        
    coluna_isin = find_column(['ISIN'], df.columns)
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
        'ticker': find_column(['Instrumento financeiro'], df.columns),
        'ativo_objeto': find_column(['Ativo'], df.columns),
        'codigo_expiracao': find_column(['Código de expiração', 'Expiração'], df.columns),
        'segmento': find_column(['Segmento'], df.columns),
        'contratos_em_aberto': find_column(['Contratos em aberto'], df.columns),
        'variacao_contratos': find_column(['Variação de contratos em aberto'], df.columns),
        'id_distribuicao': find_column(['Identificador da distribuição'], df.columns),
        'quantidade_coberta': find_column(['Quantidade coberta'], df.columns),
        'total_travas': find_column(['Total de posições bloqueadas', 'BLOQUEADAS'], df.columns),
        'quantidade_descoberta': find_column(['Quantidade descoberta'], df.columns),
        'total_posicoes': find_column(['Total de posições'], df.columns),
        'quantidade_tomadores': find_column(['Quantidade de tomadores'], df.columns),
        'quantidade_doadores': find_column(['Quantidade de doadores'], df.columns),
        'quantidade_atual': find_column(['Quantidade atual'], df.columns),
        'contratos_travados': find_column(['Contratos travados'], df.columns),
        'contratos_transferencia': find_column(['Contratos baixados por transferência'], df.columns),
        'preco_termo': find_column(['Preço a termo'], df.columns)
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
                    'contratos_em_aberto': convert_to_int(row.get(cols['contratos_em_aberto'])),
                    'variacao_contratos': convert_to_int(row.get(cols['variacao_contratos'])),
                    'id_distribuicao': str(row.get(cols['id_distribuicao'])).strip() if cols['id_distribuicao'] else '',
                    'quantidade_coberta': convert_to_int(row.get(cols['quantidade_coberta'])),
                    'total_travas': convert_to_int(row.get(cols['total_travas'])),
                    'quantidade_descoberta': convert_to_int(row.get(cols['quantidade_descoberta'])),
                    'total_posicoes': convert_to_int(row.get(cols['total_posicoes'])),
                    'quantidade_tomadores': convert_to_int(row.get(cols['quantidade_tomadores'])),
                    'quantidade_doadores': convert_to_int(row.get(cols['quantidade_doadores'])),
                    'quantidade_atual': convert_to_int(row.get(cols['quantidade_atual'])),
                    'contratos_travados': convert_to_int(row.get(cols['contratos_travados'])),
                    'contratos_transferencia': convert_to_int(row.get(cols['contratos_transferencia'])),
                    'preco_termo': convert_to_decimal(row.get(cols['preco_termo']))
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
                logger.error(f"Erro na linha ISIN {isin} do CSV OI: {e}")
                stats['erros'].append(f"Erro na linha ISIN {isin}: {e}")

    return stats


def get_option_chain(ativo_objeto, data_expiracao):
    """
    Monta a grade de opções (Option Chain) para um ativo objeto e vencimento específicos.
    """
    from .models import AtivoB3, HistoricoPreco
    from django.db.models import Max
    
    opcoes = AtivoB3.objects.filter(
        ativo_objeto=ativo_objeto,
        data_expiracao=data_expiracao
    ).order_by('preco_exercicio')
    
    # Preços recentes das opções
    max_date = HistoricoPreco.objects.filter(ativo__in=opcoes).aggregate(Max('data_pregao'))['data_pregao__max'] if opcoes.exists() else None
    
    precos_recentes = {
        h.ativo_id: h 
        for h in HistoricoPreco.objects.filter(
            ativo__in=opcoes,
            data_pregao=max_date
        )
    } if max_date else {}
    
    chain_dict = {}
    for op in opcoes:
        strike = op.preco_exercicio
        if strike not in chain_dict:
            chain_dict[strike] = {
                'strike': strike, 
                'call': None, 'put': None, 
                'call_hist': None, 'put_hist': None
            }
            
        hist = precos_recentes.get(op.codigo_isin)
        tipo = op.tipo_opcao.strip().upper()
        
        if 'CALL' in tipo or 'COMPRA' in tipo:
            chain_dict[strike]['call'] = op
            chain_dict[strike]['call_hist'] = hist
        elif 'PUT' in tipo or 'VENDA' in tipo:
            chain_dict[strike]['put'] = op
            chain_dict[strike]['put_hist'] = hist
            
    chain_list = list(chain_dict.values())
    chain_list.sort(key=lambda x: x['strike'] if x['strike'] else 0)
    return chain_list

def get_ativo_stats(ticker):
    """
    Calcula estatísticas de preço e variações para um ativo objeto.
    """
    from .models import AtivoB3, HistoricoPreco
    ativo = AtivoB3.objects.filter(ticker=ticker).first()
    if not ativo:
        return None
        
    hist = HistoricoPreco.objects.filter(ativo=ativo, fechamento__gt=0).order_by('-data_pregao')
    if not hist.exists():
        return None
        
    h_atual = hist.first()
    stats = {'preco_atual': float(h_atual.fechamento)}
    
    # Função auxiliar para variação
    def calc_var(atual, anterior):
        if not anterior or float(anterior) == 0: return 0
        return ((float(atual) / float(anterior)) - 1) * 100

    # Variações
    count = hist.count()
    h_ontem = hist[1] if count > 1 else None
    h_5d = hist[min(5, count-1)] if count > 1 else None
    h_30d = hist[min(30, count-1)] if count > 1 else None
    
    stats['var_diaria'] = calc_var(h_atual.fechamento, h_ontem.fechamento if h_ontem else None)
    stats['var_5d'] = calc_var(h_atual.fechamento, h_5d.fechamento if h_5d else None)
    stats['var_30d'] = calc_var(h_atual.fechamento, h_30d.fechamento if h_30d else None)
    
    return stats

def sync_precos_negocios_b3():
    """
    Sincroniza os dados da tabela dadosb3.NegocioDiario para a tabela core.HistoricoPreco.
    Cria entradas que não existem em HistoricoPreco baseando-se no par (isin, data_pregao).
    """
    from dadosb3.models import NegocioDiario
    from .models import AtivoB3, HistoricoPreco
    
    stats = {'novos': 0, 'pulados': 0, 'erros': 0}
    
    # Carregamos NegocioDiario
    negocios = NegocioDiario.objects.all()
    
    # Mapeamento ISIN -> AtivoB3 para performance
    mapa_ativos = {a.codigo_isin: a for a in AtivoB3.objects.all()}
    
    # Cache do que já existe em HistoricoPreco (ativo_pk, data_pregao)
    existentes = set(HistoricoPreco.objects.values_list('ativo_id', 'data_pregao'))
    
    novos_historicos = []
    
    with transaction.atomic():
        for neg in negocios:
            ativo = mapa_ativos.get(neg.isin)
            if not ativo:
                # Ativo não cadastrado no core.AtivoB3
                continue
                
            if (ativo.codigo_isin, neg.data_pregao) in existentes:
                stats['pulados'] += 1
                continue
                
            novos_historicos.append(HistoricoPreco(
                ativo=ativo,
                data_pregao=neg.data_pregao,
                abertura=neg.preco_abertura or 0,
                maximo=neg.preco_maximo or 0,
                minimo=neg.preco_minimo or 0,
                fechamento=neg.preco_fechamento or 0,
                quantidade_negocios=neg.qtd_negocios or 0,
                volume_financeiro=neg.volume_financeiro or 0,
                quantidade_contratos=neg.qtd_contratos or 0
            ))
            
            if len(novos_historicos) >= 500:
                HistoricoPreco.objects.bulk_create(novos_historicos, ignore_conflicts=True)
                stats['novos'] += len(novos_historicos)
                novos_historicos = []
                
        if novos_historicos:
            HistoricoPreco.objects.bulk_create(novos_historicos, ignore_conflicts=True)
            stats['novos'] += len(novos_historicos)
            
    return stats
