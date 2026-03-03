from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from .models import Estrutura, Ordem, PosicaoConsolidada, DailySnapshot
from .forms import EstruturaForm
import json
from .services import importar_ordens_profit


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
    posicoes = estrutura.posicoes.select_related('ativo').all()
    ordens = estrutura.ordens.select_related('ativo').all()
    
    from core.models import HistoricoPreco
    for pos in posicoes:
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
        
    for o in ordens:
        o.total_valor = abs(o.quantidade) * o.preco
        
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
    if request.method == 'POST':
        print("\n=== POST RECEBIDO NA VIEW ===")
        csv_file = request.FILES.get('csv_file')
        source = request.POST.get('source_type')
        
        print(f"Arquivo recebido: {csv_file}")
        print(f"Origem selecionada: {source}")

        if not csv_file:
            messages.error(request, "Nenhum arquivo enviado.")
            return redirect('trading:upload_ordens')

        # Chamada da nossa função de serviço com os prints
        from .services import importar_ordens_profit
        
        total, erros = importar_ordens_profit(request.user, csv_file)

        if total > 0:
            messages.success(request, f"Sucesso! {total} ordens importadas.")
        
        if erros:
            for erro in erros[:10]:  # Mostra apenas os 10 primeiros na tela
                messages.error(request, erro)
            if len(erros) > 10:
                messages.warning(request, f"Há mais {len(erros) - 10} mensagens de erro ocultas.")

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
import io
import csv
from decimal import Decimal
from datetime import datetime
from django.db import transaction
from django.utils.timezone import make_aware

@login_required
def importar_ordens_profit(user, csv_file):
    print("\n--- INICIANDO IMPORTAÇÃO ---")
    raw_data = csv_file.read()
    
    try:
        content = raw_data.decode('utf-8')
        print("Codificação detectada: UTF-8")
    except UnicodeDecodeError:
        content = raw_data.decode('iso-8859-1')
        print("Codificação detectada: ISO-8859-1 (Latin-1)")

    lines = content.splitlines()
    print(f"Total de linhas lidas no arquivo: {len(lines)}")

    # 1. Debug do cabeçalho
    header_index = -1
    for i, line in enumerate(lines):
        if 'Ativo;' in line and 'Status;' in line:
            header_index = i
            print(f"Cabeçalho encontrado na linha {i+1}: {line[:50]}...")
            break
    
    if header_index == -1:
        print("ERRO: Cabeçalho não encontrado! Verifique o delimitador ou nomes das colunas.")
        return 0, ["Cabeçalho do Profit não encontrado."]

    # 2. Lendo os dados
    f = io.StringIO('\n'.join(lines[header_index:]))
    reader = csv.DictReader(f, delimiter=';')
    
    ordens_para_criar = []
    erros = []
    
    from trading.models import Estrutura, Ordem, AtivoB3
    estrutura_placeholder, _ = Estrutura.objects.get_or_create(
        usuario=user, nome="Sem Estrutura", defaults={'slug': 'sem-estrutura'}
    )

    print("Iniciando processamento das linhas...")
    with transaction.atomic():
        for row_num, row in enumerate(reader, start=header_index + 2):
            # Print de cada linha para ver o que o DictReader capturou
            status = row.get('Status', '').strip()
            ativo_nome = row.get('Ativo', '').strip()
            
            print(f"Linha {row_num}: Ativo={ativo_nome} | Status={status}")

            if status != 'Executada':
                print(f"   -> Ignorada: Status '{status}' não é 'Executada'")
                continue

            try:
                # Busca Ativo
                try:
                    ativo = AtivoB3.objects.get(ticker=ativo_nome)
                except AtivoB3.DoesNotExist:
                    msg = f"Ativo '{ativo_nome}' não existe no banco de dados."
                    print(f"   -> ERRO: {msg}")
                    erros.append(f"Linha {row_num}: {msg}")
                    continue

                # Parse de valores
                def parse_decimal(text):
                    if not text or text == '-': return Decimal('0.00')
                    return Decimal(text.replace('.', '').replace(',', '.'))

                preco = parse_decimal(row['Preço'])
                qtd_raw = row['Qtd'].replace('.', '')
                qtd_total = int(qtd_raw)
                
                lado = row['Lado'].strip().upper()
                quantidade = -abs(qtd_total) if lado == 'V' else abs(qtd_total)

                dt_str = row['Criação'].strip()
                dt_obj = datetime.strptime(dt_str, '%d/%m/%Y %H:%M:%S')
                dt_aware = make_aware(dt_obj)

                ordem = Ordem(
                    estrutura=estrutura_placeholder,
                    ativo=ativo,
                    quantidade=quantidade,
                    preco=preco,
                    data=dt_aware.date(),
                    criado_em=dt_aware,
                    is_opening=True
                )
                ordens_para_criar.append(ordem)
                print(f"   -> OK: Ordem preparada ({lado} {abs(quantidade)} de {ativo_nome})")

            except Exception as e:
                print(f"   -> ERRO CRÍTICO na linha {row_num}: {str(e)}")
                erros.append(f"Linha {row_num}: {str(e)}")

        if ordens_para_criar:
            print(f"Salvando {len(ordens_para_criar)} ordens no banco...")
            Ordem.objects.bulk_create(ordens_para_criar)
            
            from .services import recalcular_estrutura
            recalcular_estrutura(estrutura_placeholder)
            print("Importação concluída com sucesso.")
        else:
            print("Nenhuma ordem válida foi encontrada para importação.")

    return len(ordens_para_criar), erros