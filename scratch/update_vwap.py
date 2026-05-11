import os
import django
import sys
from decimal import Decimal

sys.path.append(os.getcwd())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from dadosb3.models import NegocioDiario

def update_vwap():
    negocios = NegocioDiario.objects.all()
    count = 0
    for n in negocios:
        if n.volume_financeiro and n.qtd_contratos and n.qtd_contratos > 0:
            n.vwap = n.volume_financeiro / Decimal(n.qtd_contratos)
            n.save()
            count += 1
    print(f"Atualizados {count} registros com VWAP.")

if __name__ == "__main__":
    update_vwap()
