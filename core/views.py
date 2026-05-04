import io
import pandas as pd
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.contrib import messages
from .models import AtivoB3, HistoricoImportacao, AtivoMonitorado, AcessoLog, HistoricoPreco
from django.contrib.auth.decorators import login_required, user_passes_test
import datetime
import time
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
import json
import unicodedata
from django.shortcuts import get_object_or_404
from django.db.models import Count, Max
from trading.models import Estrutura
from trading.services import recalcular_estrutura
from collections import defaultdict
from django.db.models import Sum, Avg, Q

def apenas_admin(user):
    return user.is_superuser

@login_required
def home(request):
    if not request.user.is_staff and not request.user.is_superuser:
        return redirect('trading:dashboard_estruturas')
    
    hoje = timezone.now().date()
    
    # Total de opções que ainda não venceram
    ativos_vivos = AtivoB3.objects.filter(data_expiracao__gte=hoje).count()
    
    # Última data de pregão registrada
    ultima_data = HistoricoPreco.objects.aggregate(Max('data_pregao'))['data_pregao__max']

    # Ativos com volume > 0 na última data
    ativos_negociados = 0
    if ultima_data:
        ativos_negociados = HistoricoPreco.objects.filter(
            data_pregao=ultima_data,
            volume_financeiro__gt=0
        ).count()

    # Buscamos os últimos logs do SEU modelo AcessoLog
    ultimos_logs = AcessoLog.objects.all().order_by('-data_acesso')[:5]
    
    context = {
        'ativos_vivos': ativos_vivos,
        'ultima_data': ultima_data,
        'ativos_negociados': ativos_negociados,
        'total_geral': AtivoB3.objects.count(),
        'ultimos_logs': ultimos_logs,
    }
    return render(request, 'core/home.html', context)

@user_passes_test(apenas_admin)
def lista_logs(request):
    logs_list = AcessoLog.objects.all().order_by('-data_acesso')
    paginator = Paginator(logs_list, 50)
    page_number = request.GET.get('page')
    logs = paginator.get_page(page_number)
    
    return render(request, 'core/lista_logs.html', {'logs': logs})



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

def clean_int(value):
    """Trata inteiros, removendo pontos de milhar (formato BR)."""
    if pd.isna(value) or str(value).strip() in ['', '-']:
        return 0
    # Remove pontos de milhar (ex: 5.284 -> 5284)
    s = str(value).replace('.', '').strip()
    # Se houver vírgula, pegamos apenas a parte inteira (ex: 5284,00 -> 5284)
    if ',' in s:
        s = s.split(',')[0]
    try:
        return int(s)
    except ValueError:
        return 0

def clean_date(value):
    """Trata datas, ignorando hífens ou valores inválidos."""
    if pd.isna(value) or str(value).strip() in ['', '-']:
        return None
    try:
        # O dayfirst=True é vital para o formato brasileiro DD/MM/YYYY
        return pd.to_datetime(value, dayfirst=True).date()
    except:
        return None

@user_passes_test(apenas_admin)
def upload_csv(request):
    if request.method == 'POST' and request.FILES.get('arquivo'):
        file = request.FILES['arquivo']
        
        # 1. Carregar a lista de ativos permitidos do banco (em cache de memória para este request)
        # Pegamos apenas os tickers que estão ativos
        ativos_permitidos = list(AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True))

        if not ativos_permitidos:
            messages.warning(request, "Nenhum Ativo Monitorado cadastrado. A importação não processará dados.")
            return redirect('core:upload_csv')

        try:
            # (Mantemos a mesma lógica de leitura de arquivos anterior...)
            content = file.read()
            decoded_content = content.decode('utf-8-sig') if b'\xef\xbb\xbf' in content else content.decode('latin1')
            
            linhas = decoded_content.splitlines()
            pular = 0
            for i, linha in enumerate(linhas[:15]):
                if 'ISIN' in linha: pular = i; break
            
            io_string = io.StringIO(decoded_content)
            df = pd.read_csv(io_string, sep=';', skiprows=pular, engine='python')
            df.columns = [str(c).strip() for c in df.columns]
        except Exception as e:
            messages.error(request, f"Erro na estrutura: {e}")
            return redirect('core:upload_csv')

        relatorio = {'novos': 0, 'atualizados': 0, 'sem_alteracao': 0, 'logs': []}
        
        for index, row in df.iterrows():
            # CAPTURA O ATIVO OBJETO DO CSV
            ativo_obj_csv = str(row.get('Ativo', '')).strip().upper()

            # FILTRO DINÂMICO
            if ativo_obj_csv not in ativos_permitidos:
                continue # Ignora silenciosamente se não estiver na lista

            # ... Resto da lógica de ISIN, clean_numeric e update/create ...
            isin = str(row.get('Código ISIN', '')).strip()
            if isin in ['', 'nan', '-']:
                continue

            # Mapeamento com limpeza
            dados_csv = {
                'ticker': str(row.get('Instrumento financeiro', 'S/N')).strip(),
                'ativo_objeto': str(row.get('Ativo', '')).strip(),
                'tipo_opcao': str(row.get('Tipo de opção', '')).strip(),
                'preco_exercicio': clean_numeric(row.get('Preço de exercício', 0)),
                'data_expiracao': clean_date(row.get('Data de expiração')),
                'segmento': str(row.get('Segmento', '')).strip(),
            }

            # Lógica de Banco de Dados
            ativo_queryset = AtivoB3.objects.filter(codigo_isin__iexact=isin)

            if not ativo_queryset.exists():
                AtivoB3.objects.create(codigo_isin=isin, **dados_csv)
                if isinstance(relatorio['novos'], int):
                    relatorio['novos'] += 1
                relatorio['logs'].append(f"NOVO: {dados_csv['ticker']} ({isin})")
            else:
                ativo = ativo_queryset.first()
                mudancas = []
                
                # verifica se houve alterações nos campos
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

        # Salva histórico final
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

