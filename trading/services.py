import logging
from .models import Estrutura, Ordem, PosicaoConsolidada, DailySnapshot, Rolagem, RolagemLeg, RolagemSnapshot
from core.models import HistoricoPreco, AtivoB3
from core.utils.converters import convert_to_date, convert_to_decimal, convert_to_int
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.utils.timezone import make_aware
from django.db import transaction
import io
import csv


logger = logging.getLogger(__name__)

def calcular_estado_posicao(ordens):
    """
    Função pura que calcula o estado final (qtd, preço médio e PL realizado)
    a partir de uma lista de ordens (queryset ou list) ordenadas cronologicamente.
    """
    qtd_atual = 0
    preco_medio = Decimal('0.0')
    pl_realizado = Decimal('0.0')

    for ordem in ordens:
        qtd_ordem = ordem.quantidade
        preco_ordem = ordem.preco

        if qtd_atual == 0:
            qtd_atual = qtd_ordem
            preco_medio = preco_ordem
        else:
            # Aumento de posição (mesmo sinal)
            if (qtd_atual > 0 and qtd_ordem > 0) or (qtd_atual < 0 and qtd_ordem < 0):
                valor_total_anterior = abs(qtd_atual) * preco_medio
                valor_ordem = abs(qtd_ordem) * preco_ordem
                nova_qtd = qtd_atual + qtd_ordem
                preco_medio = (valor_total_anterior + valor_ordem) / abs(nova_qtd)
                qtd_atual = nova_qtd
            # Diminuição de posição (sinais opostos)
            else:
                if abs(qtd_ordem) <= abs(qtd_atual):
                    qtd_reduzida = abs(qtd_ordem)
                    if qtd_atual > 0: # Estávamos comprados
                        pl_realizado += (preco_ordem - preco_medio) * qtd_reduzida
                    else: # Estávamos vendidos
                        pl_realizado += (preco_medio - preco_ordem) * qtd_reduzida
                        
                    qtd_atual += qtd_ordem
                    if qtd_atual == 0:
                        preco_medio = Decimal('0.0')
                else: # Virando a mão
                    qtd_zerada = abs(qtd_atual)
                    if qtd_atual > 0:
                        pl_realizado += (preco_ordem - preco_medio) * qtd_zerada
                    else:
                        pl_realizado += (preco_medio - preco_ordem) * qtd_zerada
                        
                    qtd_atual = qtd_ordem + qtd_atual
                    preco_medio = preco_ordem
    
    return qtd_atual, preco_medio, pl_realizado

def recalcular_posicao(estrutura, ativo):
    """
    Recalcula a posição consolidada de um ativo dentro de uma estrutura.
    """
    ordens = Ordem.objects.filter(estrutura=estrutura, ativo=ativo).order_by('data', 'criado_em')
    
    if not ordens.exists():
        PosicaoConsolidada.objects.filter(estrutura=estrutura, ativo=ativo).delete()
        return

    qtd_atual, preco_medio, pl_realizado = calcular_estado_posicao(ordens)

    # Atualiza ou cria PosicaoConsolidada
    PosicaoConsolidada.objects.update_or_create(
        estrutura=estrutura,
        ativo=ativo,
        defaults={
            'quantidade_atual': qtd_atual,
            'preco_medio': preco_medio,
            'pl_realizado_acumulado': pl_realizado
        }
    )

from django.db.models import Min, Max
from collections import defaultdict
from datetime import timedelta

