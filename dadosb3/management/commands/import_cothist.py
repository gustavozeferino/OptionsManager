import os
from django.core.management.base import BaseCommand
from dadosb3.services import ingest_cothist_file

class Command(BaseCommand):
    help = 'Importa arquivo COTAHIST da B3 (TXT/ZIP)'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, help='Caminho do arquivo TXT ou ZIP', required=True)

    def handle(self, *args, **options):
        file_path = options['file']
        
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f'Arquivo não encontrado: {file_path}'))
            return

        self.stdout.write(f'Iniciando importação de {file_path}...')
        count = ingest_cothist_file(file_path)
        self.stdout.write(self.style.SUCCESS(f'Importação concluída. Registros processados: {count}'))
