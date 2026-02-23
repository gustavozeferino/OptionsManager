from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from .models import Estrutura, Ordem, PosicaoConsolidada, DailySnapshot
from .forms import EstruturaForm
import json

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
    
    resultados = [{'id': ativo.codigo_isin, 'text': f"{ativo.ticker} - {ativo.ativo_objeto}"} for ativo in ativos]
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
    estruturas = Estrutura.objects.filter(usuario=request.user)
    
    total_pl_realizado = estruturas.aggregate(Sum('pl_realizado'))['pl_realizado__sum'] or 0
    total_pl_aberto = estruturas.aggregate(Sum('pl_aberto'))['pl_aberto__sum'] or 0
    valor_total_carteira = estruturas.aggregate(Sum('valor_total'))['valor_total__sum'] or 0
    
    # Prepara dados para o gráfico ECharts (evolução do patrimônio)
    snapshots = DailySnapshot.objects.filter(estrutura__usuario=request.user) \
                                     .values('data') \
                                     .annotate(total_diario=Sum('valor_total')) \
                                     .order_by('data')
    datas_chart = [obj['data'].strftime('%d/%m/%Y') for obj in snapshots]
    valores_chart = [float(obj['total_diario']) for obj in snapshots]
    
    context = {
        'estruturas': estruturas,
        'total_pl_realizado': total_pl_realizado,
        'total_pl_aberto': total_pl_aberto,
        'valor_total_carteira': valor_total_carteira,
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
    posicoes = estrutura.posicoes.all()
    ordens = estrutura.ordens.all()
    
    snapshots = estrutura.historico_snapshots.order_by('data')
    datas_chart = [obj.data.strftime('%d/%m/%Y') for obj in snapshots]
    valores_chart = [float(obj.valor_total) for obj in snapshots]
    
    context = {
        'estrutura': estrutura,
        'posicoes': posicoes,
        'ordens': ordens,
        'snapshots': snapshots,
        'datas_chart': json.dumps(datas_chart),
        'valores_chart': json.dumps(valores_chart),
    }
    return render(request, 'trading/detalhe_estrutura.html', context)

from .services import processar_upload_csv

@login_required
def upload_ordens(request):
    """
    Recebe CSV com histórico de ordens (Clear/B3) e aloca na 'Sem Estrutura'.
    """
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        
        if not csv_file.name.endswith('.csv'):
            messages.error(request, 'Este não é um arquivo CSV válido.')
            return redirect('trading:upload_ordens')
            
        sucesso, erros = processar_upload_csv(csv_file, request.user)
        
        if sucesso > 0:
            messages.success(request, f"{sucesso} ordens foram importadas e adicionadas à 'Sem Estrutura'.")
        
        if erros:
            for erro in erros[:5]: # Mostra no máximo 5 erros para não poluir
                messages.warning(request, erro)
            if len(erros) > 5:
                messages.warning(request, f"... e mais {len(erros) - 5} erros ignorados.")
                
        return redirect('trading:dashboard_estruturas')
        
    return render(request, 'trading/upload_ordens.html')

@login_required
def alocar_ordens_orfas(request):
    """
    Interface para mover ordens da estrutura 'Sem Estrutura' para outras estruturas.
    """
    estrutura_padrao = get_object_or_404(Estrutura, usuario=request.user, slug='sem-estrutura')
    
    if request.method == 'POST':
        ordem_id = request.POST.get('ordem_id')
        nova_estrutura_id = request.POST.get('estrutura_id')
        
        if ordem_id and nova_estrutura_id:
            ordem = get_object_or_404(Ordem, id=ordem_id, estrutura=estrutura_padrao)
            nova_est = get_object_or_404(Estrutura, id=nova_estrutura_id, usuario=request.user)
            
            ordem.estrutura = nova_est
            ordem.save()
            messages.success(request, f"Ordem movida para {nova_est.nome} com sucesso.")
            return redirect('trading:alocar_orfas')
    
    ordens_orfas = estrutura_padrao.ordens.all()
    estruturas_ativas = Estrutura.objects.filter(usuario=request.user).exclude(slug='sem-estrutura')
    
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
