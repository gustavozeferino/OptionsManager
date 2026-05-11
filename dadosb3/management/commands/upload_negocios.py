import os
import time
import uuid
from django.core.management.base import BaseCommand
from django.core.cache import cache
from dadosb3.views import ingest_negocios

class Command(BaseCommand):
    help = 'Faz o upload do arquivo de negócios diários'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Caminho para o arquivo CSV')

    def handle(self, *args, **options):
        file_path = options['file_path']
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f'Arquivo não encontrado: {file_path}'))
            return

        filename = os.path.basename(file_path)
        task_id = str(uuid.uuid4())
        
        self.stdout.write(f'Iniciando processamento de {filename}...')
        
        import threading
        thread = threading.Thread(target=ingest_negocios, args=(file_path, task_id, filename))
        thread.start()
        
        last_progress = -1
        while thread.is_alive():
            progress = cache.get(f'task_{task_id}', 0)
            if progress != last_progress:
                self.stdout.write(f'Progresso: {progress}%')
                last_progress = progress
            
            error = cache.get(f'task_{task_id}_error')
            if error:
                self.stdout.write(self.style.ERROR(f'Erro: {error}'))
                return
                
            time.sleep(1)
        
        # Final check
        progress = cache.get(f'task_{task_id}', 0)
        self.stdout.write(f'Progresso: {progress}%')
        
        self.stdout.write(self.style.SUCCESS('Concluído!'))
