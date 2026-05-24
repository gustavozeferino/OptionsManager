from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from .models import Estrutura, Ordem, PosicaoConsolidada, DailySnapshot, Rolagem, RolagemLeg, RolagemSnapshot
from .forms import EstruturaForm, RolagemForm, RolagemLegFormSet
import json
from .services import importar_ordens_profit, recalcular_rolagem, recalcular_todas_rolagens
from collections import defaultdict
from datetime import datetime, timedelta


@login_required
def criar_estrutura(request):
    """Cria uma nova estrutura de trade."""
    if request.method == 'POST':
        form = EstruturaForm(request.POST)
        if form.is_valid():
            estrutura = form.save(commit=False)
            estrutura.usuario = request.user
            
            from django.utils.text import slugify
            import uuid
            
            base_slug = slugify(estrutura.nome)
            if not base_slug:
                base_slug = "estrutura"
            
            unique_id = str(uuid.uuid4().hex)[:6]
            estrutura.slug = f"{base_slug}-{unique_id}"
            
            estrutura.save()
            messages.success(request, f"Estrutura '{estrutura.nome}' criada com sucesso!")
            return redirect('trading:detalhe_estrutura', slug=estrutura.slug)
    else:
        form = EstruturaForm()
    
    return render(request, 'trading/criar_estrutura.html', {'form': form})

@login_required
def adicionar_ordem(request, slug):
    """Lança uma nova ordem manualmente para uma estrutura."""
    estrutura = get_object_or_404(Estrutura, usuario=request.user, slug=slug)
    from .forms import OrdemForm
    
    if request.method == 'POST':
        form = OrdemForm(request.POST)
        if form.is_valid():
            ordem = form.save(commit=False)
            ordem.estrutura = estrutura
            ordem.save()
            
            # Recalcula a estrutura após alteração manual
            from .services import recalcular_estrutura
            recalcular_estrutura(estrutura)
            
            messages.success(request, f"Ordem de {ordem.ativo.ticker} adicionada com sucesso!")
            
            if 'salvar_e_adicionar' in request.POST:
                return redirect('trading:adicionar_ordem_manual', slug=estrutura.slug)
            else:
                return redirect('trading:detalhe_estrutura', slug=estrutura.slug)
    else:
        form = OrdemForm()
    
    return render(request, 'trading/adicionar_ordem.html', {'form': form, 'estrutura': estrutura})

from django.http import JsonResponse
from core.models import AtivoB3

@login_required
def buscar_ativos(request):
    """Retorna lista de ativos para o Select2 via AJAX, filtrando pelo termo digitado."""
    termo = request.GET.get('q', '').strip()
    ativos = AtivoB3.objects.filter(ticker__icontains=termo)[:20] if termo else AtivoB3.objects.all()[:20]
    
    resultados = [{
        'id': ativo.codigo_isin, 
        'text': f"{ativo.ticker} - {ativo.ativo_objeto}",
        'tipo': ativo.tipo_opcao,
        'strike': str(ativo.preco_exercicio) if ativo.preco_exercicio else ''
    } for ativo in ativos]
    return JsonResponse({'results': resultados})

@login_required
def detalhe_ativo_json(request, codigo_isin):
    """Retorna os detalhes de um ativo (como o strike) para a interface de ordem."""
    ativo = get_object_or_404(AtivoB3, codigo_isin=codigo_isin)
    
    # Se preco_exercicio for nulo, retorna vazio para a interface
    strike = str(ativo.preco_exercicio) if ativo.preco_exercicio else ''
    
    return JsonResponse({'strike': strike, 'ticker': ativo.ticker})

