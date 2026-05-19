import os
import re

with open('dadosb3/views.py', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Imports
c = c.replace('import re', 'import re\nimport tempfile\nimport time')
c = c.replace('from .services import ingest_cothist_file', 'from .services import ingest_cothist_file\nfrom .automation import rotinas_automaticas_pos_ingestao, consolidar_negocios, sincronizar_historico_preco\nfrom django.db import models')

# 2. Finally blocks
# ingest_cadastro
c = c.replace(
'''        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)

def ingest_negocios''',
'''        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)
    finally:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass

def ingest_negocios''')

# ingest_posicoes
c = c.replace(
'''        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)

def ingest_cothist_web''',
'''        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)
    finally:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass

def ingest_cothist_web''')

# ingest_cothist_web
c = c.replace(
'''        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)

@login_required''',
'''        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)
    finally:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass

@login_required''')

# 3. ingest_negocios min_date and rotinas
c = c.replace(
'''            cols = chunk.columns
            instances = []
            for _, row in chunk.iterrows():
                dt = parse_date(get_val(row, cols, ['data', 'negocio']))''',
'''            cols = chunk.columns
            instances = []
            for _, row in chunk.iterrows():
                dt = parse_date(get_val(row, cols, ['data', 'negocio']))
                if dt:
                    if 'min_date' not in locals() or min_date is None or dt < min_date:
                        min_date = dt''')

c = c.replace(
'''        logger.info(f"Sucesso ao processar arquivo de negócios: {filename}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Sucesso', descricao_falha='-')
        cache.set(f'task_{task_id}', 100, timeout=3600)
    except Exception as e:
        error_msg = str(e)
        full_traceback = traceback.format_exc()
        logger.error(f"Erro ao processar arquivo de negócios {filename}: {error_msg}\\n{full_traceback}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Erro', descricao_falha=error_msg)
        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)''',
'''        if 'min_date' in locals() and min_date:
            logger.info(f"Executando rotinas pos ingestao a partir de {min_date}")
            rotinas_automaticas_pos_ingestao(min_date)
            
        logger.info(f"Sucesso ao processar arquivo de negócios: {filename}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Sucesso', descricao_falha='-')
        cache.set(f'task_{task_id}', 100, timeout=3600)
    except Exception as e:
        error_msg = str(e)
        full_traceback = traceback.format_exc()
        logger.error(f"Erro ao processar arquivo de negócios {filename}: {error_msg}\\n{full_traceback}")
        LogProcessamento.objects.create(nome_arquivo=filename, status='Erro', descricao_falha=error_msg)
        cache.set(f'task_{task_id}_error', error_msg, timeout=3600)
    finally:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass''')

# For ingest_cothist_web, we also need rotinas
c = c.replace(
'''        count = ingest_cothist_file(file_path)
        
        summary = f"Importação de Cotação Histórica concluída. Registros processados: {count}"''',
'''        count = ingest_cothist_file(file_path)
        
        min_date = CotacaoHistorica.objects.order_by('dtpreg').last().dtpreg if CotacaoHistorica.objects.exists() else None
        if min_date:
            rotinas_automaticas_pos_ingestao(min_date)
        
        summary = f"Importação de Cotação Histórica concluída. Registros processados: {count}"''')

# 4. Modify upload_view to use tempfile
c = c.replace(
'''def upload_view(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        fs = FileSystemStorage()
        filename = fs.save(file.name, file)
        file_path = fs.path(filename)
        
        task_id = str(uuid.uuid4())
        cache.set(f'task_{task_id}', 0, timeout=3600)''',
'''def upload_view(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        
        fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(file.name)[1])
        with os.fdopen(fd, 'wb') as f:
            for chunk in file.chunks():
                f.write(chunk)
        
        filename = file.name
        file_path = temp_path
        
        task_id = str(uuid.uuid4())
        cache.set(f'task_{task_id}', 0, timeout=3600)
        cache.set(f'task_{task_id}_stats', {'processed': 0, 'total': 1, 'speed': 0, 'start_time': time.time()}, timeout=3600)''')

# 5. Modify cache.set inside loops to include stats
c = re.sub(
    r'(processed_lines \+= len\(chunk\)\s+cache\.set\(f\'task_\{task_id\}\', min\(\d+, math\.floor\(\(processed_lines / total_lines\) \* 100\)\), timeout=3600\))',
    r"""processed_lines += len(chunk)
            stats = cache.get(f'task_{task_id}_stats') or {'start_time': time.time()}
            elapsed = max(1, time.time() - stats['start_time'])
            cache.set(f'task_{task_id}_stats', {'processed': processed_lines, 'total': total_lines, 'speed': processed_lines / elapsed, 'start_time': stats['start_time']}, timeout=3600)
            cache.set(f'task_{task_id}', min(99, math.floor((processed_lines / total_lines) * 100)), timeout=3600)""",
    c
)

# 6. Modify upload_progress to return stats
c = c.replace(
'''def upload_progress(request, task_id):
    progress = cache.get(f'task_{task_id}', 0)
    error = cache.get(f'task_{task_id}_error', None)
    summary = cache.get(f'task_{task_id}_summary', None)
    if error:
        return JsonResponse({'progress': progress, 'error': error})
    return JsonResponse({'progress': progress, 'summary': summary})''',
'''def upload_progress(request, task_id):
    progress = cache.get(f'task_{task_id}', 0)
    error = cache.get(f'task_{task_id}_error', None)
    summary = cache.get(f'task_{task_id}_summary', None)
    stats = cache.get(f'task_{task_id}_stats', {})
    if error:
        return JsonResponse({'progress': progress, 'error': error, 'stats': stats})
    return JsonResponse({'progress': progress, 'summary': summary, 'stats': stats})''')

# 7. Append admin views
c += '''

@login_required
@user_passes_test(is_admin)
def admin_estatisticas(request):
    try:
        last_date = NegocioDiario.objects.aggregate(models.Max('data_pregao'))['data_pregao__max']
        return JsonResponse({'status': 'success', 'last_date': last_date.strftime('%d/%m/%Y') if last_date else '-'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
@user_passes_test(is_admin)
def admin_consolidar(request):
    if request.method == 'POST':
        try:
            processed = consolidar_negocios()
            return JsonResponse({'status': 'success', 'message': f'Consolidação concluída. {processed} registros processados.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'})

@login_required
@user_passes_test(is_admin)
def admin_sincronizar(request):
    if request.method == 'POST':
        try:
            processed = sincronizar_historico_preco()
            return JsonResponse({'status': 'success', 'message': f'Sincronização concluída. {processed} registros atualizados.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'})
'''

with open('dadosb3/views.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('views.py successfully modified.')