def recalcular_estrutura(estrutura, data_base=None):
    """
    Soma as posições consolidadas para obter o PL aberto, realizado e o valor total.
    Também reconstrói o histórico diário (DailySnapshot) da estrutura desde o dia da primeira ordem
    até o último dia disponível no HistoricoPreco dos ativos envolvidos ou data da última ordem.
    """
    ordens = list(Ordem.objects.filter(estrutura=estrutura).order_by('data', 'criado_em').select_related('ativo'))
    
    if not ordens:
        DailySnapshot.objects.filter(estrutura=estrutura).delete()
        estrutura.pl_realizado = 0
        estrutura.pl_aberto = 0
        estrutura.valor_total = 0
        estrutura.exposicao_atual = 0
        estrutura.save(update_fields=['pl_realizado', 'pl_aberto', 'valor_total', 'exposicao_atual'])
        return
        
    min_date = min(o.data for o in ordens)
    max_ordem_date = max(o.data for o in ordens)
    
    ativos_envolvidos = set(o.ativo for o in ordens)
    
    max_hist_date_dict = HistoricoPreco.objects.filter(ativo__in=ativos_envolvidos).aggregate(Max('data_pregao'))
    max_hist_date = max_hist_date_dict['data_pregao__max']
    
    if max_hist_date:
        max_date = max(max_ordem_date, max_hist_date)
    else:
        max_date = max(max_ordem_date, date.today())
        
    # Se a estrutura está FECHADA, o gráfico não deve ir além da última ordem
    if estrutura.status == 'FECHADA':
        max_date = max_ordem_date
        
    # Otimização: carregar todos os preços do intervalo
    historicos = HistoricoPreco.objects.filter(
        ativo__in=ativos_envolvidos, 
        data_pregao__gte=min_date, 
        data_pregao__lte=max_date
    ).order_by('data_pregao')
    
    precos_por_ativo = defaultdict(dict)
    for h in historicos:
        precos_por_ativo[h.ativo_id][h.data_pregao] = h.fechamento
        
    ultimo_preco_conhecido = {a.codigo_isin: Decimal('0.0') for a in ativos_envolvidos}
    estado = {a.codigo_isin: {'qtd': 0, 'preco_medio': Decimal('0.0'), 'pl_realizado': Decimal('0.0')} for a in ativos_envolvidos}
        
    ordens_por_dia = defaultdict(list)
    for o in ordens:
        ordens_por_dia[o.data].append(o)
        
    snapshots_to_create = []
    
    current_date = min_date
    while current_date <= max_date:
        # 1. Atualiza preços conhecidos se houver preço para o dia
        for a in ativos_envolvidos:
            if current_date in precos_por_ativo[a.codigo_isin]:
                val = precos_por_ativo[a.codigo_isin][current_date]
                if val > 0:
                    ultimo_preco_conhecido[a.codigo_isin] = val
                    
        # 2. Executa as ordens do dia
        if current_date in ordens_por_dia:
            for ordem in ordens_por_dia[current_date]:
                # Usa a mesma lógica unificada para cada ordem que entra no snapshot
                # Mockamos uma lista de ordens de tamanho 1 para aproveitar a função pura
                st = estado[ordem.ativo.codigo_isin]
                
                # Mock temporário do estado para passar para a função
                from dataclasses import dataclass
                @dataclass
                class MockOrdem:
                    quantidade: int
                    preco: Decimal
                
                # Para manter a compatibilidade com calcular_estado_posicao, 
                # precisamos gerenciar o estado acumulado manualmente aqui ou passar o histórico todo.
                # Como queremos performance no loop cronológico, vamos manter a lógica inline aqui, 
                # mas garantindo que seja IDENTICA à calcular_estado_posicao.
                
                qtd_atual = st['qtd']
                preco_medio = st['preco_medio']
                pl_realizado = st['pl_realizado']
                
                qtd_ordem = ordem.quantidade
                preco_ordem = ordem.preco
                
                if qtd_atual == 0:
                    qtd_atual = qtd_ordem
                    preco_medio = preco_ordem
                else:
                    if (qtd_atual > 0 and qtd_ordem > 0) or (qtd_atual < 0 and qtd_ordem < 0):
                        valor_total_anterior = abs(qtd_atual) * preco_medio
                        valor_ordem = abs(qtd_ordem) * preco_ordem
                        nova_qtd = qtd_atual + qtd_ordem
                        preco_medio = (valor_total_anterior + valor_ordem) / abs(nova_qtd)
                        qtd_atual = nova_qtd
                    else:
                        if abs(qtd_ordem) <= abs(qtd_atual):
                            qtd_reduzida = abs(qtd_ordem)
                            if qtd_atual > 0:
                                pl_realizado += (preco_ordem - preco_medio) * qtd_reduzida
                            else:
                                pl_realizado += (preco_medio - preco_ordem) * qtd_reduzida
                            qtd_atual += qtd_ordem
                            if qtd_atual == 0:
                                preco_medio = Decimal('0.0')
                        else:
                            qtd_zerada = abs(qtd_atual)
                            if qtd_atual > 0:
                                pl_realizado += (preco_ordem - preco_medio) * qtd_zerada
                            else:
                                pl_realizado += (preco_medio - preco_ordem) * qtd_zerada
                            qtd_atual = qtd_ordem + qtd_atual
                            preco_medio = preco_ordem
                            
                estado[ordem.ativo.codigo_isin] = {'qtd': qtd_atual, 'preco_medio': preco_medio, 'pl_realizado': pl_realizado}
                if ultimo_preco_conhecido[ordem.ativo.codigo_isin] == 0:
                    ultimo_preco_conhecido[ordem.ativo.codigo_isin] = preco_ordem

        # 3. Calcula Snapshot do dia
        pl_realizado_total = sum(st['pl_realizado'] for st in estado.values())
        pl_aberto_total = Decimal('0.0')
        exposicao_total = Decimal('0.0')
        
        for a in ativos_envolvidos:
            st = estado[a.codigo_isin]
            qtd = st['qtd']
            if qtd != 0:
                preco_atual = ultimo_preco_conhecido[a.codigo_isin]
                if preco_atual == 0:
                    preco_atual = st['preco_medio']
                
                exposicao_total += qtd * preco_atual
                
                if qtd > 0:
                    pl_aberto_total += (preco_atual - st['preco_medio']) * qtd
                else:
                    pl_aberto_total += (st['preco_medio'] - preco_atual) * abs(qtd)
                    
        valor_total = pl_realizado_total + pl_aberto_total
        
        # Só salvar snapshots para dias de semana (segunda a sexta) ou se explicitamente for um dia de ordem
        # Para evitar encher de finais de semana sem movimento
        if current_date.weekday() < 5 or current_date in ordens_por_dia:
            snapshots_to_create.append(
                DailySnapshot(
                    estrutura=estrutura,
                    data=current_date,
                    pl_realizado=pl_realizado_total,
                    pl_aberto=pl_aberto_total,
                    valor_total=valor_total,
                    exposicao_diaria=exposicao_total
                )
            )
        
        current_date += timedelta(days=1)
        
    with transaction.atomic():
        DailySnapshot.objects.filter(estrutura=estrutura).delete()
        DailySnapshot.objects.bulk_create(snapshots_to_create)
        
    # Atualiza a estrutura com os valores do último snapshot gerado
    if snapshots_to_create:
        last = snapshots_to_create[-1]
        estrutura.pl_realizado = last.pl_realizado
        estrutura.pl_aberto = last.pl_aberto
        estrutura.valor_total = last.valor_total
        estrutura.exposicao_atual = last.exposicao_diaria
        
        # Datas e estatísticas
        primeira_ordem = ordens[0].data
        ultima_ordem = ordens[-1].data
        estrutura.data_inicial = primeira_ordem
        estrutura.data_final = ultima_ordem
        
        # Dias de vida da estrutura (da primeira até a última ordem)
        delta = ultima_ordem - primeira_ordem
        estrutura.dias_estrutura = delta.days
        
        # Se todos os snapshots tiverem PL Aberto zero e a quantidade for zero em todos ativos, 
        # a estrutura pode ser considerada fechada se o usuário quiser, mas vamos manter a lógica de datas.
        
        estrutura.save(update_fields=['pl_realizado', 'pl_aberto', 'valor_total', 'exposicao_atual', 'data_inicial', 'data_final', 'dias_estrutura'])