# Mantenha sua função de dashboard abaixo...

@user_passes_test(apenas_admin)
def lista_ativos(request):
    """Exibe a lista de ativos com filtros, formatação de meses/semanas e Option Chain."""
    search_query = request.GET.get('search', '')
    ativo_filtro = request.GET.get('ativo_objeto', '')
    mes_filtro = request.GET.get('mes', '')
    vencimento_filtro = request.GET.get('vencimento', '')

    permitidos = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True).order_by('ticker')
    lista_ativos_objeto = list(permitidos)
    
    # Se não houver ativos ativos no painel
    if not lista_ativos_objeto:
        return render(request, 'core/lista_ativos.html', {'lista_ativos_objeto': []})

    # Default para o primeiro ativo se não especificado
    if not ativo_filtro or ativo_filtro not in lista_ativos_objeto:
        ativo_filtro = lista_ativos_objeto[0]

    # Busca todas as opções do ativo selecionado
    ativos_base = AtivoB3.objects.filter(ativo_objeto=ativo_filtro).exclude(data_expiracao__isnull=True)
    
    # Busca global (sobrescreve o option chain)
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

    # Agrupar datas por ano e mês para a navegação (grade de 12 meses por ano)
    datas_distintas = ativos_base.values_list('data_expiracao', flat=True).order_by('data_expiracao').distinct()
    
    meses_labels = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    anos_dict = {}
    
    for d in datas_distintas:
        y = d.year
        m = d.month
        
        if y not in anos_dict:
            # Inicializa o ano com 12 slots para os meses
            anos_dict[y] = [
                {'mes_num': i, 'codigo': f"{y}-{i:02d}", 'label': meses_labels[i-1], 'datas': [], 'valido': False}
                for i in range(1, 13)
            ]
            
        slot = anos_dict[y][m-1]
        slot['datas'].append(d)
        slot['valido'] = True
        
    # Extrair apenas os meses válidos para a lógica de "mês ativo corrente"
    lista_meses_validos = []
    for slots in anos_dict.values():
        for slot in slots:
            if slot['valido']:
                lista_meses_validos.append(slot)
    
    if not lista_meses_validos:
        # Nenhum vencimento encontrado para o ativo
        return render(request, 'core/lista_ativos.html', {
            'ativo_filtro': ativo_filtro,
            'lista_ativos_objeto': lista_ativos_objeto,
        })

    # Decidir o mês ativo
    if not mes_filtro or not any(m['codigo'] == mes_filtro for m in lista_meses_validos):
        # Acha o mês mais próximo de expirar que ainda não expirou (ou o primeiro do dict)
        hoje = timezone.now().date()
        meses_futuros = [m for m in lista_meses_validos if any(d >= hoje for d in m['datas'])]
        if meses_futuros:
            mes_ativo_dict = meses_futuros[0]
        else:
            mes_ativo_dict = lista_meses_validos[-1] # Pega o último se todos já passaram
        mes_filtro = mes_ativo_dict['codigo']
    else:
        mes_ativo_dict = next(m for m in lista_meses_validos if m['codigo'] == mes_filtro)
        
    datas_do_mes = mes_ativo_dict['datas']

    # Decidir a semana (vencimento específico)
    if not vencimento_filtro:
        # Tenta achar o Mensal dentro do mês selecionado
        vencimento_mensal = ativos_base.filter(data_expiracao__in=datas_do_mes, classificacao_vencimento='Mensal').values_list('data_expiracao', flat=True).first()
        if vencimento_mensal:
            vencimento_filtro = vencimento_mensal.strftime('%Y-%m-%d')
        else:
            vencimento_filtro = datas_do_mes[0].strftime('%Y-%m-%d')
    else:
        # Validação básica pra não travar se passar lixo na URL
        try:
            datetime.datetime.strptime(vencimento_filtro, '%Y-%m-%d')
        except ValueError:
             vencimento_filtro = datas_do_mes[0].strftime('%Y-%m-%d')

    # Filtrar opções pelas datas
    opcoes = ativos_base.filter(data_expiracao=vencimento_filtro).order_by('preco_exercicio')

    # Obter histórico de preços mais recente para alimentar a grade
    from core.models import HistoricoPreco
    historicos = HistoricoPreco.objects.filter(ativo__in=opcoes).order_by('-data_pregao')
    precos_recentes = {}
    for h in historicos:
        if h.ativo_id not in precos_recentes:
            # Calcular VWAP
            if h.quantidade_contratos and h.quantidade_contratos > 0:
                h.vwap_calculado = float(h.volume_financeiro) / float(h.quantidade_contratos)
            else:
                h.vwap_calculado = 0.0
            precos_recentes[h.ativo_id] = h

    # Option Chain Builder
    option_chain_dict = {}
    for op in opcoes:
        strike = op.preco_exercicio
        if strike not in option_chain_dict:
            option_chain_dict[strike] = {'strike': strike, 'call': None, 'put': None, 'call_hist': None, 'put_hist': None}
            
        hist = precos_recentes.get(op.codigo_isin)
        
        if op.tipo_opcao.strip().upper() == 'CALL':
            option_chain_dict[strike]['call'] = op
            option_chain_dict[strike]['call_hist'] = hist
        else:
            option_chain_dict[strike]['put'] = op
            option_chain_dict[strike]['put_hist'] = hist
            
    chain_list = list(option_chain_dict.values())
    chain_list.sort(key=lambda x: x['strike'] if x['strike'] else 0)

    # Estatísticas do Ativo Objeto
    ativo_obj_b3 = AtivoB3.objects.filter(ticker=ativo_filtro).first()
    stats_ativo = None
    if ativo_obj_b3:
        hist_ativo = HistoricoPreco.objects.filter(ativo=ativo_obj_b3, fechamento__gt=0).order_by('-data_pregao')
        if hist_ativo.exists():
            stats_ativo = {}
            h_atual = hist_ativo.first()
            stats_ativo['preco_atual'] = float(h_atual.fechamento)
            
            # Variação Diária (comparado ao dia anterior)
            if hist_ativo.count() > 1:
                h_ontem = hist_ativo[1]
                stats_ativo['var_diaria'] = ((float(h_atual.fechamento) / float(h_ontem.fechamento)) - 1) * 100 if float(h_ontem.fechamento) else 0
            else:
                stats_ativo['var_diaria'] = 0
                
            # Variação 5 dias
            if hist_ativo.count() > 5:
                h_5d = hist_ativo[5]
                stats_ativo['var_5d'] = ((float(h_atual.fechamento) / float(h_5d.fechamento)) - 1) * 100 if float(h_5d.fechamento) else 0
            elif hist_ativo.count() > 1:
                h_5d = hist_ativo.last()
                stats_ativo['var_5d'] = ((float(h_atual.fechamento) / float(h_5d.fechamento)) - 1) * 100 if float(h_5d.fechamento) else 0
            else:
                stats_ativo['var_5d'] = 0
                
            # Variação 30 dias
            if hist_ativo.count() > 30:
                h_30d = hist_ativo[30]
                stats_ativo['var_30d'] = ((float(h_atual.fechamento) / float(h_30d.fechamento)) - 1) * 100 if float(h_30d.fechamento) else 0
            elif hist_ativo.count() > 1:
                h_30d = hist_ativo.last()
                stats_ativo['var_30d'] = ((float(h_atual.fechamento) / float(h_30d.fechamento)) - 1) * 100 if float(h_30d.fechamento) else 0
            else:
                stats_ativo['var_30d'] = 0

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

