import logging
import time
import math
from django.core.cache import cache
from datetime import datetime
from decimal import Decimal
from django.db import transaction
from django.db.models import Min

from dadosb3.models import CotacaoHistorica, BoletimNegocioDiario, NegocioDiario, Instrumento
from core.models import AtivoB3, HistoricoPreco, AtivoMonitorado
from trading.services import recalcular_todas_rolagens

logger = logging.getLogger('dadosb3')

def safe_div(a, b):
    if a is not None and b is not None and b > 0:
        return Decimal(a) / Decimal(b)
    return None

def normalize_segmento(codbdi, tpmerc):
    codbdi = str(codbdi).strip() if codbdi else ""
    tpmerc = str(tpmerc).strip() if tpmerc else ""

    if codbdi == "78" or tpmerc == "070":
        return "EQUITY CALL"
    if codbdi == "82" or tpmerc == "080":
        return "EQUITY PUT"
    if codbdi in ["02", "12"] or tpmerc == "010":
        return "CASH"
    if codbdi == "96" or tpmerc == "020":
        return "MERCADO FRACIONARIO"
    return "OUTROS"

def consolidar_negocios(min_date=None, task_id=None):
    """Consolida os dados de CotacaoHistorica e BoletimNegocioDiario em NegocioDiario a partir de min_date"""
    logger.info(f"Iniciando consolidacao de negocios a partir de {min_date}")
    
    dates_to_process = set()
    if min_date:
        dates_cothist = set(CotacaoHistorica.objects.filter(dtpreg__gte=min_date).values_list('dtpreg', flat=True).distinct())
        dates_boletim = set(BoletimNegocioDiario.objects.filter(data_pregao__gte=min_date).values_list('data_pregao', flat=True).distinct())
    else:
        dates_cothist = set(CotacaoHistorica.objects.values_list('dtpreg', flat=True).distinct())
        dates_boletim = set(BoletimNegocioDiario.objects.values_list('data_pregao', flat=True).distinct())
        
    dates_to_process = sorted(list(dates_cothist | dates_boletim))
    
    if not dates_to_process:
        logger.info("Nenhuma data para consolidar.")
        if task_id:
            cache.set(f'task_{task_id}', 100, timeout=3600)
            cache.set(f'task_{task_id}_summary', "Nenhuma data para consolidar.", timeout=3600)
        return 0

    mapa_isin_por_ticker = dict(Instrumento.objects.values_list('ticker', 'isin'))
    total_processed = 0
    
    if task_id:
        start_time_task = time.time()
        cache.set(f'task_{task_id}_stats', {'processed': 0, 'total': len(dates_to_process), 'speed': 0, 'start_time': start_time_task, 'unit': 'dias'}, timeout=3600)

    for index, dt in enumerate(dates_to_process, 1):
        golden_map = {}
        for e in NegocioDiario.objects.filter(data_pregao=dt):
            golden_map[e.isin] = e

        for c in CotacaoHistorica.objects.filter(dtpreg=dt):
            isin = mapa_isin_por_ticker.get(c.codneg) or c.codisi
            if not isin:
                continue

            if isin not in golden_map:
                golden_map[isin] = NegocioDiario(
                    data_pregao=c.dtpreg,
                    ticker=c.codneg,
                    isin=isin,
                    preco_abertura=c.preabe,
                    preco_minimo=c.premin,
                    preco_maximo=c.premax,
                    preco_fechamento=c.preult,
                    preco_vwap=safe_div(c.voltot, c.quatot),
                    qtd_negocios=c.totneg,
                    qtd_contratos=c.quatot,
                    volume_financeiro=c.voltot,
                    segmento=normalize_segmento(c.codbdi, c.tpmerc)
                )
            else:
                g = golden_map[isin]
                if not g.preco_abertura:    g.preco_abertura    = c.preabe
                if not g.preco_minimo:      g.preco_minimo      = c.premin
                if not g.preco_maximo:      g.preco_maximo      = c.premax
                if not g.preco_fechamento:  g.preco_fechamento  = c.preult
                if not g.preco_vwap:        g.preco_vwap        = safe_div(c.voltot, c.quatot)
                if not g.qtd_negocios:      g.qtd_negocios      = c.totneg
                if not g.qtd_contratos:     g.qtd_contratos     = c.quatot
                if not g.volume_financeiro: g.volume_financeiro = c.voltot
                if not g.segmento or g.segmento == "OUTROS":
                    g.segmento = normalize_segmento(c.codbdi, c.tpmerc)

        for b in BoletimNegocioDiario.objects.filter(data_pregao=dt):
            if b.isin not in golden_map:
                golden_map[b.isin] = NegocioDiario(
                    data_pregao=b.data_pregao,
                    ticker=b.ticker,
                    isin=b.isin,
                    preco_abertura=b.preco_abertura,
                    preco_minimo=b.preco_minimo,
                    preco_maximo=b.preco_maximo,
                    preco_fechamento=b.preco_fechamento,
                    preco_vwap=safe_div(b.volume_financeiro, b.qtd_contratos),
                    qtd_negocios=b.qtd_negocios,
                    qtd_contratos=b.qtd_contratos,
                    volume_financeiro=b.volume_financeiro,
                    segmento=b.segmento if b.segmento else "OUTROS"
                )
            else:
                g = golden_map[b.isin]
                if not g.preco_abertura:    g.preco_abertura    = b.preco_abertura
                if not g.preco_minimo:      g.preco_minimo      = b.preco_minimo
                if not g.preco_maximo:      g.preco_maximo      = b.preco_maximo
                if not g.preco_fechamento:  g.preco_fechamento  = b.preco_fechamento
                if not g.preco_vwap:        g.preco_vwap        = safe_div(b.volume_financeiro, b.qtd_contratos)
                if not g.qtd_negocios:      g.qtd_negocios      = b.qtd_negocios
                if not g.qtd_contratos:     g.qtd_contratos     = b.qtd_contratos
                if not g.volume_financeiro: g.volume_financeiro = b.volume_financeiro
                if not g.segmento or g.segmento == "OUTROS":
                    g.segmento = b.segmento if b.segmento else "OUTROS"

        to_create = [v for v in golden_map.values() if not v.pk]
        to_update = [v for v in golden_map.values() if v.pk]

        if to_create:
            NegocioDiario.objects.bulk_create(to_create, ignore_conflicts=True)
        if to_update:
            NegocioDiario.objects.bulk_update(to_update, [
                'preco_abertura', 'preco_minimo', 'preco_maximo', 'preco_fechamento',
                'preco_vwap', 'qtd_negocios', 'qtd_contratos', 'volume_financeiro', 'segmento'
            ])
            
        total_processed += len(to_create) + len(to_update)

    logger.info(f"Consolidacao concluida. Registros consolidados: {total_processed}")
    return total_processed