def processar_upload_csv(file, usuario):
    """
    Processa um CSV com ordens e aloca na estrutura padrão 'sem-estrutura'.
    Formato esperado: data (DD/MM/YYYY), ativo, quantidade, preco.
    """
    estrutura_padrao, _ = Estrutura.objects.get_or_create(
        usuario=usuario, 
        slug='sem-estrutura', 
        defaults={'nome': 'Sem Estrutura'}
    )
    
    content = file.read().decode('utf-8-sig', errors='replace')
    io_string = io.StringIO(content)
    
    # Tenta descobrir o delimitador (vamos assumir ; ou ,)
    primeira_linha = io_string.readline()
    delimitador = ';' if ';' in primeira_linha else ','
    io_string.seek(0)
    
    reader = csv.DictReader(io_string, delimiter=delimitador)
    
    sucesso = 0
    erros = []
    ordens_to_create = []
    
    for i, linha in enumerate(reader, start=2):
        try:
            # Normaliza as chaves do dicionário (lowercase e sem espaços extras)
            linha_clean = {k.lower().strip(): v for k, v in linha.items() if k}
            
            # Procura colunas possíveis
            col_data = linha_clean.get('data') or linha_clean.get('data do negocio')
            col_ativo = linha_clean.get('ativo') or linha_clean.get('codigo de negociacao') or linha_clean.get('ticker')
            col_qtd = linha_clean.get('quantidade') or linha_clean.get('qtd')
            col_preco = linha_clean.get('preco') or linha_clean.get('preço')
            col_operacao = linha_clean.get('operacao') or linha_clean.get('tipo de movimentacao') or linha_clean.get('compra/venda')
            
            if not all([col_data, col_ativo, col_qtd, col_preco]):
                erros.append(f"Linha {i}: Colunas obrigatórias não encontradas.")
                continue
            
            # Processamento dos valores usando conversores centralizados
            data_obj = convert_to_date(str(col_data).strip())
            ativo_str = str(col_ativo).strip().upper()
            quantidade = convert_to_int(str(col_qtd))
            preco = convert_to_decimal(str(col_preco))
            
            # Ajusta sinal da quantidade se houver coluna de operação
            if col_operacao:
                op = str(col_operacao).lower().strip()
                if op in ['v', 'venda', 'vender', 's', 'sell']:
                    quantidade = -abs(quantidade)
                elif op in ['c', 'compra', 'comprar', 'b', 'buy']:
                    quantidade = abs(quantidade)
            
            # Validação do ativo
            ativo_obj = AtivoB3.objects.filter(ticker=ativo_str).first()
            if not ativo_obj:
                erros.append(f"Linha {i}: Ativo '{ativo_str}' não cadastrado no banco. Operação ignorada.")
                continue
                
            ordens_to_create.append(Ordem(
                estrutura=estrutura_padrao,
                ativo=ativo_obj,
                quantidade=quantidade,
                preco=preco,
                data=data_obj
            ))
            sucesso += 1
            
        except Exception as e:
            erros.append(f"Linha {i}: Erro de formatação - {str(e)}")
            
    if ordens_to_create:
        from django.db import transaction
        with transaction.atomic():
            Ordem.objects.bulk_create(ordens_to_create)
            recalcular_estrutura(estrutura_padrao)
        
    return sucesso, erros