@user_passes_test(apenas_admin)
def limpar_ativos_nao_monitorados(request):
    """Remove do banco AtivoB3 todos os registros que não são Ativos Monitorados."""
    # 1. Busca a lista de tickers que você quer MANTER
    permitidos = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True)
    
    # 2. Filtra no AtivoB3 tudo que NÃO está nessa lista (usando o sinal de til ~ para negar)
    ativos_para_deletar = AtivoB3.objects.exclude(ativo_objeto__in=permitidos)
    
    quantidade = ativos_para_deletar.count()
    
    if quantidade > 0:
        ativos_para_deletar.delete()
        messages.success(request, f"Limpeza concluída! {quantidade} ativos inúteis foram removidos.")
    else:
        messages.info(request, "O banco já está limpo. Nenhum ativo extra encontrado.")
    
    return redirect('core:home')



@user_passes_test(apenas_admin)
def upload_precos(request):
    if request.method == 'POST' and request.FILES.get('arquivo'):
        file = request.FILES['arquivo']
        data_manual_str = request.POST.get('data_manual')
        
        start_time = time.time()
        print("\n" + "="*60)
        print(f"[*] INICIANDO IMPORTAÇÃO: {file.name}")
        print("="*60)

        try:
            # 1. DETECÇÃO DE CABEÇALHO MAIS AGRESSIVA
            print("[1/4] Vasculhando arquivo para localizar cabeçalho...")
            
            # Lê as primeiras 200 linhas sem definir separador (para não dar erro)
            # e converte tudo para uma lista de strings para busca rápida
            preview_raw = file.read(50000).decode('latin1').splitlines() 
            file.seek(0) # Volta o ponteiro para o início após o preview

            linha_cabecalho = None
            for i, texto_linha in enumerate(preview_raw):
                if 'ISIN' in texto_linha.upper():
                    linha_cabecalho = i
                    print(f"--- Palavra 'ISIN' encontrada na linha {i}")
                    break

            if linha_cabecalho is None:
                # Debug: Imprime as primeiras 5 linhas que ele leu para você ver o que tem nelas
                print("[!!!] Conteúdo inicial do arquivo para debug:")
                for l in preview_raw[:5]: print(f"    > {l}")
                
                messages.error(request, "Não foi possível localizar o cabeçalho 'ISIN' no arquivo.")
                return redirect('core:upload_precos')

            # 2. LEITURA COMPLETA
            print(f"[2/4] Carregando Dataframe (skiprows={linha_cabecalho})...")
            
            # Tenta UTF-8-SIG primeiro (para arquivos modernos com BOM)
            try:
                file.seek(0)
                content = file.read().decode('utf-8-sig')
            except UnicodeDecodeError:
                file.seek(0)
                content = file.read().decode('latin1')
                
            io_string = io.StringIO(content)
            
            # Tenta detectar o separador (geralmente ; em CSVs brasileiros de Excel)
            df = pd.read_csv(io_string, sep=None, skiprows=linha_cabecalho, engine='python', on_bad_lines='skip', dtype=str)
            
            print(f"--- Colunas encontradas no arquivo: {list(df.columns)}")

            # Recalibra o nome da coluna ISIN
            coluna_isin = next((c for c in df.columns if 'ISIN' in c.upper()), None)
            print(f"--- Arquivo carregado: {len(df):,} linhas.")
            print(f"--- Coluna identificada: '{coluna_isin}'")

            # Mapeamento robusto de colunas por palavras-chave com normalização de acentos
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
                    # Primeiro tenta match exato na coluna normalizada
                    if norm_k in normalized_cols:
                        return normalized_cols[norm_k]
                    # Depois tenta match parcial
                    for norm_c, original_c in normalized_cols.items():
                        if norm_k in norm_c:
                            return original_c
                return None

            # 3. FILTRAGEM EM MEMÓRIA (O segredo da performance)
            print("[2/4] Filtrando ativos monitorados...")
            # Apenas ativos que estejam relacionados aos Ativos Monitorados ativos
            ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True)
            ativos_no_banco = AtivoB3.objects.filter(ativo_objeto__in=ativos_monitorados).values_list('codigo_isin', flat=True)
            set_isins = set(ativos_no_banco)
            
            # Filtro de Segmento
            col_segmento = find_col(['Segmento', 'Segmento de Mercado', 'SEGMENTO'], df.columns)
            if col_segmento:
                segmentos_permitidos = ['CASH', 'EQUITY CALL', 'EQUITY PUT']
                df[col_segmento] = df[col_segmento].astype(str).str.strip().str.upper()
                df = df[df[col_segmento].isin(segmentos_permitidos)]

            # Garantimos que a coluna ISIN seja string e sem espaços
            df[coluna_isin] = df[coluna_isin].astype(str).str.strip()
            
            df_filtrado = df[df[coluna_isin].isin(set_isins)].copy()
            total_para_gravar = len(df_filtrado)
            
            if total_para_gravar == 0:
                print("[!] AVISO: Nenhum ativo do banco encontrado no arquivo de 1 milhão de linhas.")
                messages.warning(request, "O arquivo foi lido, mas nenhum ISIN coincide com seus ativos cadastrados.")
                return redirect('core:upload_precos')

            # 4. GRAVAÇÃO ATÔMICA
            print(f"[3/4] Gravando {total_para_gravar} registros no banco...")
            relatorio = {'novos': 0, 'atualizados': 0, 'sem_alteracao': 0, 'logs': []}

            col_abertura = find_col(['Preço de abertura', 'Abertura', 'ABR', 'PRECO ABR'], df.columns)
            col_maximo = find_col(['Preço máximo', 'Máximo', 'MAXIMO', 'MAX', 'MAX.'], df.columns)
            col_minimo = find_col(['Preço mínimo', 'Mínimo', 'MINIMO', 'MIN', 'MIN.'], df.columns)
            col_fechamento = find_col(['Preço de fechamento', 'Fechamento', 'FECH', 'FECH.', 'Último', 'ULTIMO', 'ULT.', 'PRECO FECH'], df.columns)
            col_ajuste = find_col(['Ajuste', 'AJUST.'], df.columns)
            col_qtd_neg = find_col(['Quantidade de negócios', 'Negócios', 'NEGOCIOS', 'NEGOC.'], df.columns)
            col_vol_fin = find_col(['Volume financeiro', 'Volume', 'VOL.', 'VOL FIN'], df.columns)
            col_qtd_contratos = find_col(['Quantidade de contratos', 'Contratos', 'QTD. CONTRATOS', 'QTD CONTRATOS'], df.columns)
            col_data_neg = find_col(['Data do negócio', 'Data'], df.columns)

            print(f"--- Mapeamento:")
            print(f"    - Abertura:   {col_abertura} (Exemplos: {df[col_abertura].head(2).tolist() if col_abertura else 'N/A'})")
            print(f"    - Máximo:     {col_maximo} (Exemplos: {df[col_maximo].head(2).tolist() if col_maximo else 'N/A'})")
            print(f"    - Mínimo:     {col_minimo} (Exemplos: {df[col_minimo].head(2).tolist() if col_minimo else 'N/A'})")
            print(f"    - Fechamento: {col_fechamento} (Exemplos: {df[col_fechamento].head(2).tolist() if col_fechamento else 'N/A'})")

            ativos_afetados = set()

            with transaction.atomic():
                # Mapa de objetos para evitar milhares de queries
                # Usamos ativos_monitorados (lista de tickers) que é muito menor que set_isins (lista de todos os ISINs de opções)
                mapa_objetos = {a.codigo_isin: a for a in AtivoB3.objects.filter(ativo_objeto__in=ativos_monitorados)}

                for index, (idx_df, row) in enumerate(df_filtrado.iterrows(), 1):
                    try:
                        isin = row[coluna_isin]
                        ativo_obj = mapa_objetos.get(isin)
                        
                        # Tratamento de Data (Coluna vs Manual)
                        data_linha = row.get(col_data_neg) if col_data_neg else None
                        if pd.notna(data_linha) and str(data_linha).strip() != '-':
                            dt_pregao = pd.to_datetime(data_linha, dayfirst=True).date()
                        else:
                            dt_pregao = datetime.datetime.strptime(data_manual_str, '%Y-%m-%d').date()

                        # Gravação/Atualização
                        obj, created = HistoricoPreco.objects.update_or_create(
                            ativo=ativo_obj,
                            data_pregao=dt_pregao,
                            defaults={
                                'abertura': clean_numeric(row.get(col_abertura)) if col_abertura else 0,
                                'maximo': clean_numeric(row.get(col_maximo)) if col_maximo else 0,
                                'minimo': clean_numeric(row.get(col_minimo)) if col_minimo else 0,
                                'fechamento': clean_numeric(row.get(col_fechamento)) if col_fechamento else 0,
                                'ajuste': clean_numeric(row.get(col_ajuste)) if col_ajuste else 0,
                                'quantidade_negocios': clean_int(row.get(col_qtd_neg)) if col_qtd_neg else 0,
                                'volume_financeiro': clean_numeric(row.get(col_vol_fin)) if col_vol_fin else 0,
                                'quantidade_contratos': clean_int(row.get(col_qtd_contratos)) if col_qtd_contratos else 0,
                            }
                        )
                        
                        if ativo_obj:
                            if created:
                                relatorio['novos'] += 1
                            else:
                                relatorio['atualizados'] += 1
                            
                            ativos_afetados.add(ativo_obj.codigo_isin)
                        else:
                            relatorio['logs'].append(f"Aviso: ISIN {isin} não encontrado no banco.")

                        if index % 100 == 0 or index == total_para_gravar:
                            print(f"    > Processado: {index}/{total_para_gravar} ({ (index/total_para_gravar)*100:.1f}%)")

                    except Exception as e:
                        relatorio['logs'].append(f"Erro na linha {index}: {e}")
                        continue

            # 5. RECALCULAR ESTRUTURAS AFETADAS
            if ativos_afetados:
                print(f"[4/4] Recalculando estruturas afetadas...")
                from trading.models import Estrutura
                from trading.services import recalcular_estrutura
                
                estruturas_afetadas = Estrutura.objects.filter(posicoes__ativo_id__in=ativos_afetados).distinct()
                total_est = estruturas_afetadas.count()
                
                for i, est in enumerate(estruturas_afetadas, 1):
                    recalcular_estrutura(est)
                    if i % 10 == 0 or i == total_est:
                        print(f"    > Estruturas processadas: {i}/{total_est}")

            # Salva histórico final
            historico = HistoricoImportacao.objects.create(
                tipo_importacao='Negócios Consolidados',
                arquivo_nome=file.name,
                novos=relatorio['novos'],
                atualizados=relatorio['atualizados'],
                sem_alteracao=0,
                detalhes=relatorio['logs']
            )

            end_time = time.time()
            print("="*60)
            print(f"[4/4] FINALIZADO EM {end_time - start_time:.2f} SEGUNDOS")
            print(f"[*] Sucesso: {relatorio['novos'] + relatorio['atualizados']} | Erros: {len(relatorio['logs'])}")
            print("="*60 + "\n")

            return render(request, 'core/relatorio_importacao.html', {'relatorio': historico})

        except Exception as e:
            print(f"\n[!!!] ERRO NO PROCESSAMENTO: {e}\n")
            messages.error(request, f"Erro ao processar arquivo: {e}")
            return redirect('core:upload_precos')

    return render(request, 'core/upload_precos.html', {'hoje': datetime.date.today()})


