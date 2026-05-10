import pandas as pd
import threading
import uuid
import math
import logging
import traceback
import os
from decimal import Decimal
from datetime import datetime
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.conf import settings
import unicodedata
from .models import Instrumento, NegocioDiario, PosicaoAberta, LogProcessamento

def slugify(text):
    return "".join(c for c in unicodedata.normalize('NFD', str(text)) if unicodedata.category(c) != 'Mn').lower().strip()

def get_val(row, columns, terms):
    for i, col in enumerate(columns):
        c = slugify(col)
        if all(t in c for t in terms):
            return row.iloc[i]
    return None

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
        val = str(val).replace('.', '')
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
        chunksize = 1000
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
        
        for chunk in pd.read_csv(file_path, sep=';', skiprows=skip, encoding='utf-8-sig', chunksize=chunksize, dtype=str):
            cols = chunk.columns
            instances = []
            for _, row in chunk.iterrows():
                ticker = str(get_val(row, cols, ['instrumento', 'financeiro']) or '').strip()
                if not ticker or ticker == 'nan': continue
                
                instances.append(Instrumento(
                    ticker=ticker,
                    ativo_objeto=str(get_val(row, cols, ['ativo']) or '').strip()[:100],
                    descricao=str(get_val(row, cols, ['descricao', 'ativo']) or '').strip()[:255],
                    segmento=str(get_val(row, cols, ['segmento']) or '').strip()[:100],
                    mercado=str(get_val(row, cols, ['mercado']) or '').strip()[:100],
                    categoria=str(get_val(row, cols, ['categoria']) or '').strip()[:100],
                    data_expiracao=parse_date(get_val(row, cols, ['data', 'expiracao'])),
                    data_inicio_negocio=parse_date(get_val(row, cols, ['data', 'inicio', 'negocio'])),
                    isin=str(get_val(row, cols, ['codigo', 'isin']) or '').strip()[:100],
                    strike=parse_decimal(get_val(row, cols, ['preco', 'exercicio'])),
                    estilo_opcao=str(get_val(row, cols, ['estilo', 'opcao']) or '').strip()[:100],
                    nome_instituicao=str(get_val(row, cols, ['nome', 'instituicao']) or '').strip()[:255],
                ))
            if instances:
                Instrumento.objects.bulk_create(instances, ignore_conflicts=True)
            
            processed_lines += len(chunk)
            cache.set(f'task_{task_id}', min(100, math.floor((processed_lines / total_lines) * 100)), timeout=3600)
            
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
                if not dt or not ticker or not isin or ticker == 'nan': continue
                
                instances.append(NegocioDiario(
                    data_pregao=dt,
                    ticker=ticker,
                    isin=isin,
                    preco_abertura=parse_decimal(get_val(row, cols, ['preco', 'abertura'])),
                    preco_minimo=parse_decimal(get_val(row, cols, ['preco', 'minimo'])),
                    preco_maximo=parse_decimal(get_val(row, cols, ['preco', 'maximo'])),
                    preco_medio=parse_decimal(get_val(row, cols, ['preco', 'medio'])),
                    preco_fechamento=parse_decimal(get_val(row, cols, ['preco', 'fechamento'])),
                    qtd_negocios=parse_int(get_val(row, cols, ['quantidade', 'negocio'])),
                    volume_financeiro=parse_decimal(get_val(row, cols, ['volume', 'financeiro'])),
                ))
            if instances:
                NegocioDiario.objects.bulk_create(instances, ignore_conflicts=True)
            
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
                if not ticker or not isin or ticker == 'nan': continue
                
                instances.append(PosicaoAberta(
                    ticker=ticker,
                    isin=isin,
                    codigo_expiracao=str(get_val(row, cols, ['codigo', 'expiracao']) or '').strip()[:100],
                    contratos_abertos=parse_int(get_val(row, cols, ['contratos', 'aberto'])),
                    qtd_coberta=parse_int(get_val(row, cols, ['quantidade', 'coberta'])),
                    qtd_descoberta=parse_int(get_val(row, cols, ['quantidade', 'descoberta'])),
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
    if error:
        return JsonResponse({'progress': progress, 'error': error})
    return JsonResponse({'progress': progress})

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
