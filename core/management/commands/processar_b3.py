"""
Management command para processar arquivos CSV da B3.
"""
from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _
from core.utils import processar_cadastro_b3
import os


class Command(BaseCommand):
    help = 'Processa um arquivo CSV da B3 e importa os dados para o modelo AtivoB3'

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
        
        # Processa o arquivo
        stats = processar_cadastro_b3(file_path)
        
        # Exibe os resultados
        self.stdout.write(self.style.SUCCESS('\n=== Resultado do Processamento ==='))
        self.stdout.write(f'Total de linhas lidas: {stats["total_lidas"]}')
        self.stdout.write(f'Linhas filtradas (BOVA11, PETR4, VALE3): {stats["filtradas"]}')
        self.stdout.write(self.style.SUCCESS(f'Registros criados: {stats["criadas"]}'))
        self.stdout.write(self.style.SUCCESS(f'Registros atualizados: {stats["atualizadas"]}'))
        
        if stats['erros']:
            self.stdout.write(self.style.WARNING(f'\nErros encontrados: {len(stats["erros"])}'))
            for erro in stats['erros'][:10]:  # Mostra apenas os 10 primeiros erros
                self.stdout.write(
                    self.style.ERROR(f'  Linha {erro["linha"]} ({erro["ativo"]}): {erro["erro"]}')
                )
            if len(stats['erros']) > 10:
                self.stdout.write(
                    self.style.WARNING(f'  ... e mais {len(stats["erros"]) - 10} erros')
                )
        
        self.stdout.write(self.style.SUCCESS('\nProcessamento concluído!'))