def detalhe_ativo(request, ticker):
    ativo = get_object_or_404(AtivoB3, ticker=ticker)
    historico = HistoricoPreco.objects.filter(ativo=ativo).order_by('-data_pregao')
    
    # Cálculo de dias para o vencimento
    dias_para_vencer = (ativo.data_expiracao - timezone.now().date()).days
    
    # Preparando dados para o gráfico (precisa ser em ordem cronológica)
    historico_qs = HistoricoPreco.objects.filter(
        ativo=ativo, 
        fechamento__gt=0
    ).order_by('data_pregao')
    
    ohlc_data = []
    volume_data = []
    echarts_data =[]
    
    for h in historico_qs:
        # Usamos apenas a string da data como categoria
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
        # Passamos os dados do gráfico como JSON para o JavaScript ler
        'ohlc_json': ohlc_data,
        'echarts_data' : echarts_data,
        'volume_json': json.dumps(volume_data),
    }
    return render(request, 'core/detalhe_ativo.html', context)

@user_passes_test(apenas_admin)
def remover_historico_precos_duplicados(request):
    """
    Remove entradas duplicadas na tabela HistoricoPreco.
    Mantém apenas o registro mais recente (maior ID) para cada par (ativo, data_pregao).
    """
    
    
    # Identifica pares (ativo, data_pregao) que aparecem mais de uma vez
    duplicados = HistoricoPreco.objects.values('ativo', 'data_pregao').annotate(
        count=Count('id'),
        max_id=Max('id')
    ).filter(count__gt=1)
    
    total_removidos = 0
    
    with transaction.atomic():
        for item in duplicados:
            # Seleciona todos os IDs para este par, exceto o maior (o mais recente)
            ids_para_remover = HistoricoPreco.objects.filter(
                ativo_id=item['ativo'],
                data_pregao=item['data_pregao']
            ).exclude(id=item['max_id']).values_list('id', flat=True)
            
            # Remove os duplicados
            removidos, _ = HistoricoPreco.objects.filter(id__in=ids_para_remover).delete()
            total_removidos += removidos

    if total_removidos > 0:
        messages.success(request, f"Sucesso! {total_removidos} registros duplicados de preços foram removidos.")
    else:
        messages.info(request, "A base de dados de preços já está limpa e sem duplicidade.")
        
    return redirect('core:home')

