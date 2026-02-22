"""
Management command para importar arquivos CSV da B3.
"""
from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _
from core.services import importar_csv_b3
import os


class Command(BaseCommand):
    help = 'Importa um arquivo CSV do Cadastro de Instrumentos da B3'

    def add_arguments(self, parser):
        parser.add_argument(
            'file_path',
            type=str,
            help='Caminho para o arquivo CSV da B3'
        )

    def handle(self, *args, **options):
        file_path = options['file_path']
        
        # Verifica se o arquivo existe
        if not os.path.exists(file_path):
            self.stdout.write(
                self.style.ERROR(f'Arquivo não encontrado: {file_path}')
            )
            return
        
        self.stdout.write(f'Processando arquivo: {file_path}')
        self.stdout.write('Filtrando apenas: BOVA11, PETR4, VALE3')
        
        # Processa o arquivo
        stats = importar_csv_b3(file_path)
        
        # Exibe os resultados
        self.stdout.write(self.style.SUCCESS('\n=== Resultado da Importação ==='))
        self.stdout.write(f'Total de linhas lidas: {stats["total_lidas"]}')
        self.stdout.write(f'Linhas filtradas (BOVA11, PETR4, VALE3): {stats["filtradas"]}')
        self.stdout.write(self.style.SUCCESS(f'Registros criados: {stats["criadas"]}'))
        self.stdout.write(self.style.SUCCESS(f'Registros atualizados: {stats["atualizadas"]}'))
        
        if stats['erros']:
            self.stdout.write(self.style.WARNING(f'\nErros encontrados: {len(stats["erros"])}'))
            for erro in stats['erros'][:10]:  # Mostra apenas os 10 primeiros erros
                self.stdout.write(
                    self.style.ERROR(f'  Linha {erro["linha"]} ({erro["ticker"]}): {erro["erro"]}')
                )
            if len(stats['erros']) > 10:
                self.stdout.write(
                    self.style.WARNING(f'  ... e mais {len(stats["erros"]) - 10} erros')
                )
        
        self.stdout.write(self.style.SUCCESS('\nImportação concluída!'))
