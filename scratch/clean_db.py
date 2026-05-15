import os
import sys
import django

sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/../")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from django.db import connections

try:
    with connections['b3_data'].cursor() as cursor:
        # Kill other connections
        cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'b3_data_db' AND pid != pg_backend_pid();")
        print("Killed other connections.")
        
        # Drop table
        cursor.execute("DROP TABLE IF EXISTS cotacao_historica CASCADE;")
        print("Dropped cotacao_historica.")
        
        # Truncate negocio_diario
        cursor.execute("TRUNCATE TABLE negocio_diario CASCADE;")
        print("Truncated negocio_diario.")
except Exception as e:
    print(f"Error: {e}")