@user_passes_test(apenas_admin)
def recalcular_estruturas(request):
    """Recalcula todas as estruturas de todos os usuários."""
    estruturas = Estrutura.objects.all()
    total = estruturas.count()
    
    for est in estruturas:
        recalcular_estrutura(est)
        
    messages.success(request, f"Sucesso! {total} estruturas foram recalculadas.")
    return redirect('core:home')

@user_passes_test(apenas_admin)
def liquidez_vencimentos(request):
    """
    View para Monitoramento de Liquidez por Volume Financeiro.
    """
    ticker_filtro = request.GET.get('ticker', 'BOVA11')
    periodo_dias = 30
    apenas_mensal = True

    # 1. Ativos Monitorados para o Filtro
    ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
    
    # 2. Filtra Ativos B3 do Ticker (apenas vencimentos futuros)
    hoje = timezone.now().date()
    ativos_b3_base = AtivoB3.objects.filter(ativo_objeto=ticker_filtro, data_expiracao__gte=hoje)
    
    if apenas_mensal:
        ativos_b3_base = ativos_b3_base.filter(classificacao_vencimento='Mensal')

    # 3. Busca Histórico de Preços (90 dias + 21 para médias)
    data_limite = timezone.now().date() - datetime.timedelta(days=periodo_dias + 30)
    historico = HistoricoPreco.objects.filter(
        ativo__in=ativos_b3_base,
        data_pregao__gte=data_limite
    ).select_related('ativo').order_by('data_pregao')

    if not historico.exists():
        return render(request, 'core/liquidez_vencimentos.html', {
            'ativos_monitorados': ativos_monitorados,
            'ticker_filtro': ticker_filtro,
            'apenas_mensal': apenas_mensal,
            'periodo_dias': periodo_dias,
            'empty': True
        })

    # 4. Processamento de Dados
    # Agrupar volume por [Vencimento][DataPregão]
    vol_por_venc_data = defaultdict(lambda: defaultdict(float))
    # Agrupar volume por [Vencimento][Strike][Tipo] -> Média dos últimos 5 dias
    vol_por_venc_strike_tipo = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    
    datas_pregao_set = set()
    vencimentos_set = set()
    
    for h in historico:
        venc = h.ativo.data_expiracao
        data_p = h.data_pregao
        vol = float(h.volume_financeiro)
        tipo_str = h.ativo.tipo_opcao.upper() if h.ativo.tipo_opcao else ''
        tipo = 'CALL' if ('COMPRA' in tipo_str or 'CALL' in tipo_str) else 'PUT'
        strike = float(h.ativo.preco_exercicio or 0)
        
        vol_por_venc_data[venc][data_p] += vol
        vol_por_venc_strike_tipo[venc][strike][tipo].append({'data': data_p, 'vol': vol})
        
        datas_pregao_set.add(data_p)
        vencimentos_set.add(venc)

    sorted_datas_pregao = sorted(list(datas_pregao_set))
    sorted_vencimentos = sorted(list(vencimentos_set))
    
    # 5. Cálculo das Médias Móveis por Vencimento
    # Queremos os valores das médias NA ÚLTIMA DATA disponível para cada vencimento
    resumo_vencimentos = []
    
    for venc in sorted_vencimentos:
        diario = vol_por_venc_data[venc]
        datas_venc = sorted(diario.keys())
        
        if not datas_venc: continue
        
        # Últimos 5 e 21 pregões que tiveram dados para este vencimento
        v_5d = [diario[d] for d in datas_venc[-5:]]
        v_21d = [diario[d] for d in datas_venc[-21:]]
        
        avg_5d = sum(v_5d) / len(v_5d) if v_5d else 0
        avg_21d = sum(v_21d) / len(v_21d) if v_21d else 0
        ratio = avg_5d / avg_21d if avg_21d > 0 else 0
        
        # Proporção Call/Put nos últimos 5 dias
        vol_call_5d = 0
        vol_put_5d = 0
        for d in datas_venc[-5:]:
            vol_call_5d += sum(sum(x['vol'] for x in vol_por_venc_strike_tipo[venc][s]['CALL'] if x['data'] == d) for s in vol_por_venc_strike_tipo[venc])
            vol_put_5d += sum(sum(x['vol'] for x in vol_por_venc_strike_tipo[venc][s]['PUT'] if x['data'] == d) for s in vol_por_venc_strike_tipo[venc])
            
        total_5d = vol_call_5d + vol_put_5d
        perc_call = (vol_call_5d / total_5d * 100) if total_5d > 0 else 50
        perc_put = (vol_put_5d / total_5d * 100) if total_5d > 0 else 50

        resumo_vencimentos.append({
            'vencimento': venc,
            'vencimento_str': venc.strftime('%Y-%m-%d'),
            'vencimento_br': venc.strftime('%d/%m/%y'),
            'avg_5d': avg_5d,
            'avg_21d': avg_21d,
            'ratio': ratio,
            'perc_call': perc_call,
            'perc_put': perc_put
        })

    # 6. Gráficos B & C: Dados para todos os vencimentos ativos (para frontend alternar dinamicamente)
    evolucao_data_all = {}
    strike_data_all = {}
    
    for venc in sorted_vencimentos:
        v_str = venc.strftime('%Y-%m-%d')
        
        # Gráfico B: Evolução SMA 5d vs 21d
        diario_sel = vol_por_venc_data[venc]
        datas_sel = sorted(diario_sel.keys())
        
        evolucao_data = []
        for i, d in enumerate(datas_sel):
            v_5 = [diario_sel[datas_sel[j]] for j in range(max(0, i-4), i+1)]
            v_21 = [diario_sel[datas_sel[j]] for j in range(max(0, i-20), i+1)]
            evolucao_data.append({
                'data': d.strftime('%d/%m/%Y'),
                'vol': diario_sel[d],
                'sma5': sum(v_5) / len(v_5),
                'sma21': sum(v_21) / len(v_21)
            })
        evolucao_data_all[v_str] = evolucao_data

        # Gráfico C: Volume por Strike (Média 5d)
        strikes_sel = sorted(vol_por_venc_strike_tipo[venc].keys())
        distribuicao_strike = []
        for s in strikes_sel:
            c_vols = [x['vol'] for x in vol_por_venc_strike_tipo[venc][s]['CALL']][-5:]
            p_vols = [x['vol'] for x in vol_por_venc_strike_tipo[venc][s]['PUT']][-5:]
            distribuicao_strike.append({
                'strike': s,
                'call_vol': sum(c_vols) / len(c_vols) if c_vols else 0,
                'put_vol': sum(p_vols) / len(p_vols) if p_vols else 0
            })
        strike_data_all[v_str] = distribuicao_strike

    # Define um vencimento padrão para inicialização do frontend
    vencimento_selecionado_default = ""
    if resumo_vencimentos:
        vencimento_selecionado_default = sorted(resumo_vencimentos, key=lambda x: x['avg_5d'], reverse=True)[0]['vencimento_str']

    # Preço Atual do Ativo Objeto (para a linha ATM)
    ativo_obj = AtivoB3.objects.filter(ticker=ticker_filtro).first()
    preco_atm = 0
    if ativo_obj:
        last_p = HistoricoPreco.objects.filter(ativo=ativo_obj).order_by('-data_pregao').first()
        if last_p: preco_atm = float(last_p.fechamento)

    context = {
        'ativos_monitorados': ativos_monitorados,
        'ticker_filtro': ticker_filtro,
        'resumo_vencimentos': resumo_vencimentos,
        'evolucao_json_all': json.dumps(evolucao_data_all),
        'strike_json_all': json.dumps(strike_data_all),
        'resumo_json': json.dumps([{
            'vencimento': r['vencimento_br'], 
            'avg_5d': r['avg_5d'], 
            'avg_21d': r['avg_21d']
        } for r in resumo_vencimentos]),
        'resumo_json_excluindo_proximos': json.dumps([{
            'vencimento': r['vencimento_br'], 
            'avg_5d': r['avg_5d'], 
            'avg_21d': r['avg_21d']
        } for r in resumo_vencimentos[2:]]),
        'vencimento_selecionado_default': vencimento_selecionado_default,
        'preco_atm': preco_atm,
    }
    
    return render(request, 'core/liquidez_vencimentos.html', context)

