import csv
import datetime
import io
import json
import logging
import time
from collections import defaultdict

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import connections, transaction
from django.db.models import Avg, Count, Max, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.utils.converters import (
    convert_to_date, convert_to_decimal, convert_to_int, 
    find_column, normalize_str
)
from trading.models import Estrutura, Rolagem
from trading.services import (
    recalcular_estrutura, recalcular_rolagem, recalcular_todas_rolagens
)
from .models import (
    AcessoLog, AtivoB3, AtivoMonitorado, HistoricoImportacao, 
    HistoricoPreco, OpenInterest
)
from .services import (
    get_ativo_stats, get_option_chain, processar_csv_open_interest, 
    sync_precos_negocios_b3
)

# Configuração do Logger do Django
logger = logging.getLogger(__name__)

# Constants de Configuração para Reaproveitamento
SEGMENTOS_PERMITIDOS = ['CASH', 'EQUITY CALL', 'EQUITY PUT', 'EQUITY']
MAX_EXPORT_ROWS = 50000
DEFAULT_TICKER = 'BOVA11'


def apenas_admin(user):
    """Filtro auxiliar para testar se o usuário possui privilégios de superusuário."""
    return user.is_superuser


# =============================================================================
# CORE & DASHBOARD VIEWS
# =============================================================================

@login_required
def home(request):
    """
    View da Home do painel admin.
    Exibe indicadores de controle de ativos cadastrados, última data de pregão e logs recentes.
    """
    if not request.user.is_staff and not request.user.is_superuser:
        return redirect('trading:dashboard')
    
    try:
        hoje = timezone.now().date()
        ativos_vivos = AtivoB3.objects.filter(data_expiracao__gte=hoje).count()
        
        # Otimização: Coleta agregações em uma única consulta
        agg_precos = HistoricoPreco.objects.aggregate(ultima_data=Max('data_pregao'))
        ultima_data = agg_precos['ultima_data']

        ativos_negociados = 0
        if ultima_data:
            ativos_negociados = HistoricoPreco.objects.filter(
                data_pregao=ultima_data,
                volume_financeiro__gt=0
            ).count()

        ultimos_logs = AcessoLog.objects.all().order_by('-data_acesso')[:5]
        
        context = {
            'ativos_vivos': ativos_vivos,
            'ultima_data': ultima_data,
            'ativos_negociados': ativos_negociados,
            'total_geral': AtivoB3.objects.count(),
            'ultimos_logs': ultimos_logs,
        }
        return render(request, 'core/home.html', context)
    except Exception as e:
        logger.error(f"Erro ao carregar a home do painel: {str(e)}", exc_info=True)
        messages.error(request, "Erro interno ao carregar indicadores principais.")
        return redirect('trading:dashboard')


@user_passes_test(apenas_admin)
def lista_logs(request):
    """Lista todos os registros de acessos gerados no sistema com paginação flexível."""
    try:
        logs_list = AcessoLog.objects.all().order_by('-data_acesso')
        paginator = Paginator(logs_list, 50)
        page_number = request.GET.get('page')
        logs = paginator.get_page(page_number)
        return render(request, 'core/lista_logs.html', {'logs': logs})
    except Exception as e:
        logger.error(f"Erro ao listar logs do sistema: {str(e)}", exc_info=True)
        messages.error(request, "Não foi possível carregar a lista de logs.")
        return redirect('core:home')


# =============================================================================
# ENGINE DE IMPORTAÇÃO E COMPACTAÇÃO DE DADOS (CSV)
# =============================================================================

@user_passes_test(apenas_admin)
def upload_csv(request):
    """
    Processa o upload do arquivo CSV com a lista de instrumentos emitidos pela B3.
    Faz a higienização de strikes, datas de expiração e insere/atualiza registros.
    """
    if request.method == 'POST' and request.FILES.get('arquivo'):
        file = request.FILES['arquivo']
        
        ativos_permitidos = list(AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True))
        if not ativos_permitidos:
            messages.warning(request, "Nenhum Ativo Monitorado cadastrado. A importação não processará dados.")
            return redirect('core:upload_csv')

        try:
            content = file.read()
            decoded_content = content.decode('utf-8-sig') if b'\xef\xbb\xbf' in content else content.decode('latin1')
            
            linhas = decoded_content.splitlines()
            pular = next((i for i, linha in enumerate(linhas[:15]) if 'ISIN' in linha), 0)
            
            io_string = io.StringIO(decoded_content)
            df = pd.read_csv(io_string, sep=';', skiprows=pular, engine='python')
            df.columns = [str(c).strip() for c in df.columns]
        except Exception as e:
            logger.error(f"Erro ao analisar estrutura do CSV de Ativos: {str(e)}", exc_info=True)
            messages.error(request, f"Erro na estrutura do arquivo: {e}")
            return redirect('core:upload_csv')

        relatorio = {'novos': 0, 'atualizados': 0, 'sem_alteracao': 0, 'logs': []}
        
        # Bloco transacionado para garantir integridade do lote
        with transaction.atomic():
            for index, row in df.iterrows():
                ativo_obj_csv = str(row.get('Ativo', '')).strip().upper()
                if ativo_obj_csv not in ativos_permitidos:
                    continue

                isin = str(row.get('Código ISIN', '')).strip()
                if isin in ['', 'nan', '-']:
                    continue

                dados_csv = {
                    'ticker': str(row.get('Instrumento financeiro', 'S/N')).strip(),
                    'ativo_objeto': ativo_obj_csv,
                    'tipo_opcao': str(row.get('Tipo de opção', '')).strip(),
                    'preco_exercicio': convert_to_decimal(row.get('Preço de exercício', 0)),
                    'data_expiracao': convert_to_date(row.get('Data de expiração')),
                    'segmento': str(row.get('Segmento', '')).strip(),
                }

                ativo_queryset = AtivoB3.objects.filter(codigo_isin__iexact=isin)

                if not ativo_queryset.exists():
                    AtivoB3.objects.create(codigo_isin=isin, **dados_csv)
                    relatorio['novos'] += 1
                    relatorio['logs'].append(f"NOVO: {dados_csv['ticker']} ({isin})")
                else:
                    ativo = ativo_queryset.first()
                    mudancas = []
                    
                    for campo, valor_novo in dados_csv.items():
                        valor_antigo = getattr(ativo, campo)
                        if campo == 'preco_exercicio':
                            if round(float(valor_antigo or 0), 2) != round(float(valor_novo or 0), 2):
                                mudancas.append(f"Strike: {valor_antigo} -> {valor_novo}")
                                setattr(ativo, campo, valor_novo)
                        elif campo == 'data_expiracao':
                            if valor_antigo != valor_novo:
                                mudancas.append(f"Vencimento: {valor_antigo} -> {valor_novo}")
                                setattr(ativo, campo, valor_novo)
                        else:
                            if str(valor_antigo).strip() != str(valor_novo).strip():
                                mudancas.append(f"{campo}: {valor_antigo} -> {valor_novo}")
                                setattr(ativo, campo, valor_novo)

                    if mudancas:
                        ativo.save()
                        relatorio['atualizados'] += 1
                        relatorio['logs'].append(f"ATUALIZADO: {ativo.ticker} | {' | '.join(mudancas)}")
                    else:
                        relatorio['sem_alteracao'] += 1

            historico = HistoricoImportacao.objects.create(
                tipo_importacao='Cadastro de Instrumentos',
                arquivo_nome=file.name,
                novos=relatorio['novos'],
                atualizados=relatorio['atualizados'],
                sem_alteracao=relatorio['sem_alteracao'],
                detalhes=relatorio['logs']
            )
        
        return render(request, 'core/relatorio_importacao.html', {'relatorio': historico})

    return render(request, 'core/upload.html')