@login_required
def dashboard_estruturas(request):
    """
    Exibe o resumo das estruturas do usuário (Painel Principal de Trading).
    """
    # Filtra estruturas do usuário
    estruturas = Estrutura.objects.filter(usuario=request.user)
    
    # "Sem Estrutura" só aparece se tiver ordens
    estrutura_sem_estrutura = estruturas.filter(slug='sem-estrutura').first()
    if estrutura_sem_estrutura and not estrutura_sem_estrutura.ordens.exists():
        estruturas = estruturas.exclude(slug='sem-estrutura')
    
    estruturas_ativas = estruturas.filter(status='ABERTA')
    estruturas_fechadas = estruturas.filter(status='FECHADA')
    
    total_pl_realizado = estruturas.aggregate(Sum('pl_realizado'))['pl_realizado__sum'] or 0
    total_pl_aberto = estruturas.aggregate(Sum('pl_aberto'))['pl_aberto__sum'] or 0
    valor_total_carteira = estruturas.aggregate(Sum('valor_total'))['valor_total__sum'] or 0
    total_exposicao = estruturas_ativas.aggregate(Sum('exposicao_atual'))['exposicao_atual__sum'] or 0
    
    # Prepara dados para o gráfico ECharts (evolução do patrimônio) com lógica de fill-forward
    # Isso garante que o gráfico não caia se uma estrutura não tiver dado para um dia específico
    from collections import defaultdict
    
    # Busca todos os snapshots relevantes
    todos_snapshots = DailySnapshot.objects.filter(estrutura__usuario=request.user).order_by('data', 'estrutura_id')
    
    if not todos_snapshots.exists():
        datas_chart = []
        valores_chart = []
    else:
        # Pega todas as datas únicas
        datas_distintas = sorted(list(set(s.data for s in todos_snapshots)))
        ids_estruturas = list(estruturas.values_list('id', flat=True))
        
        # Mapeia snapshots por data e estrutura
        mapa_snapshots = defaultdict(dict)
        for s in todos_snapshots:
            mapa_snapshots[s.data][s.estrutura_id] = float(s.valor_total)
            
        datas_chart = []
        valores_chart = []
        
        # Mantém o último valor conhecido de cada estrutura
        ultimos_valores = {eid: 0.0 for eid in ids_estruturas}
        
        for d in datas_distintas:
            total_dia = 0.0
            for eid in ids_estruturas:
                if eid in mapa_snapshots[d]:
                    ultimos_valores[eid] = mapa_snapshots[d][eid]
                total_dia += ultimos_valores[eid]
            
            datas_chart.append(d.strftime('%d/%m/%Y'))
            valores_chart.append(total_dia)

        # Adiciona o ponto de "hoje" se for maior que a última data do snapshot
        hoje = timezone.now().date()
        if not datas_chart or datas_distintas[-1] < hoje:
            datas_chart.append(hoje.strftime('%d/%m/%Y'))
            valores_chart.append(float(valor_total_carteira))
    
    context = {
        'estruturas_ativas': estruturas_ativas,
        'estruturas_fechadas': estruturas_fechadas,
        'total_pl_realizado': total_pl_realizado,
        'total_pl_aberto': total_pl_aberto,
        'valor_total_carteira': valor_total_carteira,
        'total_exposicao': total_exposicao,
        'datas_chart': json.dumps(datas_chart),
        'valores_chart': json.dumps(valores_chart),
    }
    
    return render(request, 'trading/dashboard_estruturas.html', context)

