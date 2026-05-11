import os
import django
import sys

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from django.db import connections

def update_vwap_fast():
    with connections['b3_data'].cursor() as cursor:
        print("Iniciando atualização rápida de VWAP...")
        sql = """
        UPDATE negocio_diario
        SET vwap = CASE 
            WHEN qtd_contratos > 0 THEN volume_financeiro / qtd_contratos 
            ELSE NULL 
        END
        WHERE vwap IS NULL AND volume_financeiro IS NOT NULL AND qtd_contratos IS NOT NULL;
        """
        cursor.execute(sql)
        print(f"Registros atualizados: {cursor.rowcount}")

if __name__ == "__main__":
    update_vwap_fast()