def sincronizar_historico_preco(min_date=None, task_id=None):
    """Sincroniza a tabela NegocioDiario (Golden Source) com HistoricoPreco (apenas para Ativos Monitorados)"""
    logger.info(f"Sincronizando HistoricoPreco a partir de {min_date}")
    
    ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True)
    mapa_objetos = {a.codigo_isin: a for a in AtivoB3.objects.filter(ativo_objeto__in=ativos_monitorados)}
    set_isins = set(mapa_objetos.keys())
    
    if not set_isins:
        logger.info("Nenhum ativo monitorado configurado.")
        return 0
        
    qs = NegocioDiario.objects.filter(isin__in=set_isins)
    if min_date:
        qs = qs.filter(data_pregao__gte=min_date)
        
    total_sucesso = 0
    count = 0
    
    # Processar um a um via update_or_create (mais lento porem seguro para logica existente)
    # ou usar bulk se preferir. Usaremos update_or_create como no import_negocios
    for n in qs.iterator(chunk_size=2000):
        try:
            ativo_obj = mapa_objetos.get(n.isin)
            if not ativo_obj:
                continue
                
            HistoricoPreco.objects.update_or_create(
                ativo=ativo_obj,
                data_pregao=n.data_pregao,
                defaults={
                    'abertura': float(n.preco_abertura) if n.preco_abertura else 0.0,
                    'maximo': float(n.preco_maximo) if n.preco_maximo else 0.0,
                    'minimo': float(n.preco_minimo) if n.preco_minimo else 0.0,
                    'fechamento': float(n.preco_fechamento) if n.preco_fechamento else 0.0,
                    # No NegocioDiario nao tem ajuste. O ajuste fica em BoletimNegocioDiario,
                    # Mas o historico preco aceita isso? Sim, import_negocios le o csv e pega ajuste se tiver, senao deixa o que tem.
                    'quantidade_negocios': n.qtd_negocios if n.qtd_negocios else 0,
                    'volume_financeiro': float(n.volume_financeiro) if n.volume_financeiro else 0.0,
                    'quantidade_contratos': n.qtd_contratos if n.qtd_contratos else 0,
                }
            )
            total_sucesso += 1
            count += 1
            if count % 1000 == 0:
                logger.info(f"Sincronizando HistoricoPreco... {count} registros")
        except Exception as e:
            logger.error(f"Erro ao sincronizar HistoricoPreco para isin {n.isin}: {e}")

    logger.info(f"Sincronizacao concluida. {total_sucesso} registros atualizados.")
    return total_sucesso

