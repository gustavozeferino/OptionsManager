from django.db import transaction
from django.db.models import Sum
from .models import Estrutura, Ordem, PosicaoConsolidada, DailySnapshot
from core.models import HistoricoPreco, AtivoB3
from datetime import date, datetime
from decimal import Decimal
import io
import csv


def recalcular_posicao(estrutura, ativo):
    """
    Recalcula a posição consolidada (preço médio, qtd e pl realizado) de um ativo
    dentro de uma estrutura, baseando-se no histórico de ordens.
    """
    ordens = Ordem.objects.filter(estrutura=estrutura, ativo=ativo).order_by('data', 'criado_em')
    
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

    # Atualiza ou cria PosicaoConsolidada
    if qtd_atual == 0 and pl_realizado == 0 and not ordens.exists():
        PosicaoConsolidada.objects.filter(estrutura=estrutura, ativo=ativo).delete()
    else:
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
                st = estado[ordem.ativo.codigo_isin]
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
    
    with transaction.atomic():
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
                
                # Processamento dos valores
                data_obj = datetime.strptime(str(col_data).strip(), '%d/%m/%Y').date()
                ativo_str = str(col_ativo).strip().upper()
                quantidade = int(str(col_qtd).replace('.', '').strip())
                preco = Decimal(str(col_preco).replace('R$', '').replace('.', '').replace(',', '.').strip())
                
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
                    
                Ordem.objects.create(
                    estrutura=estrutura_padrao,
                    ativo=ativo_obj,
                    quantidade=quantidade,
                    preco=preco,
                    data=data_obj
                )
                sucesso += 1
                
            except Exception as e:
                erros.append(f"Linha {i}: Erro de formatação - {str(e)}")
                
                
    if sucesso > 0:
        recalcular_estrutura(estrutura_padrao)
        
    return sucesso, erros

def importar_ordens_profit(user, csv_file):
    print("\n" + "="*40)
    print("DEBUG: FUNCAO IMPORTAR_ORDENS_PROFIT INICIADA")
    print("="*40)
    
    # Lê os bytes puros primeiro
    raw_data = csv_file.read()
    
    # Tenta decodificar de forma resiliente
    try:
        content = raw_data.decode('utf-8')
        print("DEBUG: Decodificado com UTF-8")
    except UnicodeDecodeError:
        content = raw_data.decode('iso-8859-1')
        print("DEBUG: Decodificado com ISO-8859-1 (Latin-1)")

    lines = content.splitlines()
    print(f"DEBUG: Total de linhas no arquivo: {len(lines)}")
    
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
        print("DEBUG: ERRO - Cabecalho 'Ativo;Status' nao encontrado!")
        return 0, ["Cabecalho do Profit nao encontrado."]

    print(f"DEBUG: Cabecalho encontrado na linha {header_index + 1}")

    import io
    import csv
    from decimal import Decimal
    from datetime import datetime
    from django.db import transaction
    from django.utils.timezone import make_aware
    from trading.models import Estrutura, Ordem, AtivoB3

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
                
                # Preço e Qtd (Tratando formato PT-BR)
                preco = Decimal(row['Preço'].replace('.', '').replace(',', '.'))
                qtd = int(row['Qtd'].replace('.', ''))
                
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
                print(f"DEBUG: --> OK: Ordem adicionada")
            except AtivoB3.DoesNotExist:
                print(f"DEBUG: --> ERRO: Ativo {ativo_ticker} nao cadastrado")
                erros.append(f"Ativo {ativo_ticker} não cadastrado.")
            except Exception as e:
                print(f"DEBUG: --> ERRO: {str(e)}")
                erros.append(f"Linha {row_num}: {str(e)}")

        if ordens_para_criar:
            Ordem.objects.bulk_create(ordens_para_criar)
            print(f"DEBUG: {len(ordens_para_criar)} ordens salvas.")
            recalcular_estrutura(est)
            
    return len(ordens_para_criar), erros