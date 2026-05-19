import os

with open('dadosb3/views.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_consolidar = '''@login_required
@user_passes_test(is_admin)
def admin_consolidar(request):
    if request.method == 'POST':
        try:
            processed = consolidar_negocios()
            return JsonResponse({'status': 'success', 'message': f'Consolidação concluída. {processed} registros processados.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'})'''

new_consolidar = '''@login_required
@user_passes_test(is_admin)
def admin_consolidar(request):
    if request.method == 'POST':
        try:
            data_inicio_str = request.POST.get('data_inicio')
            if data_inicio_str == 'ALL':
                min_date = None
            else:
                min_date = datetime.strptime(data_inicio_str, '%Y-%m-%d').date() if data_inicio_str else None
                
            task_id = str(uuid.uuid4())
            cache.set(f'task_{task_id}', 0, timeout=3600)
            cache.set(f'task_{task_id}_stats', {'processed': 0, 'total': 1, 'speed': 0, 'start_time': time.time(), 'unit': 'dias'}, timeout=3600)
            
            def run_task():
                try:
                    consolidar_negocios(min_date=min_date, task_id=task_id)
                except Exception as e:
                    logger.error(f"Erro em admin_consolidar thread: {e}\\n{traceback.format_exc()}")
                    cache.set(f'task_{task_id}_error', str(e), timeout=3600)
            
            thread = threading.Thread(target=run_task)
            thread.start()
            
            return JsonResponse({'status': 'success', 'task_id': task_id})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'})'''

content = content.replace(old_consolidar, new_consolidar)

old_sincronizar = '''@login_required
@user_passes_test(is_admin)
def admin_sincronizar(request):
    if request.method == 'POST':
        try:
            processed = sincronizar_historico_preco()
            return JsonResponse({'status': 'success', 'message': f'Sincronização concluída. {processed} registros atualizados.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'})'''

new_sincronizar = '''@login_required
@user_passes_test(is_admin)
def admin_sincronizar(request):
    if request.method == 'POST':
        try:
            data_inicio_str = request.POST.get('data_inicio')
            if data_inicio_str == 'ALL':
                min_date = None
            else:
                min_date = datetime.strptime(data_inicio_str, '%Y-%m-%d').date() if data_inicio_str else None
                
            task_id = str(uuid.uuid4())
            cache.set(f'task_{task_id}', 0, timeout=3600)
            cache.set(f'task_{task_id}_stats', {'processed': 0, 'total': 1, 'speed': 0, 'start_time': time.time(), 'unit': 'dias'}, timeout=3600)
            
            def run_task():
                try:
                    sincronizar_historico_preco(min_date=min_date, task_id=task_id)
                except Exception as e:
                    logger.error(f"Erro em admin_sincronizar thread: {e}\\n{traceback.format_exc()}")
                    cache.set(f'task_{task_id}_error', str(e), timeout=3600)
            
            thread = threading.Thread(target=run_task)
            thread.start()
            
            return JsonResponse({'status': 'success', 'task_id': task_id})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'})'''

content = content.replace(old_sincronizar, new_sincronizar)

with open('dadosb3/views.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("views.py updated")