@login_required
def detalhe_estrutura(request, slug):
    """
    Exibe os detalhes de uma estrutura específica (Tabela de Posições, Tabela de Ordens).
    """
    estrutura = get_object_or_404(Estrutura, usuario=request.user, slug=slug)
    posicoes_all = estrutura.posicoes.select_related('ativo').all()
    ordens_all = estrutura.ordens.select_related('ativo').all()
    
    from core.models import HistoricoPreco
    for pos in posicoes_all:
        if pos.quantidade_atual != 0:
            # Busca o preço mais recente que não seja zero
            hist = HistoricoPreco.objects.filter(
                ativo=pos.ativo, 
                fechamento__gt=0
            ).order_by('-data_pregao').first()
            
            if hist:
                pos.ultimo_preco = hist.fechamento
                pos.data_ultimo_preco = hist.data_pregao
            else:
                # Fallback para o preço médio se não houver cotação
                pos.ultimo_preco = pos.preco_medio
                pos.data_ultimo_preco = None
                
            if pos.quantidade_atual > 0:
                pos.pl_aberto_calc = (pos.ultimo_preco - pos.preco_medio) * pos.quantidade_atual
            else:
                pos.pl_aberto_calc = (pos.preco_medio - pos.ultimo_preco) * abs(pos.quantidade_atual)
        else:
            pos.ultimo_preco = 0
            pos.data_ultimo_preco = None
            pos.pl_aberto_calc = 0
            
        pos.pl_total = pos.pl_realizado_acumulado + pos.pl_aberto_calc
        
    for o in ordens_all:
        o.total_valor = abs(o.quantidade) * o.preco
        
    posicoes_abertas = [p for p in posicoes_all if p.quantidade_atual != 0]
    posicoes_fechadas = [p for p in posicoes_all if p.quantidade_atual == 0]
    
    # Calcula datas para posições fechadas
    for pos in posicoes_fechadas:
        ordens_pos = Ordem.objects.filter(estrutura=estrutura, ativo=pos.ativo).order_by('data')
        if ordens_pos.exists():
            pos.data_inicial = ordens_pos.first().data
            pos.data_final = ordens_pos.last().data
            pos.dias = (pos.data_final - pos.data_inicial).days
        else:
            pos.data_inicial = pos.data_final = None
            pos.dias = 0

    from django.core.paginator import Paginator
    paginator = Paginator(ordens_all, 20) # 20 ordens por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    snapshots = estrutura.historico_snapshots.order_by('data')
    datas_chart = [obj.data.strftime('%d/%m/%Y') for obj in snapshots]
    valores_chart = [float(obj.valor_total) for obj in snapshots]
    exposicao_chart = [float(obj.exposicao_diaria) for obj in snapshots]
    
    context = {
        'estrutura': estrutura,
        'posicoes_abertas': posicoes_abertas,
        'posicoes_fechadas': posicoes_fechadas,
        'page_obj': page_obj,
        'snapshots': snapshots,
        'datas_chart': json.dumps(datas_chart),
        'valores_chart': json.dumps(valores_chart),
        'exposicao_chart': json.dumps(exposicao_chart),
        'has_open_positions': len(posicoes_abertas) > 0,
    }
    return render(request, 'trading/detalhe_estrutura.html', context)

@login_required
def alternar_status_estrutura(request, slug):
    """Alterna entre ABERTA e FECHADA."""
    estrutura = get_object_or_404(Estrutura, usuario=request.user, slug=slug)
    
    if estrutura.status == 'ABERTA':
        # Verifica se há posições abertas
        if estrutura.posicoes.exclude(quantidade_atual=0).exists():
            messages.error(request, "Não é possível fechar uma estrutura com posições abertas.")
        else:
            estrutura.status = 'FECHADA'
            estrutura.save()
            messages.success(request, f"Estrutura '{estrutura.nome}' fechada com sucesso.")
    else:
        estrutura.status = 'ABERTA'
        estrutura.save()
        messages.success(request, f"Estrutura '{estrutura.nome}' reaberta.")
        
    # Recalcula a estrutura para ajustar o gráfico e as estatísticas
    from .services import recalcular_estrutura
    recalcular_estrutura(estrutura)
        
    return redirect('trading:detalhe_estrutura', slug=estrutura.slug)

from .services import processar_upload_csv

@login_required
def upload_ordens(request):
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        source = request.POST.get('source_type')

        if not csv_file:
            messages.error(request, "Nenhum arquivo enviado.")
            return redirect('trading:upload_ordens')

        if source == 'PROFIT':
            from .services import importar_ordens_profit
            total, erros = importar_ordens_profit(request.user, csv_file)
        else:
            from .services import processar_upload_csv
            total, erros = processar_upload_csv(csv_file, request.user)

        if total > 0:
            messages.success(request, f"Sucesso! {total} ordens importadas.")
        
        if erros:
            for erro in erros[:10]:
                messages.error(request, erro)
            if len(erros) > 10:
                messages.warning(request, f"Há mais {len(erros) - 10} mensagens de erro ocultas.")

        return redirect('trading:dashboard_estruturas')

    return render(request, 'trading/upload_ordens.html')