def rotinas_automaticas_pos_ingestao(nova_data_minima, task_id=None):
    """Executa consolidacao, sync e recalculos a partir da menor data identificada na ingestao"""
    if not nova_data_minima:
        return
        
    try:
        if task_id: cache.set(f'task_{task_id}_stage', 'Consolidando Negócios (2/3)', timeout=3600)
        # 1. Consolidar
        consolidar_negocios(nova_data_minima, task_id=None) # task_id=None aqui para não sobreescrever o 0-100 da etapa inteira
        if task_id: cache.set(f'task_{task_id}', 60, timeout=3600)
        
        # 2. Sincronizar Historico Preco
        sincronizar_historico_preco(nova_data_minima, task_id=None)
        if task_id: cache.set(f'task_{task_id}', 70, timeout=3600)
        
        if task_id: cache.set(f'task_{task_id}_stage', 'Ajustes de Cálculos e Estruturas (3/3)', timeout=3600)
        # 3. Recalcular Rolagens
        recalcular_todas_rolagens()
        if task_id: cache.set(f'task_{task_id}', 85, timeout=3600)
        
        # 4. Recalcular Estruturas
        from trading.models import Estrutura
        from trading.services import recalcular_estrutura
        for est in Estrutura.objects.all():
            recalcular_estrutura(est)
        
        if task_id: cache.set(f'task_{task_id}', 100, timeout=3600)
        logger.info("Rotinas automaticas pos ingestao concluidas com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao executar rotinas automaticas pos ingestao: {e}")

def sincronizar_posicoes_abertas():
    """Sincroniza PosicaoAberta (dadosb3) para OpenInterest (core)"""
    from dadosb3.models import PosicaoAberta
    from core.models import OpenInterest, AtivoB3, AtivoMonitorado
    from django.db import transaction
    
    logger.info("Iniciando sincronização de posições em aberto")
    ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True)
    mapa_objetos = {a.codigo_isin: a for a in AtivoB3.objects.filter(ativo_objeto__in=ativos_monitorados)}
    set_isins = set(mapa_objetos.keys())
    
    if not set_isins:
        return 0

    posicoes = PosicaoAberta.objects.filter(isin__in=set_isins)
    sucesso = 0
    
    for chunk in [posicoes[i:i + 2000] for i in range(0, posicoes.count(), 2000)]:
        with transaction.atomic():
            for p in chunk:
                ativo_obj = mapa_objetos.get(p.isin)
                if not ativo_obj: continue
                
                # Regra de total = abertos + descobertos + travas
                tot_pos = (p.contratos_abertos or 0) + (p.qtd_descoberta or 0) + (p.posicoes_bloqueadas or 0)
                
                OpenInterest.objects.update_or_create(
                    ativo=ativo_obj,
                    data_referencia=p.data,
                    defaults={
                        'ticker': p.ticker or '',
                        'ativo_objeto': ativo_obj.ativo_objeto or '',
                        'codigo_expiracao': p.codigo_expiracao or '',
                        'segmento': p.segmento or '',
                        'contratos_em_aberto': p.contratos_abertos or 0,
                        'variacao_contratos': p.variacao_abertos or 0,
                        'id_distribuicao': p.id_distribuicao or '',
                        'quantidade_coberta': p.qtd_coberta or 0,
                        'total_travas': p.posicoes_bloqueadas or 0,
                        'quantidade_descoberta': p.qtd_descoberta or 0,
                        'total_posicoes': tot_pos,
                        'quantidade_tomadores': p.qtd_tomadores or 0,
                        'quantidade_doadores': p.qtd_doadores or 0,
                        'quantidade_atual': p.qtd_atual or 0,
                        'contratos_travados': p.contratos_travados or 0,
                        'contratos_transferencia': p.contratos_transferidos or 0,
                        'preco_termo': p.preco_termo or 0
                    }
                )
                sucesso += 1
    logger.info(f"Sincronização de posições em aberto concluída: {sucesso} registros.")
    return sucesso
