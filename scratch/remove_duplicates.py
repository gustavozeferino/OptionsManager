import os
import django
import sys

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from dadosb3.models import Instrumento
from django.db import connections

def remove_duplicates():
    # Identifica duplicatas de ISIN
    from django.db.models import Count
    duplicates = Instrumento.objects.values('isin').annotate(isin_count=Count('isin')).filter(isin_count__gt=1)
    
    total_removed = 0
    for entry in duplicates:
        isin = entry['isin']
        # Mantém o registro mais recente (ou o primeiro encontrado)
        objs = Instrumento.objects.filter(isin=isin).order_by('-data', '-id')
        keep_id = objs[0].id
        to_delete = objs.exclude(id=keep_id)
        count = to_delete.count()
        to_delete.delete()
        total_removed += count
        print(f"ISIN {isin}: mantido ID {keep_id}, removidos {count} duplicatas.")
    
    print(f"Total de registros removidos: {total_removed}")

if __name__ == "__main__":
    remove_duplicates()