@login_required
def alocar_ordens_orfas(request):
    """
    Interface para mover ordens da estrutura 'Sem Estrutura' para outras estruturas.
    Suporta alocação em lote.
    """
    estrutura_padrao = get_object_or_404(Estrutura, usuario=request.user, slug='sem-estrutura')
    
    if request.method == 'POST':
        ordem_ids = request.POST.getlist('ordem_ids')
        nova_estrutura_id = request.POST.get('estrutura_id')
        
        if ordem_ids and nova_estrutura_id:
            nova_est = get_object_or_404(Estrutura, id=nova_estrutura_id, usuario=request.user)
            
            # Filtra as ordens que realmente pertencem à estrutura padrão e ao usuário
            ordens = Ordem.objects.filter(id__in=ordem_ids, estrutura=estrutura_padrao)
            
            # Identifica ativos afetados para recalcular posições consolidadas
            ativos_ids = list(ordens.values_list('ativo_id', flat=True).distinct())
            count = ordens.count()
            
            if count > 0:
                # Atualiza todas as ordens de uma vez
                ordens.update(estrutura=nova_est)
                
                # Recalcula ambas as estruturas e suas posições envolvidas
                from .services import recalcular_estrutura, recalcular_posicao
                from core.models import AtivoB3
                
                ativos = AtivoB3.objects.filter(codigo_isin__in=ativos_ids)
                
                for ativo in ativos:
                    recalcular_posicao(estrutura_padrao, ativo)
                    recalcular_posicao(nova_est, ativo)
                
                recalcular_estrutura(estrutura_padrao)
                recalcular_estrutura(nova_est)
                
                messages.success(request, f"{count} ordens movidas para {nova_est.nome} com sucesso.")
            else:
                messages.warning(request, "Nenhuma ordem válida selecionada.")
                
            return redirect('trading:alocar_orfas')
    
    ordens_orfas = estrutura_padrao.ordens.all()
    estruturas_ativas = Estrutura.objects.filter(usuario=request.user, status='ABERTA').exclude(slug='sem-estrutura')
    
    context = {
        'ordens_orfas': ordens_orfas,
        'estruturas_ativas': estruturas_ativas,
    }
    return render(request, 'trading/alocar_ordens_orfas.html', context)

@login_required
def excluir_ordem(request, ordem_id):
    """
    Exclui uma ordem e recarrega a página de detalhes.
    Como usamos signals, o recálculo da posição é automático.
    """
    if request.method == 'POST':
        ordem = get_object_or_404(Ordem, id=ordem_id, estrutura__usuario=request.user)
        estrutura_slug = ordem.estrutura.slug
        ordem.delete()
        messages.success(request, "Ordem excluída com sucesso!")
        return redirect('trading:detalhe_estrutura', slug=estrutura_slug)
    
    return redirect('trading:dashboard_estruturas')

import io
import csv
import logging
from decimal import Decimal
from datetime import datetime
from django.db import transaction
from django.utils.timezone import make_aware
from core.models import AtivoB3
from trading.models import Ordem, Estrutura

logger = logging.getLogger(__name__)

@login_required
def relatorio_performance(request):
    """
    View para relatórios detalhados de performance utilizando services.
    """
    import json
    from .services import get_performance_report
    report = get_performance_report(request.user)
    
    if not report:
        return render(request, 'trading/relatorios.html', {'empty': True})
        
    context = {
        'equity_datas': json.dumps(report['equity_curve']['datas']),
        'equity_valores': json.dumps(report['equity_curve']['valores']),
        'equity_exposicao': json.dumps(report['equity_curve']['exposicao']),
        'monthly_labels': json.dumps(report['monthly']['labels']),
        'monthly_values': json.dumps(report['monthly']['values']),
        'weekly_labels': json.dumps(report['weekly']['labels']),
        'weekly_values': json.dumps(report['weekly']['values']),
        'total_atual': report['total_atual'],
        'exposicao_atual': report['exposicao_atual'],
    }
    return render(request, 'trading/relatorios.html', context)


@login_required
def lista_rolagens(request):
    """Exibe a lista de rolagens ativas e arquivadas do usuário."""
    rolagens_ativas = Rolagem.objects.filter(usuario=request.user, status='ATIVA')
    rolagens_arquivadas = Rolagem.objects.filter(usuario=request.user, status='ARQUIVADA')
    return render(request, 'trading/rolagem_lista.html', {
        'rolagens_ativas': rolagens_ativas,
        'rolagens_arquivadas': rolagens_arquivadas,
    })