def importar_ordens_profit(user, csv_file):
    logger.info("Iniciando importação de ordens do Profit")
    
    # Lê os bytes puros primeiro
    raw_data = csv_file.read()
    
    # Tenta decodificar de forma resiliente
    try:
        content = raw_data.decode('utf-8')
        logger.debug("Decodificado com UTF-8")
    except UnicodeDecodeError:
        content = raw_data.decode('iso-8859-1')
        logger.debug("Decodificado com ISO-8859-1 (Latin-1)")

    lines = content.splitlines()
    logger.info(f"Total de linhas no arquivo: {len(lines)}")
    
    # Se o arquivo estiver vazio após o read, é porque o ponteiro do arquivo já estava no fim
    if not lines:
        print("DEBUG: Arquivo vazio ou ponteiro no fim. Tentando resetar ponteiro...")
        csv_file.seek(0)
        raw_data = csv_file.read()
        content = raw_data.decode('iso-8859-1', errors='ignore')
        lines = content.splitlines()

    # Localizar o cabeçalho
    header_index = -1
    for i, line in enumerate(lines):
        if 'Ativo;' in line and 'Status;' in line:
            header_index = i
            break
    
    if header_index == -1:
        logger.error("Cabeçalho 'Ativo;Status' não encontrado no CSV do Profit")
        return 0, ["Cabecalho do Profit nao encontrado."]

    logger.debug(f"Cabeçalho encontrado na linha {header_index + 1}")

    f = io.StringIO('\n'.join(lines[header_index:]))
    reader = csv.DictReader(f, delimiter=';')
    
    ordens_para_criar = []
    erros = []
    
    # Garantir estrutura
    est, _ = Estrutura.objects.get_or_create(usuario=user, nome="Sem Estrutura")

    with transaction.atomic():
        for row_num, row in enumerate(reader, start=header_index + 2):
            # Limpar espaços dos nomes das colunas
            row = {k.strip(): v.strip() for k, v in row.items() if k}
            
            status = row.get('Status', '')
            ativo_ticker = row.get('Ativo', '')
            
            print(f"DEBUG: Processando Linha {row_num} - Ativo: {ativo_ticker} - Status: {status}")

            if status != 'Executada':
                continue

            try:
                ativo_obj = AtivoB3.objects.get(ticker=ativo_ticker)
                
                # Preço e Qtd (Tratando formato PT-BR via novos conversores)
                preco = convert_to_decimal(row['Preço'])
                qtd = convert_to_int(row['Qtd'])
                
                if row['Lado'].upper() == 'V':
                    qtd = -qtd

                dt_obj = datetime.strptime(row['Criação'], '%d/%m/%Y %H:%M:%S')
                
                ordens_para_criar.append(Ordem(
                    estrutura=est,
                    ativo=ativo_obj,
                    quantidade=qtd,
                    preco=preco,
                    data=dt_obj.date(),
                    criado_em=make_aware(dt_obj)
                ))
                logger.debug(f"Ordem preparada: {ativo_ticker}")
            except AtivoB3.DoesNotExist:
                logger.warning(f"Ativo {ativo_ticker} não cadastrado")
                erros.append(f"Ativo {ativo_ticker} não cadastrado.")
            except Exception as e:
                logger.error(f"Erro na linha {row_num} do CSV Profit: {e}")
                erros.append(f"Linha {row_num}: {str(e)}")

        if ordens_para_criar:
            Ordem.objects.bulk_create(ordens_para_criar)
            logger.info(f"{len(ordens_para_criar)} ordens salvas.")
            recalcular_estrutura(est)
            
    return len(ordens_para_criar), erros