@user_passes_test(apenas_admin)
def upload_precos(request):
    """
    Efetua a carga de negócios consolidados diários e atualizações de preços (OHLC).
    Otimizado com mapas em memória para evitar gargalos de IO de banco de dados.
    """
    if request.method == 'POST' and request.FILES.get('arquivo'):
        file = request.FILES['arquivo']
        data_manual_str = request.POST.get('data_manual')
        start_time = time.time()

        try:
            preview_raw = file.read(50000).decode('latin1').splitlines() 
            file.seek(0)

            linha_cabecalho = next((i for i, txt in enumerate(preview_raw) if 'ISIN' in txt.upper()), None)
            if linha_cabecalho is None:
                logger.error(f"Upload de preços falhou: palavra-chave ISIN não encontrada nas primeiras linhas de {file.name}")
                messages.error(request, "Não foi possível localizar o cabeçalho 'ISIN' no arquivo.")
                return redirect('core:upload_precos')

            try:
                content = file.read().decode('utf-8-sig')
            except UnicodeDecodeError:
                file.seek(0)
                content = file.read().decode('latin1')
                
            io_string = io.StringIO(content)
            df = pd.read_csv(io_string, sep=None, skiprows=linha_cabecalho, engine='python', on_bad_lines='skip', dtype=str)
            df.columns = [str(c).strip() for c in df.columns]

            coluna_isin = next((c for c in df.columns if 'ISIN' in c.upper()), None)
            ativos_monitorados = set(AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True))
            col_ativo_obj = find_column(['Ativo', 'Ativo Objeto', 'Ticker Objeto', 'Instrumento Objeto', 'UNDERLYING', 'Asst'], df.columns)
            col_segmento = find_column(['Segmento', 'Segmento de Mercado', 'SEGMENTO'], df.columns)

            if col_segmento:
                df[col_segmento] = df[col_segmento].astype(str).str.strip().str.upper()
                df = df[df[col_segmento].isin(SEGMENTOS_PERMITIDOS)]

            df[coluna_isin] = df[coluna_isin].astype(str).str.strip()
            
            if col_ativo_obj:
                df[col_ativo_obj] = df[col_ativo_obj].astype(str).str.strip().str.upper()
                df_filtrado = df[df[col_ativo_obj].isin(ativos_monitorados)].copy()
            else:
                ativos_no_banco = AtivoB3.objects.filter(ativo_objeto__in=ativos_monitorados).values_list('codigo_isin', flat=True)
                df_filtrado = df[df[coluna_isin].isin(set(ativos_no_banco))].copy()
            
            total_para_gravar = len(df_filtrado)
            if total_para_gravar == 0:
                messages.warning(request, f"O arquivo foi lido, mas nenhum ativo monitorado foi identificado.")
                return redirect('core:upload_precos')

            relatorio = {'novos': 0, 'atualizados': 0, 'sem_alteracao': 0, 'logs': []}
            
            # Detecção posicional de colunas financeiras
            col_abertura = find_column(['Preço de abertura', 'Abertura', 'ABR', 'PRECO ABR'], df.columns)
            col_maximo = find_column(['Preço máximo', 'Máximo', 'MAXIMO', 'MAX', 'MAX.'], df.columns)
            col_minimo = find_column(['Preço mínimo', 'Mínimo', 'MINIMO', 'MIN', 'MIN.'], df.columns)
            col_fechamento = find_column(['Preço de fechamento', 'Fechamento', 'FECH', 'FECH.', 'Último', 'ULTIMO', 'ULT.', 'PRECO FECH'], df.columns)
            col_qtd_neg = find_column(['Quantidade de negócios', 'Negócios', 'NEGOCIOS', 'NEGOC.'], df.columns)
            col_vol_fin = find_column(['Volume financeiro', 'Volume', 'VOL.', 'VOL FIN'], df.columns)
            col_qtd_contratos = find_column(['Quantidade de contratos', 'Contratos', 'QTD. CONTRATOS', 'QTD CONTRATOS'], df.columns)
            col_data_neg = find_column(['Data do negócio', 'Data'], df.columns)
            col_ticker_inst = find_column(['Instrumento', 'Instrumento Financeiro', 'Ticker', 'SYMBOL', 'Instrumento financeiro'], df.columns)

            ativos_afetados = set()

            with transaction.atomic():
                mapa_objetos = {a.codigo_isin: a for a in AtivoB3.objects.filter(ativo_objeto__in=ativos_monitorados)}

                for index, (idx_df, row) in enumerate(df_filtrado.iterrows(), 1):
                    try:
                        isin = row[coluna_isin]
                        ativo_obj = mapa_objetos.get(isin)
                        
                        if not ativo_obj:
                            ativo_obj = AtivoB3.objects.filter(codigo_isin=isin).first()
                            if not ativo_obj and col_ativo_obj:
                                ticker_inst = str(row.get(col_ticker_inst, isin)).strip().upper() if col_ticker_inst else isin
                                underlying = str(row.get(col_ativo_obj)).strip().upper()
                                
                                ativo_obj = AtivoB3.objects.create(
                                    codigo_isin=isin,
                                    ticker=ticker_inst,
                                    ativo_objeto=underlying,
                                    segmento=str(row.get(col_segmento, '')).strip().upper() if col_segmento else ''
                                )
                                relatorio['logs'].append(f"Auto-criado AtivoB3: {ticker_inst} ({isin})")
                            
                            if ativo_obj:
                                mapa_objetos[isin] = ativo_obj

                        if not ativo_obj:
                            continue

                        data_linha = row.get(col_data_neg) if col_data_neg else None
                        if pd.notna(data_linha) and str(data_linha).strip() != '-':
                            dt_pregao = pd.to_datetime(data_linha, dayfirst=True).date()
                        else:
                            dt_pregao = datetime.datetime.strptime(data_manual_str, '%Y-%m-%d').date()

                        obj, created = HistoricoPreco.objects.update_or_create(
                            ativo=ativo_obj,
                            data_pregao=dt_pregao,
                            defaults={
                                'abertura': convert_to_decimal(row.get(col_abertura)) if col_abertura else 0,
                                'maximo': convert_to_decimal(row.get(col_maximo)) if col_maximo else 0,
                                'minimo': convert_to_decimal(row.get(col_minimo)) if col_minimo else 0,
                                'fechamento': convert_to_decimal(row.get(col_fechamento)) if col_fechamento else 0,
                                'quantidade_negocios': convert_to_int(row.get(col_qtd_neg)) if col_qtd_neg else 0,
                                'volume_financeiro': convert_to_decimal(row.get(col_vol_fin)) if col_vol_fin else 0,
                                'quantidade_contratos': convert_to_int(row.get(col_qtd_contratos)) if col_qtd_contratos else 0,
                            }
                        )
                        
                        if created:
                            relatorio['novos'] += 1
                        else:
                            relatorio['atualizados'] += 1
                        
                        ativos_afetados.add(ativo_obj.codigo_isin)

                    except Exception as line_error:
                        relatorio['logs'].append(f"Erro na linha {index}: {line_error}")
                        logger.warning(f"Erro de linha ignorado no upload de preços (Linha {index}): {str(line_error)}")
                        continue

            # Gatilhos automáticos de recálculos de estruturas e rolagens afetadas
            if ativos_afetados:
                estruturas_afetadas = Estrutura.objects.filter(posicoes__ativo_id__in=ativos_afetados).distinct()
                for est in estruturas_afetadas:
                    recalcular_estrutura(est)

                rolagens_afetadas = Rolagem.objects.filter(legs__ativo_id__in=ativos_afetados).distinct()
                for r in rolagens_afetadas:
                    recalcular_rolagem(r)

            historico = HistoricoImportacao.objects.create(
                tipo_importacao='Negócios Consolidados',
                arquivo_nome=file.name,
                novos=relatorio['novos'],
                atualizados=relatorio['atualizados'],
                sem_alteracao=0,
                detalhes=relatorio['logs']
            )

            logger.info(f"Importação concluída com sucesso em {time.time() - start_time:.2f}s para {file.name}")
            return render(request, 'core/relatorio_importacao.html', {'relatorio': historico})

        except Exception as e:
            logger.error(f"Erro catastrófico no processamento de preços: {str(e)}", exc_info=True)
            messages.error(request, f"Erro crítico ao processar o arquivo de preços: {e}")
            return redirect('core:upload_precos')

    return render(request, 'core/upload_precos.html', {'hoje': datetime.date.today()})