@login_required
def criar_rolagem(request):
    """Cria uma nova simulação de rolagem."""
    if request.method == 'POST':
        form = RolagemForm(request.POST)
        formset = RolagemLegFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            rolagem = form.save(commit=False)
            rolagem.usuario = request.user
            rolagem.save()
            
            for f in formset.forms:
                if f.cleaned_data and not f.cleaned_data.get('DELETE'):
                    leg = f.save(commit=False)
                    leg.rolagem = rolagem
                    leg.ativo = f.cleaned_data.get('ticker')
                    leg.save()
            
            recalcular_rolagem(rolagem)
            messages.success(request, f"Rolagem '{rolagem.nome}' criada com sucesso!")
            return redirect('trading:lista_rolagens')
    else:
        form = RolagemForm()
        formset = RolagemLegFormSet()
    
    return render(request, 'trading/rolagem_form.html', {
        'form': form, 
        'formset': formset, 
        'titulo': 'Nova Rolagem'
    })

@login_required
def detalhe_rolagem(request, slug):
    """Exibe os detalhes e o histórico de uma rolagem."""
    rolagem = get_object_or_404(Rolagem, usuario=request.user, slug=slug)
    snapshots = rolagem.snapshots.all().order_by('data')
    
    # Filtramos apenas os dias com spread válido para o gráfico
    valid_snapshots = [s for s in snapshots if s.spread_total is not None]
    datas_chart = [s.data.strftime('%d/%m/%Y') for s in valid_snapshots]
    valores_chart = [float(s.spread_total) for s in valid_snapshots]
    valores_chart_fechamento = [float(s.spread_fechamento) if s.spread_fechamento is not None else None for s in valid_snapshots]
    
    # Legs para a tabela de detalhes
    legs = rolagem.legs.select_related('ativo').all()
    
    return render(request, 'trading/rolagem_detalhe.html', {
        'rolagem': rolagem,
        'snapshots': snapshots.order_by('-data'), # Tabela em ordem decrescente
        'legs': legs,
        'datas_chart': json.dumps(datas_chart),
        'valores_chart': json.dumps(valores_chart),
        'valores_chart_fechamento': json.dumps(valores_chart_fechamento),
    })

@login_required
def editar_rolagem(request, slug):
    """Edita uma rolagem existente e dispara o recálculo."""
    rolagem = get_object_or_404(Rolagem, usuario=request.user, slug=slug)
    if request.method == 'POST':
        form = RolagemForm(request.POST, instance=rolagem)
        formset = RolagemLegFormSet(request.POST, instance=rolagem)
        if form.is_valid() and formset.is_valid():
            form.save()
            
            # Remove legs deletadas e atualiza/cria as outras
            formset.save(commit=False)
            for obj in formset.deleted_objects:
                obj.delete()
            
            for f in formset.forms:
                if f.cleaned_data and not f.cleaned_data.get('DELETE'):
                    leg = f.save(commit=False)
                    leg.rolagem = rolagem
                    leg.ativo = f.cleaned_data.get('ticker')
                    leg.save()
            
            recalcular_rolagem(rolagem)
            messages.success(request, "Rolagem atualizada e histórico recalculado.")
            return redirect('trading:detalhe_rolagem', slug=rolagem.slug)
    else:
        form = RolagemForm(instance=rolagem)
        formset = RolagemLegFormSet(instance=rolagem)
        # Pre-fill ticker
        for i, leg in enumerate(rolagem.legs.all()):
             if i < len(formset.forms):
                 formset.forms[i].fields['ticker'].initial = leg.ativo.ticker

    return render(request, 'trading/rolagem_form.html', {
        'form': form, 
        'formset': formset, 
        'titulo': 'Editar Rolagem'
    })

@login_required
def arquivar_rolagem(request, slug):
    rolagem = get_object_or_404(Rolagem, usuario=request.user, slug=slug)
    rolagem.status = 'ARQUIVADA' if rolagem.status == 'ATIVA' else 'ATIVA'
    rolagem.save()
    status_str = "arquivada" if rolagem.status == 'ARQUIVADA' else "reativada"
    messages.success(request, f"Rolagem {status_str} com sucesso.")
    return redirect('trading:lista_rolagens')

@login_required
def excluir_rolagem(request, slug):
    rolagem = get_object_or_404(Rolagem, usuario=request.user, slug=slug)
    rolagem.delete()
    messages.success(request, "Rolagem excluída permanentemente.")
    return redirect('trading:lista_rolagens')

@login_required
def recalcular_todas_rolagens_view(request):
    """Trigger manual de recálculo de todas as rolagens do usuário."""
    count = recalcular_todas_rolagens()
    messages.success(request, f"{count} rolagens recalculadas com sucesso.")
    return redirect('trading:lista_rolagens')