def recalcular_rolagem(rolagem):
    """
    Calcula o histórico de spreads da rolagem baseando-se no VWAP diário das legs.
    """
    from collections import defaultdict
    from decimal import Decimal
    from django.db import transaction
    from .models import RolagemSnapshot, RolagemLeg
    from core.models import HistoricoPreco

    legs = list(rolagem.legs.all().select_related('ativo'))
    if not legs:
        RolagemSnapshot.objects.filter(rolagem=rolagem).delete()
        rolagem.spread_atual = None
        rolagem.melhor_spread_historico = None
        rolagem.variacao_5d = None
        rolagem.save()
        return

    ativos_ids = [leg.ativo_id for leg in legs]
    historicos = HistoricoPreco.objects.filter(ativo_id__in=ativos_ids).order_by('data_pregao')
    
    dados_por_dia = defaultdict(dict)
    contratos_por_dia = defaultdict(dict)
    fechamento_por_dia = defaultdict(dict)
    
    for h in historicos:
        vwap = Decimal('0')
        if h.quantidade_contratos > 0:
            vwap = h.volume_financeiro / h.quantidade_contratos
        
        dados_por_dia[h.data_pregao][h.ativo_id] = vwap
        contratos_por_dia[h.data_pregao][h.ativo_id] = h.quantidade_contratos
        fechamento_por_dia[h.data_pregao][h.ativo_id] = h.fechamento

    datas_disponiveis = sorted(dados_por_dia.keys())
    snapshots_to_create = []
    
    for data in datas_disponiveis:
        valido_spread = True
        detalhes = {}
        spread_total_dia = Decimal('0')
        spread_fechamento_dia = Decimal('0')
        
        for leg in legs:
            contratos = contratos_por_dia[data].get(leg.ativo_id, 0)
            vwap = dados_por_dia[data].get(leg.ativo_id)
            fechamento = fechamento_por_dia[data].get(leg.ativo_id)
            
            # Detalhes armazena vwap e contratos (contratos não sofre influência do filtro)
            detalhes[leg.ativo.ticker] = {
                'vwap': float(vwap) if vwap else 0.0,
                'fechamento': float(fechamento) if fechamento else 0.0,
                'contratos': contratos
            }
            
            # Validação para o spread (VWAP e contratos mínimos)
            if contratos < rolagem.filtro_liquidez or vwap is None or fechamento is None:
                valido_spread = False
                
            if vwap:
                spread_total_dia += vwap * leg.quantidade
            if fechamento:
                spread_fechamento_dia += fechamento * leg.quantidade
            
        if not valido_spread:
            spread_total_dia = None
            spread_fechamento_dia = None
            
        snapshots_to_create.append(RolagemSnapshot(
            rolagem=rolagem,
            data=data,
            spread_total=spread_total_dia,
            spread_fechamento=spread_fechamento_dia,
            detalhes_legs=detalhes
        ))

    with transaction.atomic():
        RolagemSnapshot.objects.filter(rolagem=rolagem).delete()
        RolagemSnapshot.objects.bulk_create(snapshots_to_create)

    # Atualiza Cache apenas com dias válidos
    snapshots_validos = [s for s in snapshots_to_create if s.spread_total is not None]
    
    if snapshots_validos:
        rolagem.spread_atual = snapshots_validos[-1].spread_total
        
        # Média dos últimos 5 dias válidos
        ultimos_5 = snapshots_validos[-5:]
        rolagem.spread_medio_5d = sum(s.spread_total for s in ultimos_5) / len(ultimos_5)
        
        rolagem.save(update_fields=['spread_atual', 'spread_medio_5d'])
    else:
        rolagem.spread_atual = None
        rolagem.spread_medio_5d = None
        rolagem.save(update_fields=['spread_atual', 'spread_medio_5d'])

