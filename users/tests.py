from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from .models import LayoutConfig

User = get_user_model()


class UserModelTest(TestCase):
    """Testes para o modelo User."""
    
    def test_create_user(self):
        """Testa criação de usuário."""
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.email, 'test@example.com')
        self.assertTrue(user.check_password('testpass123'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
    
    def test_create_superuser(self):
        """Testa criação de superusuário."""
        user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
    
    def test_email_unique(self):
        """Testa que o email deve ser único."""
        User.objects.create_user(
            username='user1',
            email='test@example.com',
            password='pass123'
        )
        with self.assertRaises(Exception):
            User.objects.create_user(
                username='user2',
                email='test@example.com',
                password='pass123'
            )


class UserViewTest(TestCase):
    """Testes para as views de usuário."""

    def setUp(self):
        self.user_password = 'testpass123'
        self.user = User.objects.create_user(
            username='viewuser',
            email='view@example.com',
            password=self.user_password
        )

    def test_login_page_status_code(self):
        """Testa se a página de login está acessível."""
        response = self.client.get('/users/login/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/login.html')

    def test_login_successful(self):
        """Testa login com credenciais válidas."""
        response = self.client.post('/users/login/', {
            'username': 'viewuser',
            'password': self.user_password
        })
        # LoginView redireciona após sucesso
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_login_failed(self):
        """Testa login com credenciais inválidas."""
        response = self.client.post('/users/login/', {
            'username': 'viewuser',
            'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, 200)  # Volta para o form com erro
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_logout_successful(self):
        """Testa logout."""
        self.client.login(username='viewuser', password=self.user_password)
        response = self.client.post('/users/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class LayoutConfigTest(TestCase):
    """Testes para configuração de layout e cores."""

    def setUp(self):
        self.user_password = 'testpass123'
        self.user = User.objects.create_user(
            username='layoutuser',
            email='layout@example.com',
            password=self.user_password
        )

    def test_lazy_layout_config_creation(self):
        """Testa se a propriedade layout cria e retorna o LayoutConfig automaticamente."""
        # Inicialmente não existe
        self.assertFalse(LayoutConfig.objects.filter(usuario=self.user).exists())
        
        # Acesso via propriedade
        config = self.user.layout
        
        # Agora deve existir
        self.assertTrue(LayoutConfig.objects.filter(usuario=self.user).exists())
        self.assertEqual(config.compra_color, '#10b981')  # Valor padrão
        self.assertEqual(config.venda_color, '#ef4444')    # Valor padrão

    def test_customizar_layout_view_anonymous(self):
        """Testa se o acesso à view é restrito para usuários anônimos."""
        response = self.client.get('/users/layout/')
        self.assertEqual(response.status_code, 302)  # Redireciona para o login

    def test_customizar_layout_view_authenticated(self):
        """Testa se o usuário autenticado acessa e salva novas cores."""
        self.client.login(username='layoutuser', password=self.user_password)
        
        # Acessa a página
        response = self.client.get('/users/layout/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/customizar_layout.html')
        
        # Envia novas cores
        response = self.client.post('/users/layout/', {
            'compra_color': '#22c55e',
            'venda_color': '#ef4444',
            'call_color': '#00d4aa',
            'put_color': '#f59e0b',
            'ativo_color': '#6c63ff'
        })
        self.assertEqual(response.status_code, 302)  # Redireciona após salvar
        
        # Verifica se as novas cores foram salvas no banco
        self.user.refresh_from_db()
        self.assertEqual(self.user.layout.compra_color, '#22c55e')
        self.assertEqual(self.user.layout.ativo_color, '#6c63ff')

    def test_customizar_layout_reset_defaults(self):
        """Testa se é possível restaurar as cores padrões."""
        self.client.login(username='layoutuser', password=self.user_password)
        
        # Modifica primeiro
        config = self.user.layout
        config.compra_color = '#ffffff'
        config.save()
        
        # Envia requisição de reset
        response = self.client.post('/users/layout/', {
            'reset_defaults': 'true'
        })
        self.assertEqual(response.status_code, 302)
        
        # Verifica se voltou aos padrões
        self.user.refresh_from_db()
        self.assertEqual(self.user.layout.compra_color, '#10b981')
