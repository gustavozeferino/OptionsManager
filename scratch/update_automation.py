import os

with open('dadosb3/automation.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Make sure to import cache and time and math if not there
if 'from django.core.cache import cache' not in content:
    content = content.replace('import logging', 'import logging\nimport time\nimport math\nfrom django.core.cache import cache')

# Update consolidar_negocios
content = content.replace('def consolidar_negocios(min_date=None):', 'def consolidar_negocios(min_date=None, task_id=None):')
content = content.replace('''    if not dates_to_process:
        logger.info("Nenhuma data para consolidar.")
        return 0

    mapa_isin_por_ticker = dict(Instrumento.objects.values_list('ticker', 'isin'))
    total_processed = 0

    for dt in dates_to_process:''',
'''    if not dates_to_process:
        logger.info("Nenhuma data para consolidar.")
        if task_id:
            cache.set(f'task_{task_id}', 100, timeout=3600)
            cache.set(f'task_{task_id}_summary', "Nenhuma data para consolidar.", timeout=3600)
        return 0

    mapa_isin_por_ticker = dict(Instrumento.objects.values_list('ticker', 'isin'))
    total_processed = 0
    
    if task_id:
        start_time_task = time.time()
        cache.set(f'task_{task_id}_stats', {'processed': 0, 'total': len(dates_to_process), 'speed': 0, 'start_time': start_time_task, 'unit': 'dias'}, timeout=3600)

    for index, dt in enumerate(dates_to_process, 1):''')

# Now inject inside the loop of consolidar_negocios
content = content.replace('''            logger.error(f"Erro ao consolidar negocio diario para data {dt}: {e}")
            
    logger.info(f"Consolidacao de negocios concluida. {total_processed} registros.")
    return total_processed''',
'''            logger.error(f"Erro ao consolidar negocio diario para data {dt}: {e}")
            
        if task_id:
            elapsed = max(1, time.time() - start_time_task)
            cache.set(f'task_{task_id}_stats', {'processed': index, 'total': len(dates_to_process), 'speed': index / elapsed, 'start_time': start_time_task, 'unit': 'dias'}, timeout=3600)
            cache.set(f'task_{task_id}', min(99, math.floor((index / len(dates_to_process)) * 100)), timeout=3600)
            
    if task_id:
        cache.set(f'task_{task_id}', 100, timeout=3600)
        cache.set(f'task_{task_id}_summary', f"Consolidação concluída. {total_processed} registros processados em {len(dates_to_process)} dias.", timeout=3600)
        
    logger.info(f"Consolidacao de negocios concluida. {total_processed} registros.")
    return total_processed''')

# Update sincronizar_historico_preco
content = content.replace('def sincronizar_historico_preco(min_date=None):', 'def sincronizar_historico_preco(min_date=None, task_id=None):')
content = content.replace('''    if not dates_to_process:
        logger.info("Nenhuma data para sincronizar historico.")
        return 0

    total_processed = 0

    for dt in dates_to_process:''',
'''    if not dates_to_process:
        logger.info("Nenhuma data para sincronizar historico.")
        if task_id:
            cache.set(f'task_{task_id}', 100, timeout=3600)
            cache.set(f'task_{task_id}_summary', "Nenhuma data para sincronizar historico.", timeout=3600)
        return 0

    total_processed = 0
    
    if task_id:
        start_time_task = time.time()
        cache.set(f'task_{task_id}_stats', {'processed': 0, 'total': len(dates_to_process), 'speed': 0, 'start_time': start_time_task, 'unit': 'dias'}, timeout=3600)

    for index, dt in enumerate(dates_to_process, 1):''')

content = content.replace('''            logger.error(f"Erro ao sincronizar historico preco para data {dt}: {e}")
            
    logger.info(f"Sincronizacao de historico de preco concluida. {total_processed} atualizados.")
    return total_processed''',
'''            logger.error(f"Erro ao sincronizar historico preco para data {dt}: {e}")
            
        if task_id:
            elapsed = max(1, time.time() - start_time_task)
            cache.set(f'task_{task_id}_stats', {'processed': index, 'total': len(dates_to_process), 'speed': index / elapsed, 'start_time': start_time_task, 'unit': 'dias'}, timeout=3600)
            cache.set(f'task_{task_id}', min(99, math.floor((index / len(dates_to_process)) * 100)), timeout=3600)

    if task_id:
        cache.set(f'task_{task_id}', 100, timeout=3600)
        cache.set(f'task_{task_id}_summary', f"Sincronização concluída. {total_processed} registros atualizados em {len(dates_to_process)} dias.", timeout=3600)
            
    logger.info(f"Sincronizacao de historico de preco concluida. {total_processed} atualizados.")
    return total_processed''')


with open('dadosb3/automation.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("automation.py updated")