def exportar_estruturas_json(estrutura_ids, usuario):
    """
    Exporta as estruturas selecionadas (pelo id) do usuário como um dicionário serializável em JSON.
    Inclui: metadados da estrutura, todas as ordens, posições consolidadas e snapshots diários.
    """
    from decimal import Decimal

    estruturas = Estrutura.objects.filter(id__in=estrutura_ids, usuario=usuario).prefetch_related(
        'ordens__ativo', 'posicoes__ativo', 'historico_snapshots'
    )

    payload = {
        'versao': '1.0',
        'exportado_em': datetime.now().isoformat(),
        'usuario': usuario.username,
        'estruturas': []
    }

    for est in estruturas:
        ordens_data = []
        for o in est.ordens.all().order_by('data', 'criado_em'):
            ordens_data.append({
                'ativo_ticker': o.ativo.ticker,
                'quantidade': o.quantidade,
                'preco': str(o.preco),
                'data': o.data.isoformat(),
            })

        posicoes_data = []
        for p in est.posicoes.all():
            posicoes_data.append({
                'ativo_ticker': p.ativo.ticker,
                'quantidade_atual': p.quantidade_atual,
                'preco_medio': str(p.preco_medio),
                'pl_realizado_acumulado': str(p.pl_realizado_acumulado),
            })

        snapshots_data = []
        for s in est.historico_snapshots.order_by('data'):
            snapshots_data.append({
                'data': s.data.isoformat(),
                'pl_realizado': str(s.pl_realizado),
                'pl_aberto': str(s.pl_aberto),
                'valor_total': str(s.valor_total),
                'exposicao_diaria': str(s.exposicao_diaria),
            })

        payload['estruturas'].append({
            'nome': est.nome,
            'status': est.status,
            'pl_realizado': str(est.pl_realizado),
            'pl_aberto': str(est.pl_aberto),
            'valor_total': str(est.valor_total),
            'exposicao_atual': str(est.exposicao_atual),
            'data_inicial': est.data_inicial.isoformat() if est.data_inicial else None,
            'data_final': est.data_final.isoformat() if est.data_final else None,
            'dias_estrutura': est.dias_estrutura,
            'criado_em': est.criado_em.isoformat(),
            'ordens': ordens_data,
            'posicoes': posicoes_data,
            'snapshots': snapshots_data,
        })

    return payload