@user_passes_test(apenas_admin)
def upload_open_interest(request):
    """Efetua o processamento em lotes de múltiplos arquivos de Open Interest (Contratos em Aberto)."""
    if request.method == 'POST' and request.FILES.getlist('arquivo_csv'):
        files = request.FILES.getlist('arquivo_csv')
        total_novos = 0
        total_atualizados = 0
        todos_erros = []
        start_time = time.time()
        
        try:
            for file in files:
                content = file.read()
                stats = processar_csv_open_interest(content, file.name)
                total_novos += stats['novos']
                total_atualizados += stats['atualizados']
                
                if stats['erros']:
                    todos_erros.append(f"Erros em {file.name}: {len(stats['erros'])} problemas.")
                    for err in stats['erros']:
                        logger.warning(f"Erro de Open Interest em {file.name}: {err}")
                    
                HistoricoImportacao.objects.create(
                    tipo_importacao='Open Interest',
                    arquivo_nome=file.name,
                    novos=stats['novos'],
                    atualizados=stats['atualizados'],
                    sem_alteracao=0,
                    detalhes=stats['erros']
                )

            if todos_erros:
                for erro in todos_erros:
                    messages.warning(request, erro)
            
            messages.success(request, f"Processamento concluído em {time.time() - start_time:.2f}s! Novos: {total_novos}, Atualizados: {total_atualizados}.")
        except Exception as e:
            logger.error(f"Erro ao carregar lote de Open Interest: {str(e)}", exc_info=True)
            messages.error(request, "Erro crítico interno no upload de Open Interest.")
            
        return redirect('core:upload_open_interest')
        
    return render(request, 'core/upload_open_interest.html')


# =============================================================================
# CONSULTAS DE MARKET DATA & OPTIONS CHAIN
# =============================================================================