from .models import OpenInterest
from .services import processar_csv_open_interest

@user_passes_test(apenas_admin)
def upload_open_interest(request):
    if request.method == 'POST' and request.FILES.getlist('arquivo_csv'):
        files = request.FILES.getlist('arquivo_csv')
        total_novos = 0
        total_atualizados = 0
        todos_erros = []
        
        start_time = time.time()
        for file in files:
            print(f"[*] Processando Open Interest: {file.name}")
            content = file.read()
            stats = processar_csv_open_interest(content, file.name)
            total_novos += stats['novos']
            total_atualizados += stats['atualizados']
            if stats['erros']:
                todos_erros.append(f"Erros em {file.name}: {len(stats['erros'])} problemas (ex: {stats['erros'][0]})")
                
            HistoricoImportacao.objects.create(
                tipo_importacao='Open Interest',
                arquivo_nome=file.name,
                novos=stats['novos'],
                atualizados=stats['atualizados'],
                sem_alteracao=0,
                detalhes=stats['erros']
            )

        end_time = time.time()
        if todos_erros:
            for erro in todos_erros:
                messages.warning(request, erro)
        
        messages.success(request, f"Processamento concluído em {end_time - start_time:.2f}s! Novos: {total_novos}, Atualizados: {total_atualizados}.")
        return redirect('core:upload_open_interest')
        
    return render(request, 'core/upload_open_interest.html')

