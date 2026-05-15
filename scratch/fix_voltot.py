import os
import sys
import django

sys.path.insert(0, r'C:\Users\Usuario\Projetos\OptionsManager')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from django.db import connections

print("Corrigindo voltot em cotacao_historica (dividindo por 100)...")
with connections['b3_data'].cursor() as cursor:
    cursor.execute("UPDATE cotacao_historica SET voltot = voltot / 100 WHERE voltot IS NOT NULL")
    updated = cursor.rowcount

print(f"Registros atualizados: {updated}")

print("\nLimpando negocio_diario...")
with connections['b3_data'].cursor() as cursor:
    cursor.execute("TRUNCATE TABLE negocio_diario CASCADE")
print("negocio_diario limpa.")
