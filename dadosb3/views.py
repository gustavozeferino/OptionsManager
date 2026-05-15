import pandas as pd
import threading
import uuid
import math
import logging
import traceback
import os
import re
from decimal import Decimal
from datetime import datetime
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.conf import settings
import unicodedata
from .models import Instrumento, BoletimNegocioDiario, CotacaoHistorica, NegocioDiario, PosicaoAberta, LogProcessamento, InstrumentoAtualizacao
from .services import ingest_cothist_file

def slugify(text):
    return "".join(c for c in unicodedata.normalize('NFD', str(text)) if unicodedata.category(c) != 'Mn').lower().strip()

def get_val(row, columns, terms):
    for i, col in enumerate(columns):
        c = slugify(col)
        if all(t in c for t in terms):
            return row.iloc[i]
    return None

def are_values_equal(v1, v2):
    """
    Compara dois valores seguindo a regra:
    Para números, ignora casas decimais e analisa somente o valor absoluto.
    Para outros tipos, usa comparação padrão.
    """
    if v1 == v2:
        return True
    
    # Tratar casos de None ou strings vazias como equivalentes dependendo do contexto, 
    # mas aqui vamos ser simples: se ambos forem "vazios", são iguais.
    def is_empty(v):
        return v is None or pd.isna(v) or str(v).strip() in ['', '-', 'nan']
        
    if is_empty(v1) and is_empty(v2):
        return True
    if is_empty(v1) != is_empty(v2):
        return False

    try:
        # Tenta comparação numérica conforme pedido: abs(int(float))
        # Substitui vírgula por ponto para garantir conversão de strings BR
        s1 = str(v1).replace(',', '.')
        s2 = str(v2).replace(',', '.')
        
        n1 = abs(int(float(s1)))
        n2 = abs(int(float(s2)))
        return n1 == n2
    except:
        pass
    
    # Fallback para string comparison limpa
    return str(v1).strip() == str(v2).strip()