@user_passes_test(apenas_admin)
def consultar_open_interest(request):
    ticker_filtro = request.GET.get('ticker', 'BOVA11')
    data_filtro_str = request.GET.get('data', None)
    vencimento_filtro_str = request.GET.get('vencimento', None)
    
    ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
    
    # 1. Buscar datas disponíveis
    datas_disponiveis = OpenInterest.objects.values_list('data_referencia', flat=True).distinct().order_by('-data_referencia')
    
    if data_filtro_str:
        try:
            data_filtro = datetime.datetime.strptime(data_filtro_str, '%Y-%m-%d').date()
        except ValueError:
            data_filtro = datas_disponiveis.first() if datas_disponiveis else None
    else:
        data_filtro = datas_disponiveis.first() if datas_disponiveis else None

    # 2. Buscar vencimentos disponíveis para o ativo
    vencimentos_disponiveis = []
    if data_filtro:
        vencimentos_disponiveis = OpenInterest.objects.filter(
            ativo_objeto=ticker_filtro,
            data_referencia=data_filtro
        ).values_list('ativo__data_expiracao', flat=True).distinct().order_by('ativo__data_expiracao')

    # 3. Determinar vencimento padrão (próximo mensal)
    if not vencimento_filtro_str:
        hoje = timezone.now().date()
        # Busca o próximo vencimento mensal no cadastro de ativos
        vencimento_padrao = AtivoB3.objects.filter(
            ativo_objeto=ticker_filtro,
            data_expiracao__gte=hoje,
            classificacao_vencimento='Mensal'
        ).order_by('data_expiracao').values_list('data_expiracao', flat=True).first()
        
        # Se não achou no cadastro, pega o primeiro disponível do OpenInterest
        if not vencimento_padrao and vencimentos_disponiveis:
            vencimento_padrao = vencimentos_disponiveis[0]
            
        if vencimento_padrao:
            vencimento_filtro = vencimento_padrao
        else:
            vencimento_filtro = None
    else:
        try:
            vencimento_filtro = datetime.datetime.strptime(vencimento_filtro_str, '%Y-%m-%d').date()
        except ValueError:
            vencimento_filtro = vencimentos_disponiveis[0] if vencimentos_disponiveis else None

    # 4. Buscar e organizar dados por strike
    dados_organizados = []
    if data_filtro and vencimento_filtro:
        # Busca todas as posições para o ativo, data e vencimento selecionados
        posicoes = OpenInterest.objects.filter(
            ativo_objeto=ticker_filtro,
            data_referencia=data_filtro,
            ativo__data_expiracao=vencimento_filtro
        ).select_related('ativo').order_by('ativo__preco_exercicio')
        
        # Agrupar por strike
        por_strike = defaultdict(lambda: {'call': None, 'put': None})
        for p in posicoes:
            strike = p.ativo.preco_exercicio
            tipo = p.ativo.tipo_opcao.upper()
            if 'CALL' in tipo or 'COMPRA' in tipo:
                por_strike[strike]['call'] = p
            elif 'PUT' in tipo or 'VENDA' in tipo:
                por_strike[strike]['put'] = p
        
        # Transformar em lista ordenada
        strikes_ordenados = sorted(por_strike.keys())
        for s in strikes_ordenados:
            dados_organizados.append({
                'strike': s,
                'call': por_strike[s]['call'],
                'put': por_strike[s]['put']
            })
        
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