def importar_estruturas_json(payload, usuario, nomes_selecionados=None):
    """
    Importa estruturas a partir de um payload JSON previamente exportado.
    - nomes_selecionados: lista de nomes de estruturas a restaurar. Se None, importa todas.
    - Estruturas com nome conflitante recebem sufixo com data/hora.
    - Retorna (qtd_criadas, erros)
    """
    from django.utils.text import slugify
    import uuid
    from decimal import Decimal, InvalidOperation

    erros = []
    criadas = 0

    estruturas_payload = payload.get('estruturas', [])

    if nomes_selecionados is not None:
        estruturas_payload = [e for e in estruturas_payload if e.get('nome') in nomes_selecionados]

    if not estruturas_payload:
        return 0, ['Nenhuma estrutura selecionada para restaurar.']

    for est_data in estruturas_payload:
        try:
            nome_base = est_data.get('nome', 'Estrutura Importada')

            # Resolve conflito de nomes
            nome_final = nome_base
            if Estrutura.objects.filter(usuario=usuario, nome=nome_base).exists():
                sufixo = datetime.now().strftime('%d%m%y-%H%M')
                nome_final = f"{nome_base} ({sufixo})"

            base_slug = slugify(nome_final) or 'estrutura'
            slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

            with transaction.atomic():
                nova_est = Estrutura.objects.create(
                    usuario=usuario,
                    nome=nome_final,
                    slug=slug,
                    status=est_data.get('status', 'ABERTA'),
                    pl_realizado=Decimal(est_data.get('pl_realizado', '0') or '0'),
                    pl_aberto=Decimal(est_data.get('pl_aberto', '0') or '0'),
                    valor_total=Decimal(est_data.get('valor_total', '0') or '0'),
                    exposicao_atual=Decimal(est_data.get('exposicao_atual', '0') or '0'),
                    data_inicial=est_data.get('data_inicial') or None,
                    data_final=est_data.get('data_final') or None,
                    dias_estrutura=est_data.get('dias_estrutura', 0) or 0,
                )

                # Importa as ordens
                ordens_para_criar = []
                for o_data in est_data.get('ordens', []):
                    ticker = o_data.get('ativo_ticker', '').upper().strip()
                    ativo = AtivoB3.objects.filter(ticker=ticker).first()
                    if not ativo:
                        erros.append(f"[{nome_final}] Ativo '{ticker}' não encontrado. Ordem ignorada.")
                        continue
                    try:
                        ordens_para_criar.append(Ordem(
                            estrutura=nova_est,
                            ativo=ativo,
                            quantidade=int(o_data['quantidade']),
                            preco=Decimal(str(o_data['preco'])),
                            data=date.fromisoformat(o_data['data']),
                        ))
                    except Exception as e:
                        erros.append(f"[{nome_final}] Erro ao processar ordem ({ticker}): {e}")

                if ordens_para_criar:
                    Ordem.objects.bulk_create(ordens_para_criar)

                # Importa snapshots diários (se existirem no backup)
                snapshots_para_criar = []
                for s_data in est_data.get('snapshots', []):
                    try:
                        snapshots_para_criar.append(DailySnapshot(
                            estrutura=nova_est,
                            data=date.fromisoformat(s_data['data']),
                            pl_realizado=Decimal(str(s_data.get('pl_realizado', '0') or '0')),
                            pl_aberto=Decimal(str(s_data.get('pl_aberto', '0') or '0')),
                            valor_total=Decimal(str(s_data.get('valor_total', '0') or '0')),
                            exposicao_diaria=Decimal(str(s_data.get('exposicao_diaria', '0') or '0')),
                        ))
                    except Exception as e:
                        erros.append(f"[{nome_final}] Erro ao processar snapshot: {e}")

                if snapshots_para_criar:
                    DailySnapshot.objects.bulk_create(snapshots_para_criar, ignore_conflicts=True)

                # Recalcula posições a partir das ordens restauradas
                if ordens_para_criar:
                    ativos_afetados = set(o.ativo for o in ordens_para_criar)
                    for ativo in ativos_afetados:
                        recalcular_posicao(nova_est, ativo)

            criadas += 1

        except Exception as e:
            erros.append(f"Erro ao restaurar estrutura '{est_data.get('nome', '?')}': {e}")

    return criadas, erros