@user_passes_test(apenas_admin)
def lista_ativos(request):
    """Exibe o painel de Option Chain estruturado com filtros temporais de ano/mês e navegação fluida."""
    try:
        search_query = request.GET.get('search', '')
        ativo_filtro = request.GET.get('ativo_objeto', '')
        mes_filtro = request.GET.get('mes', '')
        vencimento_filtro = request.GET.get('vencimento', '')

        permitidos = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True).order_by('ticker')
        lista_ativos_objeto = list(permitidos)
        
        if not lista_ativos_objeto:
            return render(request, 'core/lista_ativos.html', {'lista_ativos_objeto': []})

        if not ativo_filtro or ativo_filtro not in lista_ativos_objeto:
            ativo_filtro = lista_ativos_objeto[0]

        # Tratamento de busca por texto global
        if search_query:
            ativos_list = AtivoB3.objects.filter(
                Q(ticker__icontains=search_query) | Q(codigo_isin__icontains=search_query)
            ).order_by('ticker')
            paginator = Paginator(ativos_list, 50)
            page_number = request.GET.get('page')
            ativos = paginator.get_page(page_number)
            return render(request, 'core/lista_ativos.html', {
                'ativos': ativos,
                'search_query': search_query,
                'ativo_filtro': ativo_filtro,
                'lista_ativos_objeto': lista_ativos_objeto,
                'is_search': True
            })

        ativos_base = AtivoB3.objects.filter(ativo_objeto=ativo_filtro).exclude(data_expiracao__isnull=True)
        datas_distintas = ativos_base.values_list('data_expiracao', flat=True).order_by('data_expiracao').distinct()
        
        meses_labels = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
        anos_dict = {}
        lista_meses_validos = []
        
        for d in datas_distintas:
            y, m = d.year, d.month
            if y not in anos_dict:
                anos_dict[y] = [
                    {'mes_num': i, 'codigo': f"{y}-{i:02d}", 'label': meses_labels[i-1], 'datas': [], 'valido': False}
                    for i in range(1, 13)
                ]
            slot = anos_dict[y][m-1]
            slot['datas'].append(d)
            if not slot['valido']:
                slot['valido'] = True
                lista_meses_validos.append(slot)
        
        if not lista_meses_validos:
            return render(request, 'core/lista_ativos.html', {
                'ativo_filtro': ativo_filtro,
                'lista_ativos_objeto': lista_ativos_objeto,
            })

        # Seleção automática de mês corrente válido
        if not mes_filtro or not any(m['codigo'] == mes_filtro for m in lista_meses_validos):
            hoje = timezone.now().date()
            meses_futuros = [m for m in lista_meses_validos if any(d >= hoje for d in m['datas'])]
            mes_ativo_dict = meses_futuros[0] if meses_futuros else lista_meses_validos[-1]
            mes_filtro = mes_ativo_dict['codigo']
        else:
            mes_ativo_dict = next(m for m in lista_meses_validos if m['codigo'] == mes_filtro)
            
        datas_do_mes = mes_ativo_dict['datas']

        # Seleção automática do vencimento
        if not vencimento_filtro:
            vencimento_mensal = ativos_base.filter(data_expiracao__in=datas_do_mes, classificacao_vencimento='Mensal').values_list('data_expiracao', flat=True).first()
            vencimento_filtro = vencimento_mensal.strftime('%Y-%m-%d') if vencimento_mensal else datas_do_mes[0].strftime('%Y-%m-%d')
        else:
            try:
                datetime.datetime.strptime(vencimento_filtro, '%Y-%m-%d')
            except ValueError:
                 vencimento_filtro = datas_do_mes[0].strftime('%Y-%m-%d')

        chain_list = get_option_chain(ativo_filtro, vencimento_filtro)
        stats_ativo = get_ativo_stats(ativo_filtro)

        context = {
            'ativo_filtro': ativo_filtro,
            'mes_filtro': mes_filtro,
            'vencimento_filtro': vencimento_filtro,
            'lista_ativos_objeto': lista_ativos_objeto,
            'anos_dict': anos_dict,
            'datas_do_mes': datas_do_mes,
            'chain_list': chain_list,
            'stats_ativo': stats_ativo,
            'is_search': False
        }
        return render(request, 'core/lista_ativos.html', context)
    except Exception as e:
        logger.error(f"Erro ao renderizar a cadeia de ativos/opções: {str(e)}", exc_info=True)
        messages.error(request, "Erro interno ao processar a grade de opções.")
        return redirect('core:home')


def detalhe_ativo(request, ticker):
    """Renderiza a página de detalhes, histórico estatístico e gráficos OHLC de um ativo individual."""
    try:
        ativo = get_object_or_404(AtivoB3, ticker=ticker)
        historico = HistoricoPreco.objects.filter(ativo=ativo).order_by('-data_pregao')
        dias_para_vencer = (ativo.data_expiracao - timezone.now().date()).days if ativo.data_expiracao else 0
        
        historico_qs = HistoricoPreco.objects.filter(ativo=ativo, fechamento__gt=0).order_by('data_pregao')
        
        ohlc_data = []
        volume_data = []
        echarts_data = []
        
        for h in historico_qs:
            label = h.data_pregao.strftime('%d/%m/%Y')
            ohlc_data.append({
                'x': label,
                'y': [float(h.abertura), float(h.maximo), float(h.minimo), float(h.fechamento)]
            })
            volume_data.append({
                'x': label,
                'y': float(h.volume_financeiro)
            })
            echarts_data.append({
                'x': label,
                'y': [float(h.abertura), float(h.fechamento), float(h.minimo), float(h.maximo)]
            })

        context = {
            'ativo': ativo,
            'historico': historico,
            'dias_para_vencer': dias_para_vencer,
            'ohlc_json': ohlc_data,
            'echarts_data': echarts_data,
            'volume_json': json.dumps(volume_data),
        }
        return render(request, 'core/detalhe_ativo.html', context)
    except Exception as e:
        logger.error(f"Erro ao extrair detalhes do ativo {ticker}: {str(e)}", exc_info=True)
        messages.error(request, f"Erro ao recuperar dados históricos do ticker {ticker}.")
        return redirect('core:lista_ativos')


# =============================================================================
# VISUALIZADORES ANALÍTICOS DE MERCADO
# =============================================================================