@user_passes_test(apenas_admin)
def grafico_open_interest(request):
    ticker_filtro = request.GET.get('ticker', 'BOVA11')
    vencimento_filtro_str = request.GET.get('vencimento', None)
    tipo_filtro = request.GET.get('tipo', 'TODOS') # CALL, PUT, TODOS
    
    ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
    
    # Busca a última data de referência global
    ultima_data = OpenInterest.objects.aggregate(Max('data_referencia'))['data_referencia__max']
    
    vencimentos_disponiveis = []
    if ultima_data:
        vencimentos_disponiveis = OpenInterest.objects.filter(
            ativo_objeto=ticker_filtro,
            data_referencia=ultima_data
        ).values_list('ativo__data_expiracao', flat=True).distinct().order_by('ativo__data_expiracao')

    if not vencimento_filtro_str and vencimentos_disponiveis:
        # Padrão: Próximo mensal
        hoje = timezone.now().date()
        vencimento_padrao = AtivoB3.objects.filter(
            ativo_objeto=ticker_filtro,
            data_expiracao__gte=hoje,
            classificacao_vencimento='Mensal'
        ).order_by('data_expiracao').values_list('data_expiracao', flat=True).first()
        
        vencimento_filtro = vencimento_padrao if vencimento_padrao else vencimentos_disponiveis[0]
    elif vencimento_filtro_str:
        vencimento_filtro = datetime.datetime.strptime(vencimento_filtro_str, '%Y-%m-%d').date()
    else:
        vencimento_filtro = None

    chart_data = {'strikes': [], 'coberta': [], 'descoberta': [], 'trava': []}
    
    if ultima_data and vencimento_filtro:
        qs = OpenInterest.objects.filter(
            ativo_objeto=ticker_filtro,
            data_referencia=ultima_data,
            ativo__data_expiracao=vencimento_filtro
        ).select_related('ativo').order_by('ativo__preco_exercicio')
        
        if tipo_filtro == 'CALL':
            qs = qs.filter(Q(ativo__tipo_opcao__icontains='CALL') | Q(ativo__tipo_opcao__icontains='COMPRA'))
        elif tipo_filtro == 'PUT':
            qs = qs.filter(Q(ativo__tipo_opcao__icontains='PUT') | Q(ativo__tipo_opcao__icontains='VENDA'))
            
        # Agrupar por strike (caso tenha call e put no mesmo gráfico, somamos ou mostramos lado a lado?)
        # O usuário pediu "quantidade de posições devem ser exibidas em um gráfico de barras empilhado"
        # Se for TODOS, vamos somar call e put por strike? Ou separar? 
        # Geralmente em OI se separa call de put, mas o filtro permite escolher.
        # Vamos agrupar por strike para o gráfico.
        data_por_strike = defaultdict(lambda: {'coberta': 0, 'descoberta': 0, 'trava': 0})
        for p in qs:
            s = float(p.ativo.preco_exercicio)
            data_por_strike[s]['coberta'] += p.quantidade_coberta
            data_por_strike[s]['descoberta'] += p.quantidade_descoberta
            data_por_strike[s]['trava'] += p.total_travas
            
        sorted_strikes = sorted(data_por_strike.keys())
        for s in sorted_strikes:
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

@user_passes_test(apenas_admin)
def barreiras_open_interest(request):
    ticker_filtro = request.GET.get('ticker', 'BOVA11')
    min_posicoes_raw = request.GET.get('min_posicoes', '2000000')
    try:
        min_posicoes = int(min_posicoes_raw) if min_posicoes_raw else 2000000
    except ValueError:
        min_posicoes = 2000000
    
    ativos_monitorados = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).order_by('ticker')
    
    ultima_data = OpenInterest.objects.aggregate(Max('data_referencia'))['data_referencia__max']
    
    dados_barreiras = []
    if ultima_data:
        dados_barreiras = OpenInterest.objects.filter(
            ativo_objeto=ticker_filtro,
            data_referencia=ultima_data,
            total_posicoes__gte=min_posicoes
        ).select_related('ativo').order_by('-total_posicoes')
        
    context = {
        'ativos_monitorados': ativos_monitorados,
        'ticker_filtro': ticker_filtro,
        'min_posicoes': min_posicoes,
        'ultima_data': ultima_data,
        'dados_barreiras': dados_barreiras,
    }
    return render(request, 'core/barreiras_oi.html', context)