def recalcular_todas_rolagens():
    """Recalcula os caches de spread para todas as rolagens cadastradas."""
    from .models import Rolagem
    rolagens = Rolagem.objects.all()
    for rolagem in rolagens:
        recalcular_rolagem(rolagem)
    return rolagens.count()


def get_performance_report(usuario):
    """
    Gera dados consolidados de performance para todas as estruturas de um usuário.
    """
    from collections import defaultdict
    from .models import DailySnapshot, Estrutura
    from datetime import datetime
    
    snapshots = DailySnapshot.objects.filter(
        estrutura__usuario=usuario
    ).order_by('data', 'estrutura_id')
    
    if not snapshots.exists():
        return None
        
    datas_distintas = sorted(list(set(s.data for s in snapshots)))
    ids_estruturas = list(Estrutura.objects.filter(usuario=usuario).values_list('id', flat=True))
    
    mapa_snapshots = defaultdict(dict)
    for s in snapshots:
        mapa_snapshots[s.data][s.estrutura_id] = {
            'valor': float(s.valor_total),
            'exposicao': float(s.exposicao_diaria)
        }
        
    equity_curve = {'datas': [], 'valores': [], 'exposicao': []}
    ultimos_valores = {eid: {'valor': 0.0, 'exposicao': 0.0} for eid in ids_estruturas}
    last_total_per_month = {}
    last_total_per_week = {}
    
    for d in datas_distintas:
        total_dia = 0.0
        exposicao_dia = 0.0
        for eid in ids_estruturas:
            if eid in mapa_snapshots[d]:
                ultimos_valores[eid] = mapa_snapshots[d][eid]
            total_dia += ultimos_valores[eid]['valor']
            exposicao_dia += ultimos_valores[eid]['exposicao']
        
        equity_curve['datas'].append(d.strftime('%d/%m/%Y'))
        equity_curve['valores'].append(total_dia)
        equity_curve['exposicao'].append(exposicao_dia)
        
        month_key = d.strftime('%Y-%m')
        year, week, _ = d.isocalendar()
        week_key = f"{year}-W{week:02d}"
        
        last_total_per_month[month_key] = total_dia
        last_total_per_week[week_key] = total_dia

    # Mensal
    sorted_months = sorted(last_total_per_month.keys())
    monthly = {'labels': [], 'values': []}
    prev = 0.0
    for m in sorted_months:
        val = last_total_per_month[m]
        dt = datetime.strptime(m, '%Y-%m')
        monthly['labels'].append(dt.strftime('%b/%y'))
        monthly['values'].append(round(val - prev, 2))
        prev = val

    # Semanal
    sorted_weeks = sorted(last_total_per_week.keys())
    weekly = {'labels': [], 'values': []}
    prev_w = 0.0
    for w in sorted_weeks:
        val = last_total_per_week[w]
        weekly['labels'].append(f"Sem {w.split('-W')[-1]}")
        weekly['values'].append(round(val - prev_w, 2))
        prev_w = val
        
    return {
        'equity_curve': equity_curve,
        'monthly': monthly,
        'weekly': weekly,
        'total_atual': equity_curve['valores'][-1],
        'exposicao_atual': equity_curve['exposicao'][-1]
    }