@user_passes_test(apenas_admin)
def liquidez_vencimentos(request):
    """Gera matrizes analíticas de liquidez de opções por vencimento, calculando médias móveis diárias."""
    try:
        ticker_filtro = request.GET.get('ticker', DEFAULT_TICKER)
        periodo_dias = 30
        apenas_mensal = True

        ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
        hoje = timezone.now().date()
        ativos_b3_base = AtivoB3.objects.filter(ativo_objeto=ticker_filtro, data_expiracao__gte=hoje)
        
        if apenas_mensal:
            ativos_b3_base = ativos_b3_base.filter(classificacao_vencimento='Mensal')

        data_limite = hoje - datetime.timedelta(days=periodo_dias + 30)
        historico = HistoricoPreco.objects.filter(
            ativo__in=ativos_b3_base,
            data_pregao__gte=data_limite
        ).select_related('ativo').order_by('data_pregao')

        if not historico.exists():
            return render(request, 'core/liquidez_vencimentos.html', {
                'ativos_monitorados': ativos_monitorados,
                'ticker_filtro': ticker_filtro,
                'empty': True
            })

        vol_por_venc_data = defaultdict(lambda: defaultdict(float))
        vol_por_venc_strike_tipo = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        datas_pregao_set, vencimentos_set = set(), set()
        
        for h in historico:
            venc, data_p = h.ativo.data_expiracao, h.data_pregao
            vol = float(h.volume_financeiro)
            tipo_str = h.ativo.tipo_opcao.upper() if h.ativo.tipo_opcao else ''
            tipo = 'CALL' if ('COMPRA' in tipo_str or 'CALL' in tipo_str) else 'PUT'
            strike = float(h.ativo.preco_exercicio or 0)
            
            vol_por_venc_data[venc][data_p] += vol
            vol_por_venc_strike_tipo[venc][strike][tipo].append({'data': data_p, 'vol': vol})
            datas_pregao_set.add(data_p)
            vencimentos_set.add(venc)

        sorted_vencimentos = sorted(list(vencimentos_set))
        resumo_vencimentos = []
        evolucao_data_all = {}
        strike_data_all = {}
        
        for venc in sorted_vencimentos:
            diario = vol_por_venc_data[venc]
            datas_venc = sorted(diario.keys())
            if not datas_venc: continue
            
            v_5d = [diario[d] for d in datas_venc[-5:]]
            v_21d = [diario[d] for d in datas_venc[-21:]]
            
            avg_5d = sum(v_5d) / len(v_5d) if v_5d else 0
            avg_21d = sum(v_21d) / len(v_21d) if v_21d else 0
            ratio = avg_5d / avg_21d if avg_21d > 0 else 0
            
            vol_call_5d = sum(sum(x['vol'] for x in vol_por_venc_strike_tipo[venc][s]['CALL'] if x['data'] in datas_venc[-5:]) for s in vol_por_venc_strike_tipo[venc])
            vol_put_5d = sum(sum(x['vol'] for x in vol_por_venc_strike_tipo[venc][s]['PUT'] if x['data'] in datas_venc[-5:]) for s in vol_por_venc_strike_tipo[venc])
            total_5d = vol_call_5d + vol_put_5d

            resumo_vencimentos.append({
                'vencimento': venc,
                'vencimento_str': venc.strftime('%Y-%m-%d'),
                'vencimento_br': venc.strftime('%d/%m/%y'),
                'avg_5d': avg_5d,
                'avg_21d': avg_21d,
                'ratio': ratio,
                'perc_call': (vol_call_5d / total_5d * 100) if total_5d > 0 else 50,
                'perc_put': (vol_put_5d / total_5d * 100) if total_5d > 0 else 50
            })

            # Montagem das evoluções temporais para o frontend (Gráficos B e C)
            v_str = venc.strftime('%Y-%m-%d')
            evolucao_data_all[v_str] = [
                {
                    'data': d.strftime('%d/%m/%Y'),
                    'vol': diario[d],
                    'sma5': sum([diario[datas_venc[j]] for j in range(max(0, idx-4), idx+1)]) / len(range(max(0, idx-4), idx+1)),
                    'sma21': sum([diario[datas_venc[j]] for j in range(max(0, idx-20), idx+1)]) / len(range(max(0, idx-20), idx+1))
                } for idx, d in enumerate(datas_venc)
            ]

            strike_data_all[v_str] = [
                {
                    'strike': s,
                    'call_vol': sum([x['vol'] for x in vol_por_venc_strike_tipo[venc][s]['CALL']][-5:]) / 5,
                    'put_vol': sum([x['vol'] for x in vol_por_venc_strike_tipo[venc][s]['PUT']][-5:]) / 5
                } for s in sorted(vol_por_venc_strike_tipo[venc].keys())
            ]

        vencimento_default = sorted(resumo_vencimentos, key=lambda x: x['avg_5d'], reverse=True)[0]['vencimento_str'] if resumo_vencimentos else ""
        ativo_obj = AtivoB3.objects.filter(ticker=ticker_filtro).first()
        preco_atm = 0.0
        if ativo_obj:
            last_p = HistoricoPreco.objects.filter(ativo=ativo_obj).order_by('-data_pregao').first()
            if last_p: preco_atm = float(last_p.fechamento)

        context = {
            'ativos_monitorados': ativos_monitorados,
            'ticker_filtro': ticker_filtro,
            'resumo_vencimentos': resumo_vencimentos,
            'evolucao_json_all': json.dumps(evolucao_data_all),
            'strike_json_all': json.dumps(strike_data_all),
            'resumo_json': json.dumps([{'vencimento': r['vencimento_br'], 'avg_5d': r['avg_5d'], 'avg_21d': r['avg_21d']} for r in resumo_vencimentos]),
            'vencimento_selecionado_default': vencimento_default,
            'preco_atm': preco_atm,
        }
        return render(request, 'core/liquidez_vencimentos.html', context)
    except Exception as e:
        logger.error(f"Erro em liquidez_vencimentos para ticker {request.GET.get('ticker')}: {str(e)}", exc_info=True)
        messages.error(request, "Falha ao processar o cálculo e distribuição de liquidez dos vencimentos.")
        return redirect('core:home')


@user_passes_test(apenas_admin)
def consultar_open_interest(request):
    """Gera matrizes analíticas de posições em aberto por strikes para fins de tomada de decisão de exposição."""
    try:
        ticker_filtro = request.GET.get('ticker', DEFAULT_TICKER)
        data_filtro_str = request.GET.get('data', None)
        vencimento_filtro_str = request.GET.get('vencimento', None)
        
        ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
        datas_disponiveis = OpenInterest.objects.values_list('data_referencia', flat=True).distinct().order_by('-data_referencia')
        
        if data_filtro_str:
            try:
                data_filtro = datetime.datetime.strptime(data_filtro_str, '%Y-%m-%d').date()
            except ValueError:
                data_filtro = datas_disponiveis.first() if datas_disponiveis else None
        else:
            data_filtro = datas_disponiveis.first() if datas_disponiveis else None

        vencimentos_disponiveis = []
        if data_filtro:
            vencimentos_disponiveis = OpenInterest.objects.filter(
                ativo_objeto=ticker_filtro, data_referencia=data_filtro
            ).values_list('ativo__data_expiracao', flat=True).distinct().order_by('ativo__data_expiracao')

        if not vencimento_filtro_str:
            vencimento_padrao = AtivoB3.objects.filter(
                ativo_objeto=ticker_filtro, data_expiracao__gte=timezone.now().date(), classificacao_vencimento='Mensal'
            ).order_by('data_expiracao').values_list('data_expiracao', flat=True).first()
            
            vencimento_filtro = vencimento_padrao if vencimento_padrao else (vencimentos_disponiveis[0] if vencimentos_disponiveis else None)
        else:
            try:
                vencimento_filtro = datetime.datetime.strptime(vencimento_filtro_str, '%Y-%m-%d').date()
            except ValueError:
                vencimento_filtro = vencimentos_disponiveis[0] if vencimentos_disponiveis else None

        dados_organizados = []
        if data_filtro and vencimento_filtro:
            posicoes = OpenInterest.objects.filter(
                ativo_objeto=ticker_filtro, data_referencia=data_filtro, ativo__data_expiracao=vencimento_filtro
            ).select_related('ativo').order_by('ativo__preco_exercicio')
            
            por_strike = defaultdict(lambda: {'call': None, 'put': None})
            for p in posicoes:
                tipo = p.ativo.tipo_opcao.upper()
                tipo_chave = 'call' if ('CALL' in tipo or 'COMPRA' in tipo) else 'put'
                por_strike[p.ativo.preco_exercicio][tipo_chave] = p
            
            for s in sorted(por_strike.keys()):
                dados_organizados.append({'strike': s, 'call': por_strike[s]['call'], 'put': por_strike[s]['put']})
            
        context = {
            'ativos_monitorados': ativos_monitorados,
            'ticker_filtro': ticker_filtro,
            'datas_disponiveis': datas_disponiveis,
            'data_filtro': data_filtro,
            'vencimentos_disponiveis': vencimentos_disponiveis,
            'vencimento_filtro': vencimento_filtro,
            'dados_organizados': dados_organizados,
            'empty': not bool(dados_organizados),
        }
        return render(request, 'core/open_interest.html', context)
    except Exception as e:
        logger.error(f"Erro em consultar_open_interest: {str(e)}", exc_info=True)
        messages.error(request, "Erro interno ao processar a tabela de Open Interest.")
        return redirect('core:home')


