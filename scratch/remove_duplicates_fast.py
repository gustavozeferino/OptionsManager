import os
import django
import sys

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from django.db import connections

def remove_duplicates_fast():
    with connections['b3_data'].cursor() as cursor:
        print("Iniciando remoção rápida de duplicatas...")
        sql = """
        DELETE FROM instrumento
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM instrumento
            GROUP BY isin
        )
        """
        cursor.execute(sql)
        print(f"Registros removidos: {cursor.rowcount}")

if __name__ == "__main__":
    remove_duplicates_fast()
