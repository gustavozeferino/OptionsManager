from django.core.management.base import BaseCommand
from core.services import sync_precos_negocios_b3

class Command(BaseCommand):
    help = 'Sincroniza dados de NegocioDiario (dadosb3) para HistoricoPreco (core)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Iniciando sincronização de preços...'))
        stats = sync_precos_negocios_b3()
        self.stdout.write(self.style.SUCCESS(
            f"Sincronização concluída!\n"
            f"Novos registros: {stats['novos']}\n"
            f"Pulados (já existentes): {stats['pulados']}"
        ))