@user_passes_test(apenas_admin)
def grafico_open_interest(request):
    """Estrutura os dados agregados de Open Interest para renderização em gráficos de barras empilhadas."""
    try:
        ticker_filtro = request.GET.get('ticker', DEFAULT_TICKER)
        vencimento_filtro_str = request.GET.get('vencimento', None)
        tipo_filtro = request.GET.get('tipo', 'TODOS')
        
        ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
        ultima_data = OpenInterest.objects.aggregate(Max('data_referencia'))['data_referencia__max']
        
        vencimentos_disponiveis = []
        if ultima_data:
            vencimentos_disponiveis = OpenInterest.objects.filter(
                ativo_objeto=ticker_filtro, data_referencia=ultima_data
            ).values_list('ativo__data_expiracao', flat=True).distinct().order_by('ativo__data_expiracao')

        if not vencimento_filtro_str and vencimentos_disponiveis:
            vencimento_padrao = AtivoB3.objects.filter(
                ativo_objeto=ticker_filtro, data_expiracao__gte=timezone.now().date(), classificacao_vencimento='Mensal'
            ).order_by('data_expiracao').values_list('data_expiracao', flat=True).first()
            vencimento_filtro = vencimento_padrao if vencimento_padrao else vencimentos_disponiveis[0]
        elif vencimento_filtro_str:
            vencimento_filtro = datetime.datetime.strptime(vencimento_filtro_str, '%Y-%m-%d').date()
        else:
            vencimento_filtro = None

        chart_data = {'strikes': [], 'coberta': [], 'descoberta': [], 'trava': []}
        
        if ultima_data and vencimento_filtro:
            qs = OpenInterest.objects.filter(
                ativo_objeto=ticker_filtro, data_referencia=ultima_data, ativo__data_expiracao=vencimento_filtro
            ).select_related('ativo')
            
            if tipo_filtro == 'CALL':
                qs = qs.filter(Q(ativo__tipo_opcao__icontains='CALL') | Q(ativo__tipo_opcao__icontains='COMPRA'))
            elif tipo_filtro == 'PUT':
                qs = qs.filter(Q(ativo__tipo_opcao__icontains='PUT') | Q(ativo__tipo_opcao__icontains='VENDA'))
                
            data_por_strike = defaultdict(lambda: {'coberta': 0, 'descoberta': 0, 'trava': 0})
            for p in qs:
                s = float(p.ativo.preco_exercicio)
                data_por_strike[s]['coberta'] += p.quantidade_coberta
                data_por_strike[s]['descoberta'] += p.quantidade_descoberta
                data_por_strike[s]['trava'] += p.total_travas
                
            for s in sorted(data_por_strike.keys()):
                chart_data['strikes'].append(s)
                chart_data['coberta'].append(data_por_strike[s]['coberta'])
                chart_data['descoberta'].append(data_por_strike[s]['descoberta'])
                chart_data['trava'].append(data_por_strike[s]['trava'])

        context = {
            'ativos_monitorados': ativos_monitorados,
            'ticker_filtro': ticker_filtro,
            'vencimentos_disponiveis': vencimentos_disponiveis,
            'vencimento_filtro': vencimento_filtro,
            'tipo_filtro': tipo_filtro,
            'chart_data_json': json.dumps(chart_data),
            'ultima_data': ultima_data,
        }
        return render(request, 'core/grafico_oi.html', context)
    except Exception as e:
        logger.error(f"Erro ao computar gráfico de Open Interest: {str(e)}", exc_info=True)
        messages.error(request, "Falha ao gerar o conjunto de dados visuais do Open Interest.")
        return redirect('core:home')


@user_passes_test(apenas_admin)
def barreiras_open_interest(request):
    """Mapeia as maiores concentrações (barreiras/suportes/resistências) de posições em aberto."""
    try:
        ticker_filtro = request.GET.get('ticker', DEFAULT_TICKER)
        try:
            min_posicoes = int(request.GET.get('min_posicoes', '2000000'))
        except ValueError:
            min_posicoes = 2000000
        
        ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
        ultima_data = OpenInterest.objects.aggregate(Max('data_referencia'))['data_referencia__max']
        
        dados_barreiras = []
        if ultima_data:
            dados_barreiras = OpenInterest.objects.filter(
                ativo_objeto=ticker_filtro, data_referencia=ultima_data, total_posicoes__gte=min_posicoes
            ).select_related('ativo').order_by('-total_posicoes')
            
        context = {
            'ativos_monitorados': ativos_monitorados,
            'ticker_filtro': ticker_filtro,
            'min_posicoes': min_posicoes,
            'ultima_data': ultima_data,
            'dados_barreiras': dados_barreiras,
        }
        return render(request, 'core/barreiras_oi.html', context)
    except Exception as e:
        logger.error(f"Erro ao mapear barreiras de Open Interest: {str(e)}", exc_info=True)
        messages.error(request, "Não foi possível carregar as barreiras físicas de Open Interest.")
        return redirect('core:home')