# Configuração de logging para o módulo dadosb3
LOG_DIR = os.path.join(settings.BASE_DIR, 'logs')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logger = logging.getLogger('dadosb3')
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    handler = logging.FileHandler(os.path.join(LOG_DIR, 'dadosb3_errors.log'), encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def is_admin(user):
    return user.is_superuser

def parse_decimal(val):
    if pd.isna(val) or val == '' or val == '-':
        return None
    val = str(val).replace('.', '').replace(',', '.')
    try:
        return Decimal(val)
    except:
        return None

def parse_date(val):
    if pd.isna(val) or val == '' or val == '-' or val == '31/12/9999':
        return None
    try:
        return datetime.strptime(str(val), '%d/%m/%Y').date()
    except:
        return None

def parse_int(val):
    if pd.isna(val) or val == '' or val == '-':
        return None
    try:
        val = str(val).strip()
        # Se termina com .0 ou .00 (comum em arquivos processados), remove
        if re.search(r'[.,]0{1,2}$', val):
            val = re.sub(r'[.,]0{1,2}$', '', val)
        # Remove pontos de milhar
        val = val.replace('.', '')
        return int(val)
    except:
        return None

def count_lines(file_path):
    with open(file_path, 'rb') as f:
        return sum(1 for _ in f) - 4

def ingest_cadastro(file_path, task_id, filename):
    try:
        total_lines = count_lines(file_path)
        if total_lines <= 0: total_lines = 1
        chunksize = 500
        processed_lines = 0
        
        # Detecção dinâmica da linha de cabeçalho
        skip = 0
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f):
                    if i > 10: break
                    if 'Instrumento' in line and 'ISIN' in line:
                        skip = i
                        break
        except: pass
        
        # Extração da data pelo nome do arquivo (dd-mm-aaaa)
        date_ref = None
        match = re.search(r'(\d{2})-(\d{2})-(\d{4})', filename)
        if match:
            try:
                date_ref = datetime.strptime(match.group(0), '%d-%m-%Y').date()
            except:
                pass

        summary = {"novos": 0, "alterados": 0, "detalhes": []}

        for chunk in pd.read_csv(file_path, sep=';', skiprows=skip, encoding='utf-8-sig', chunksize=chunksize, dtype=str):
            cols = chunk.columns
            for _, row in chunk.iterrows():
                ticker = str(get_val(row, cols, ['instrumento', 'financeiro']) or '').strip()
                isin = str(get_val(row, cols, ['codigo', 'isin']) or '').strip()
                
                if not isin or isin == 'nan' or isin == '':
                    continue
                
                if not ticker or ticker == 'nan':
                    continue

                isin = isin[:12]
                
                # Dados do arquivo (sem o campo data)
                data_row = {
                    'ticker': ticker,
                    'ativo_objeto': str(get_val(row, cols, ['ativo']) or '').strip()[:100],
                    'descricao': str(get_val(row, cols, ['descricao', 'ativo']) or '').strip(),
                    'segmento': str(get_val(row, cols, ['segmento']) or '').strip()[:100],
                    'mercado': str(get_val(row, cols, ['mercado']) or '').strip()[:100],
                    'categoria': str(get_val(row, cols, ['categoria']) or '').strip()[:100],
                    'data_expiracao': parse_date(get_val(row, cols, ['data', 'expiracao'])),
                    'data_inicio_negocio': parse_date(get_val(row, cols, ['data', 'inicio', 'negocio'])),
                    'data_fim_negocio': parse_date(get_val(row, cols, ['data', 'fim', 'negocio'])),
                    'cfi': str(get_val(row, cols, ['codigo', 'cfi']) or '').strip()[:100],
                    'tipo_opcao': str(get_val(row, cols, ['tipo', 'opcao']) or '').strip()[:10],
                    'lote_alocacao': parse_int(get_val(row, cols, ['tamanho', 'lote', 'alocacao'])),
                    'moeda': str(get_val(row, cols, ['moeda', 'negociada']) or '').strip()[:50],
                    'tipo_entrega': str(get_val(row, cols, ['tipo', 'entrega']) or '').strip()[:50],
                    'strike': parse_decimal(get_val(row, cols, ['preco', 'exercicio'])),
                    'estilo_opcao': str(get_val(row, cols, ['estilo', 'opcao']) or '').strip()[:10],
                    'ind_premio_antecipado': (str(get_val(row, cols, ['indicador', 'premio', 'antecipado']) or '').strip().lower() in ['s', 'sim', 'true', '1']),
                    'id_distribuicao': str(get_val(row, cols, ['identificador', 'distribuicao']) or '').strip()[:50],
                    'fator_preco': parse_int(get_val(row, cols, ['fator', 'preco'])),
                    'dias_liquidacao': parse_int(get_val(row, cols, ['dias', 'liquidacao'])),
                    'tipo_serie': str(get_val(row, cols, ['tipo', 'serie']) or '').strip()[:50],
                    'ind_protecao': (str(get_val(row, cols, ['indicador', 'protecao']) or '').strip().lower() in ['s', 'sim', 'true', '1']),
                    'ind_exercicio_automatico': (str(get_val(row, cols, ['exercicio', 'automatico']) or '').strip().lower() in ['s', 'sim', 'true', '1']),
                    'especificacao': str(get_val(row, cols, ['codigo', 'especificacao']) or '').strip()[:100],
                    'nome_instituicao': str(get_val(row, cols, ['nome', 'instituicao']) or '').strip()[:255],
                    'data_evento_corp': parse_date(get_val(row, cols, ['data', 'inicio', 'evento', 'corporativo'])),
                    'tipo_custodia': str(get_val(row, cols, ['tipo', 'tratamento', 'custodia']) or '').strip()[:100],
                    'capital_social': parse_decimal(get_val(row, cols, ['capital', 'social'])),
                    'nivel_governanca': str(get_val(row, cols, ['nivel', 'governanca', 'corporativa']) or '').strip()[:100],
                }

                obj, created = Instrumento.objects.get_or_create(isin=isin, defaults={**data_row, 'data': date_ref})
                
                if created:
                    summary["novos"] += 1
                    summary["detalhes"].append({"tipo": "novo", "ticker": ticker, "isin": isin})
                else:
                    if date_ref and obj.data and date_ref <= obj.data:
                        continue
                    
                    if not date_ref and obj.data:
                        continue
                    
                    changed = False
                    changes = []
                    for field, value in data_row.items():
                        old_val = getattr(obj, field)
                        if not are_values_equal(old_val, value):
                            InstrumentoAtualizacao.objects.create(
                                data_arquivo=date_ref,
                                isin=isin,
                                coluna=field,
                                valor_antigo=str(old_val),
                                valor_novo=str(value)
                            )
                            setattr(obj, field, value)
                            changed = True
                            changes.append({"campo": field, "anterior": str(old_val), "novo": str(value)})
                    
                    if changed:
                        obj.data = date_ref
                        obj.save()
                        summary["alterados"] += 1
                        summary["detalhes"].append({"tipo": "alterado", "ticker": ticker, "isin": isin, "mudancas": changes})

            processed_lines += len(chunk)
            cache.set(f'task_{task_id}', min(99, math.floor((processed_lines / total_lines) * 100)), timeout=3600)
            
        # Formata para Web (HTML)
        html_parts = [f"<div class='space-y-4'><p class='text-lg font-bold'>Resumo do Upload: {summary['novos']} novos, {summary['alterados']} alterados.</p>"]
        for d in summary["detalhes"]:
            if d["tipo"] == "novo":
                html_parts.append(f"<p class='text-green-600 font-bold'>Novo: {d['ticker']} ({d['isin']})</p>")
            else:
                rows = "".join([f"<tr><td class='border px-2 py-1'>{m['campo']}</td><td class='border px-2 py-1'>{m['anterior']}</td><td class='border px-2 py-1'>{m['novo']}</td></tr>" for m in d["mudancas"]])
                html_parts.append(f"<div class='mb-4'><p class='font-bold text-blue-600'>Alterado: {d['ticker']} ({d['isin']})</p><table class='table-auto border-collapse w-full text-xs'><thead><tr class='bg-gray-200'><th class='border px-2 py-1'>Campo</th><th class='border px-2 py-1'>Anterior</th><th class='border px-2 py-1'>Novo</th></tr></thead><tbody>{rows}</tbody></table></div>")
        html_parts.append("</div>")
        cache.set(f'task_{task_id}_summary', "".join(html_parts), timeout=3600)
        
        # Formata para Console (Plain Text)
        txt_parts = [f"Resumo do Upload: {summary['novos']} novos, {summary['alterados']} alterados."]
        for d in summary["detalhes"]:
            if d["tipo"] == "novo":
                txt_parts.append(f"Novo: {d['ticker']} ({d['isin']})")
            else:
                txt_parts.append(f"Alterado: {d['ticker']} ({d['isin']})")
                for m in d["mudancas"]:
                    txt_parts.append(f"  - {m['campo']}: {m['anterior']} -> {m['novo']}")
        cache.set(f'task_{task_id}_summary_txt', "\n".join(txt_parts), timeout=3600)

        logger.info(f"Sucesso ao processar arquivo de cadastro: {filename}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Sucesso', descricao_falha='-')
        cache.set(f'task_{task_id}', 100, timeout=3600)
    except Exception as e:
        error_msg = str(e)
        full_traceback = traceback.format_exc()
        logger.error(f"Erro ao processar arquivo de cadastro {filename}: {error_msg}\n{full_traceback}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Erro', descricao_falha=error_msg)
        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)


def ingest_negocios(file_path, task_id, filename):
    try:
        total_lines = count_lines(file_path)
        if total_lines <= 0: total_lines = 1
        chunksize = 1000
        processed_lines = 0
        
        # Detecção dinâmica da linha de cabeçalho
        skip = 0
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f):
                    if i > 10: break
                    if ('Instrumento' in line and 'ISIN' in line) or ('Data' in line and 'negocio' in line.lower()):
                        skip = i
                        break
        except: pass
        
        for chunk in pd.read_csv(file_path, sep=';', skiprows=skip, encoding='utf-8-sig', chunksize=chunksize, dtype=str):
            cols = chunk.columns
            instances = []
            for _, row in chunk.iterrows():
                dt = parse_date(get_val(row, cols, ['data', 'negocio']))
                ticker = str(get_val(row, cols, ['instrumento', 'financeiro']) or '').strip()
                isin = str(get_val(row, cols, ['codigo', 'isin']) or '').strip()
                
                # Validação: isin deve estar preenchido
                if not isin or isin == 'nan' or isin == '':
                    continue
                
                if not dt or not ticker or ticker == 'nan': continue
                
                vol = parse_decimal(get_val(row, cols, ['volume', 'financeiro']))
                qtd_cont = parse_int(get_val(row, cols, ['quantidade', 'contrato']))
                vwap_val = None
                if vol and qtd_cont and qtd_cont > 0:
                    vwap_val = vol / Decimal(qtd_cont)

                instances.append(BoletimNegocioDiario(
                    data_pregao=dt,
                    ticker=ticker,
                    isin=isin[:12],
                    segmento=str(get_val(row, cols, ['segmento']) or '').strip()[:100],
                    preco_abertura=parse_decimal(get_val(row, cols, ['preco', 'abertura'])),
                    preco_minimo=parse_decimal(get_val(row, cols, ['preco', 'minimo'])),
                    preco_maximo=parse_decimal(get_val(row, cols, ['preco', 'maximo'])),
                    preco_medio=parse_decimal(get_val(row, cols, ['preco', 'medio'])),
                    preco_fechamento=parse_decimal(get_val(row, cols, ['preco', 'fechamento'])),
                    oscilacao=parse_decimal(get_val(row, cols, ['oscilacao'])),
                    ajuste=parse_decimal(get_val(row, cols, ['ajuste'])),
                    ajuste_referencia=parse_decimal(get_val(row, cols, ['ajuste', 'referencia'])),
                    ajuste_anterior=parse_decimal(get_val(row, cols, ['ajuste', 'anterior'])),
                    preco_referencia=parse_decimal(get_val(row, cols, ['preco', 'referencia'])),
                    variacao=parse_decimal(get_val(row, cols, ['variacao'])),
                    valor_ajuste_contrato=parse_decimal(get_val(row, cols, ['valor', 'ajuste', 'contrato'])),
                    bid=parse_decimal(get_val(row, cols, ['ultima', 'oferta', 'compra'])),
                    ask=parse_decimal(get_val(row, cols, ['ultima', 'oferta', 'venda'])),
                    qtd_negocios=parse_int(get_val(row, cols, ['quantidade', 'negocio'])),
                    qtd_contratos=qtd_cont,
                    volume_financeiro=vol,
                    vwap=vwap_val,
                ))
            if instances:
                BoletimNegocioDiario.objects.bulk_create(instances, ignore_conflicts=True)
            
            processed_lines += len(chunk)
            cache.set(f'task_{task_id}', min(100, math.floor((processed_lines / total_lines) * 100)), timeout=3600)
            
        logger.info(f"Sucesso ao processar arquivo de negócios: {filename}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Sucesso', descricao_falha='-')
        cache.set(f'task_{task_id}', 100, timeout=3600)
    except Exception as e:
        error_msg = str(e)
        full_traceback = traceback.format_exc()
        logger.error(f"Erro ao processar arquivo de negócios {filename}: {error_msg}\n{full_traceback}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Erro', descricao_falha=error_msg)
        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)

def ingest_posicoes(file_path, task_id, filename):
    try:
        total_lines = count_lines(file_path)
        if total_lines <= 0: total_lines = 1
        chunksize = 1000
        processed_lines = 0
        
        # Extração da data pelo nome do arquivo (dd-mm-aaaa)
        date_ref = None
        match = re.search(r'(\d{2})-(\d{2})-(\d{4})', filename)
        if match:
            try:
                date_ref = datetime.strptime(match.group(0), '%d-%m-%Y').date()
            except:
                pass

        # Detecção dinâmica da linha de cabeçalho
        skip = 0
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for i, line in enumerate(f):
                    if i > 10: break
                    if 'Instrumento' in line and 'ISIN' in line:
                        skip = i
                        break
        except: pass
        
        for chunk in pd.read_csv(file_path, sep=';', skiprows=skip, encoding='utf-8-sig', chunksize=chunksize, dtype=str):
            cols = chunk.columns
            instances = []
            for _, row in chunk.iterrows():
                ticker = str(get_val(row, cols, ['instrumento', 'financeiro']) or '').strip()
                isin = str(get_val(row, cols, ['codigo', 'isin']) or '').strip()
                
                # Validação: isin deve estar preenchido
                if not isin or isin == 'nan' or isin == '':
                    continue
                
                if not ticker or ticker == 'nan':
                    continue
                
                instances.append(PosicaoAberta(
                    data=date_ref,
                    ticker=ticker,
                    isin=isin[:12],
                    ativo_objeto=str(get_val(row, cols, ['ativo']) or '').strip()[:100],
                    codigo_expiracao=str(get_val(row, cols, ['codigo', 'expiracao']) or '').strip()[:100],
                    segmento=str(get_val(row, cols, ['segmento']) or '').strip()[:100],
                    contratos_abertos=parse_int(get_val(row, cols, ['contratos', 'aberto'])),
                    variacao_abertos=parse_int(get_val(row, cols, ['variacao', 'contratos', 'aberto'])),
                    id_distribuicao=str(get_val(row, cols, ['identificador', 'distribuicao']) or '').strip()[:50],
                    qtd_coberta=parse_int(get_val(row, cols, ['quantidade', 'coberta'])),
                    posicoes_bloqueadas=parse_int(get_val(row, cols, ['total', 'posicoes', 'bloqueadas'])),
                    qtd_descoberta=parse_int(get_val(row, cols, ['quantidade', 'descoberta'])),
                    total_posicoes=parse_int(get_val(row, cols, ['total', 'posicoes'])),
                    qtd_tomadores=parse_int(get_val(row, cols, ['quantidade', 'tomadores'])),
                    qtd_doadores=parse_int(get_val(row, cols, ['quantidade', 'doadores'])),
                    qtd_atual=parse_int(get_val(row, cols, ['quantidade', 'atual'])),
                    contratos_travados=parse_int(get_val(row, cols, ['contratos', 'travados'])),
                    contratos_transferidos=parse_int(get_val(row, cols, ['contratos', 'baixados', 'transferencia'])),
                    preco_termo=parse_decimal(get_val(row, cols, ['preco', 'termo'])),
                ))
            if instances:
                PosicaoAberta.objects.bulk_create(instances, ignore_conflicts=True)
            
            processed_lines += len(chunk)
            cache.set(f'task_{task_id}', min(100, math.floor((processed_lines / total_lines) * 100)), timeout=3600)
            
        logger.info(f"Sucesso ao processar arquivo de posições: {filename}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Sucesso', descricao_falha='-')
        cache.set(f'task_{task_id}', 100, timeout=3600)
    except Exception as e:
        error_msg = str(e)
        full_traceback = traceback.format_exc()
        logger.error(f"Erro ao processar arquivo de posições {filename}: {error_msg}\n{full_traceback}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Erro', descricao_falha=error_msg)
        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)

def ingest_cothist_web(file_path, task_id, filename):
    try:
        count = ingest_cothist_file(file_path)
        
        summary = f"Importação de Cotação Histórica concluída. Registros processados: {count}"
        cache.set(f'task_{task_id}_summary', summary, timeout=3600)
        cache.set(f'task_{task_id}_summary_txt', summary, timeout=3600)
        
        logger.info(f"Sucesso ao processar arquivo COTAHIST: {filename}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Sucesso', descricao_falha='-')
        cache.set(f'task_{task_id}', 100, timeout=3600)
    except Exception as e:
        error_msg = str(e)
        full_traceback = traceback.format_exc()
        logger.error(f"Erro ao processar arquivo COTAHIST {filename}: {error_msg}\n{full_traceback}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Erro', descricao_falha=error_msg)
        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)

@login_required
@user_passes_test(is_admin)
def upload_view(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        fs = FileSystemStorage()
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)
        
        task_id = str(uuid.uuid4())
        cache.set(f'task_{task_id}', 0, timeout=3600)
        
        file_type = request.POST.get('file_type')
        if file_type == 'cadastro':
            target_func = ingest_cadastro
        elif file_type == 'negocios':
            target_func = ingest_negocios
        elif file_type == 'posicoes':
            target_func = ingest_posicoes
        elif file_type == 'cotacao_historica':
            target_func = ingest_cothist_web
        else:
            target_func = None
            
        if target_func:
            thread = threading.Thread(target=target_func, args=(file_path, task_id, filename))
            thread.daemon = True
            thread.start()
            
        return JsonResponse({'task_id': task_id})
    return render(request, 'dadosb3/upload.html')

@login_required
@user_passes_test(is_admin)
def upload_progress(request, task_id):
    progress = cache.get(f'task_{task_id}', 0)
    error = cache.get(f'task_{task_id}_error', None)
    summary = cache.get(f'task_{task_id}_summary', None)
    if error:
        return JsonResponse({'progress': progress, 'error': error})
    return JsonResponse({'progress': progress, 'summary': summary})

@login_required
@user_passes_test(is_admin)
def dashboard_view(request):
    segmentos = Instrumento.objects.values_list('segmento', flat=True).distinct().exclude(segmento='').order_by('segmento')
    return render(request, 'dadosb3/dashboard.html', {'segmentos': segmentos})

@login_required
@user_passes_test(is_admin)
def get_tickers(request):
    segmento = request.GET.get('segmento')
    tickers = Instrumento.objects.filter(segmento=segmento).values_list('ticker', flat=True).distinct().order_by('ticker')
    return JsonResponse({'tickers': list(tickers)})

@login_required
@user_passes_test(is_admin)
def get_chart_data(request):
    ticker = request.GET.get('ticker')
    negocios = NegocioDiario.objects.filter(ticker=ticker).order_by('data_pregao')
    
    data = []
    for n in negocios:
        if n.preco_abertura and n.preco_fechamento and n.preco_minimo and n.preco_maximo:
            data.append({
                'data': n.data_pregao.strftime('%Y-%m-%d'),
                'abertura': float(n.preco_abertura),
                'fechamento': float(n.preco_fechamento),
                'minimo': float(n.preco_minimo),
                'maximo': float(n.preco_maximo),
                'volume': float(n.volume_financeiro) if n.volume_financeiro else 0
            })
            
    return JsonResponse({'data': data})
