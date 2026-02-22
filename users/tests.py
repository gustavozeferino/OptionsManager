from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

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