@user_passes_test(apenas_admin)
def fluxo_open_interest(request):
    """Calcula a evolução histórica do Put/Call Ratio (PCR) tanto de Open Interest quanto de volumes diários."""
    try:
        ticker_filtro = request.GET.get('ticker', DEFAULT_TICKER)
        vencimento_filtro_str = request.GET.get('vencimento', 'Todos')
        
        ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
        vencimentos_disponiveis = OpenInterest.objects.filter(ativo_objeto=ticker_filtro).values_list('ativo__data_expiracao', flat=True).distinct().order_by('ativo__data_expiracao')
        
        # Bloco 1: Histórico OI
        qs_oi = OpenInterest.objects.filter(ativo_objeto=ticker_filtro).select_related('ativo')
        if vencimento_filtro_str and vencimento_filtro_str != 'Todos':
            try:
                venc_date = datetime.datetime.strptime(vencimento_filtro_str, '%Y-%m-%d').date()
                qs_oi = qs_oi.filter(ativo__data_expiracao=venc_date)
            except ValueError: pass
                
        oi_por_data = defaultdict(lambda: {'call': 0, 'put': 0})
        for p in qs_oi:
            tipo = p.ativo.tipo_opcao.upper() if p.ativo.tipo_opcao else ''
            dt_ref = p.data_referencia.strftime('%d/%m/%Y')
            chave = 'call' if ('CALL' in tipo or 'COMPRA' in tipo) else 'put'
            oi_por_data[dt_ref][chave] += p.total_posicoes
                
        datas_oi = [d.strftime('%d/%m/%Y') for d in sorted([datetime.datetime.strptime(k, '%d/%m/%Y').date() for k in oi_por_data.keys()])]
        
        chart_pcr = {'datas': datas_oi, 'pcr': [], 'pct_call': [], 'pct_put': []}
        chart_vol_oi = {'datas': datas_oi, 'call': [], 'put': [], 'total': []}
        
        for d in datas_oi:
            c, p = oi_por_data[d]['call'], oi_por_data[d]['put']
            total = c + p
            chart_pcr['pcr'].append(round(p / c, 2) if c > 0 else 0)
            chart_pcr['pct_call'].append(round(c / total * 100, 2) if total > 0 else 0)
            chart_pcr['pct_put'].append(round(p / total * 100, 2) if total > 0 else 0)
            chart_vol_oi['call'].append(c)
            chart_vol_oi['put'].append(p)
            chart_vol_oi['total'].append(total)
            
        # Bloco 2: Histórico Financeiro
        qs_hist = HistoricoPreco.objects.filter(ativo__ativo_objeto=ticker_filtro).select_related('ativo')
        if vencimento_filtro_str and vencimento_filtro_str != 'Todos':
            try:
                venc_date = datetime.datetime.strptime(vencimento_filtro_str, '%Y-%m-%d').date()
                qs_hist = qs_hist.filter(ativo__data_expiracao=venc_date)
            except ValueError: pass
                
        fin_por_data = defaultdict(lambda: {'call': 0.0, 'put': 0.0})
        for h in qs_hist:
            tipo = h.ativo.tipo_opcao.upper() if h.ativo.tipo_opcao else ''
            dt_pregao = h.data_pregao.strftime('%d/%m/%Y')
            chave = 'call' if ('CALL' in tipo or 'COMPRA' in tipo) else 'put'
            fin_por_data[dt_pregao][chave] += float(h.volume_financeiro)
                
        datas_fin = [d.strftime('%d/%m/%Y') for d in sorted([datetime.datetime.strptime(k, '%d/%m/%Y').date() for k in fin_por_data.keys()])]
        chart_fin = {'datas': datas_fin, 'call': [], 'put': [], 'total': []}
        for d in datas_fin:
            c, p = fin_por_data[d]['call'], fin_por_data[d]['put']
            chart_fin['call'].append(round(c, 2))
            chart_fin['put'].append(round(p, 2))
            chart_fin['total'].append(round(c + p, 2))
            
        context = {
            'ativos_monitorados': ativos_monitorados,
            'ticker_filtro': ticker_filtro,
            'vencimentos_disponiveis': vencimentos_disponiveis,
            'vencimento_filtro_str': vencimento_filtro_str,
            'chart_pcr_json': json.dumps(chart_pcr),
            'chart_vol_oi_json': json.dumps(chart_vol_oi),
            'chart_fin_json': json.dumps(chart_fin),
        }
        return render(request, 'core/fluxo_oi.html', context)
    except Exception as e:
        logger.error(f"Erro crítico em fluxo_open_interest: {str(e)}", exc_info=True)
        messages.error(request, "Erro interno ao calcular as matrizes de fluxo de contratos.")
        return redirect('core:home')


# =============================================================================
# OPERAÇÕES DE LIMPEZA E MANUTENÇÃO DO BANCO (ADMIN)
# =============================================================================

@user_passes_test(apenas_admin)
def limpar_ativos_nao_monitorados(request):
    """Varre e expurga da base todos os ativos secundários/antigos não listados como monitorados."""
    try:
        permitidos = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True)
        ativos_para_deletar = AtivoB3.objects.exclude(ativo_objeto__in=permitidos)
        quantidade = ativos_para_deletar.count()
        
        if quantidade > 0:
            ativos_para_deletar.delete()
            messages.success(request, f"Limpeza concluída! {quantidade} ativos obsoletos foram expurgados.")
        else:
            messages.info(request, "O banco já está limpo e consolidado.")
    except Exception as e:
        logger.error(f"Erro na limpeza de ativos não monitorados: {str(e)}", exc_info=True)
        messages.error(request, "Erro durante a execução do processo de limpeza física.")
        
    return redirect('core:home')


@user_passes_test(apenas_admin)
def remover_historico_precos_duplicados(request):
    """Identifica e remove chaves duplicadas de (ativo, data_pregao), mantendo o maior ID."""
    try:
        duplicados = HistoricoPreco.objects.values('ativo', 'data_pregao').annotate(
            count=Count('id'), max_id=Max('id')
        ).filter(count__gt=1)
        
        total_removidos = 0
        with transaction.atomic():
            for item in duplicados:
                ids_para_remover = HistoricoPreco.objects.filter(
                    ativo_id=item['ativo'], data_pregao=item['data_pregao']
                ).exclude(id=item['max_id']).values_list('id', flat=True)
                
                removidos, _ = HistoricoPreco.objects.filter(id__in=ids_para_remover).delete()
                total_removidos += removidos

        if total_removidos > 0:
            messages.success(request, f"Sucesso! {total_removidos} registros duplicados de preços foram removidos.")
        else:
            messages.info(request, "Nenhuma duplicidade encontrada na base de preços.")
    except Exception as e:
        logger.error(f"Falha ao remover preços duplicados: {str(e)}", exc_info=True)
        messages.error(request, "Erro interno de concorrência ao processar a limpeza de duplicados.")
        
    return redirect('core:home')


