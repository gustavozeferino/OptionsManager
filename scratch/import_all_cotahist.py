import os
import sys
import django

sys.path.insert(0, r'C:\Users\Usuario\Projetos\OptionsManager')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from dadosb3.services import ingest_cothist_file

files = [
    r'input_data\cotahist\COTAHIST_2026-01-02-03.TXT',
    r'input_data\cotahist\COTAHIST_D11052026.TXT',
    r'input_data\cotahist\COTAHIST_D12052026.TXT',
    r'input_data\cotahist\COTAHIST_D13052026.TXT',
]

total = 0
for f in files:
    path = os.path.join(r'C:\Users\Usuario\Projetos\OptionsManager', f)
    print(f"Importando: {os.path.basename(f)} ...")
    count = ingest_cothist_file(path)
    print(f"  -> {count} registros")
    total += count

print(f"\nTotal importado: {total}")
