import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

# Verifica se já existe um superusuário
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser(
        username='admin',
        email='admin@optionsmanager.com',
        password='admin123'
    )
    print("Superusuário criado com sucesso!")
    print("Username: admin")
    print("Password: admin123")
else:
    print("Superusuário já existe!")