@user_passes_test(apenas_admin)
def recalcular_estruturas(request):
    """Gatilho manual assíncrono/síncrono para recalcular o mark-to-market de todas as carteiras e estruturas."""
    try:
        estruturas = Estrutura.objects.all()
        total = estruturas.count()
        for est in estruturas:
            recalcular_estrutura(est)
        messages.success(request, f"Sucesso! {total} estruturas operacionais foram recalculadas.")
    except Exception as e:
        logger.error(f"Erro no recálculo global de estruturas: {str(e)}", exc_info=True)
        messages.error(request, "Falha no motor de recálculo matemático de estruturas.")
    return redirect('core:home')


@user_passes_test(apenas_admin)
def sync_precos_b3(request):
    """Aciona a sincronização nativa direta via API/Serviço B3."""
    try:
        stats = sync_precos_negocios_b3()
        messages.success(request, f"Sincronização concluída! {stats['novos']} novos carregados.")
    except Exception as e:
        logger.error(f"Falha na sincronização direta B3: {str(e)}", exc_info=True)
        messages.error(request, "Não foi possível estabelecer contato com a base de dados de sincronização.")
    return redirect('core:home')


@user_passes_test(apenas_admin)
def recalcular_rolagens(request):
    """Gatilho manual para reprocessamento do spread implícito das rolagens de opções cadastradas."""
    try:
        count = recalcular_todas_rolagens()
        messages.success(request, f"Sucesso! {count} spreads de rolagem atualizados.")
    except Exception as e:
        logger.error(f"Erro ao recalcular rolagens: {str(e)}", exc_info=True)
        messages.error(request, "Ocorreu um erro no cálculo analítico dos spreads.")
    return redirect('core:home')


# =============================================================================
# INTRACONTROL DB VIEWER (SERVER-SIDE DATATABLES)
# =============================================================================

@user_passes_test(apenas_admin)
def db_viewer(request):
    """View de renderização do painel gerenciador e inspetor de tabelas SQL brutas do ecossistema."""
    tables_info = []
    for db_alias in connections:
        try:
            tables = connections[db_alias].introspection.table_names()
            for t in sorted(tables):
                tables_info.append({'db': db_alias, 'table': t})
        except Exception as conn_err:
            logger.warning(f"Banco ignorado no DB Viewer ({db_alias}): {str(conn_err)}")
            pass
            
    return render(request, 'core/db_viewer.html', {'tables_info': tables_info})


@user_passes_test(apenas_admin)
def db_viewer_data(request):
    """Endpoint de processamento server-side com paginação, ordenação dinâmica e filtros nativos SQL."""
    db_alias = request.GET.get('db', 'default')
    table_name = request.GET.get('table')
    
    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 25))
    search_value = request.GET.get('search[value]', '').strip()
    
    if not table_name:
        return JsonResponse({'error': 'Nenhuma tabela especificada.'}, status=400)

    try:
        conn = connections[db_alias]
    except KeyError:
        return JsonResponse({'error': 'Database Alias inválido.'}, status=400)
        
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 0")
            columns = [col[0] for col in cursor.description]
            
            where_clause, params = "", []
            if search_value:
                conditions = []
                for col in columns:
                    if conn.vendor == 'postgresql':
                        conditions.append(f'"{col}"::text ILIKE %s')
                    else:
                        conditions.append(f'CAST("{col}" AS TEXT) LIKE %s')
                    params.append(f'%{search_value}%')
                if conditions:
                    where_clause = "WHERE " + " OR ".join(conditions)
            
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            recordsTotal = cursor.fetchone()[0]
            
            recordsFiltered = recordsTotal
            if where_clause:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name} {where_clause}", params)
                recordsFiltered = cursor.fetchone()[0]
            
            order_col_idx = request.GET.get('order[0][column]')
            order_dir = request.GET.get('order[0][dir]', 'asc')
            order_clause = ""
            if order_col_idx is not None and order_col_idx.isdigit():
                idx = int(order_col_idx)
                col_name = request.GET.get(f'columns[{idx}][data]')
                if col_name in columns:
                    if order_dir.lower() not in ['asc', 'desc']:
                        order_dir = 'asc'
                    order_clause = f'ORDER BY "{col_name}" {order_dir}'

            query = f"SELECT * FROM {table_name} {where_clause} {order_clause} LIMIT %s OFFSET %s"
            cursor.execute(query, params + [length, start])
            rows = cursor.fetchall()

            data = []
            for row in rows:
                row_dict = {}
                for col, val in zip(columns, row):
                    row_dict[col] = str(val) if val is not None else ''
                data.append(row_dict)
                
        return JsonResponse({
            "draw": draw,
            "recordsTotal": recordsTotal,
            "recordsFiltered": recordsFiltered,
            "columns": columns,
            "data": data
        })
    except Exception as e:
        logger.error(f"Erro na execução server-side do DataTables para {table_name}: {str(e)}", exc_info=True)
        return JsonResponse({'error': f'Falha interna na query: {str(e)}'}, status=500)


@user_passes_test(apenas_admin)
def db_viewer_export(request):
    """Gera um arquivo estruturado CSV baseado no filtro atual limitando a 50 mil registros por segurança."""
    db_alias = request.GET.get('db', 'default')
    table_name = request.GET.get('table')
    search_value = request.GET.get('search', '').strip()
    
    if not table_name:
        return HttpResponse('Tabela não informada.', status=400)

    try:
        conn = connections[db_alias]
    except KeyError:
        return HttpResponse('Conexão de Banco não encontrada.', status=400)
        
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 0")
            columns = [col[0] for col in cursor.description]
            
            where_clause, params = "", []
            if search_value:
                conditions = []
                for col in columns:
                    if conn.vendor == 'postgresql':
                        conditions.append(f'"{col}"::text ILIKE %s')
                    else:
                        conditions.append(f'CAST("{col}" AS TEXT) LIKE %s')
                    params.append(f'%{search_value}%')
                if conditions:
                    where_clause = "WHERE " + " OR ".join(conditions)
            
            query = f"SELECT * FROM {table_name} {where_clause} LIMIT %s"
            cursor.execute(query, params + [MAX_EXPORT_ROWS])
            
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{table_name}_export.csv"'
            response.write(u'\ufeff'.encode('utf8')) # Excel BOM fix
            
            writer = csv.writer(response, delimiter=';')
            writer.writerow(columns)
            
            for row in cursor.fetchall():
                writer.writerow([str(r) if r is not None else '' for r in row])
                
        return response
    except Exception as e:
        logger.error(f"Erro na exportação via CSV da tabela {table_name}: {str(e)}", exc_info=True)
        return HttpResponse('Erro interno gerado ao processar a planilha.', status=500)