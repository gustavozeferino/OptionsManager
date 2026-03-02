from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from decimal import Decimal
import datetime

from core.models import AtivoB3
from trading.models import Estrutura, Ordem

User = get_user_model()

class TradingViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        
        # A estrutura padrao ja deve existir pelo signal
        self.estrutura_padrao = Estrutura.objects.get(usuario=self.user, slug='sem-estrutura')
        
        # Criamos o ativo teste e outro que usaremos
        self.ativo_1 = AtivoB3.objects.create(codigo_isin='BRTESTE12345', ticker='PETRC250', ativo_objeto='PETR4')
        self.ativo_2 = AtivoB3.objects.create(codigo_isin='BRTESTE54321', ticker='VALE3', ativo_objeto='VALE3')

    def test_upload_ordens_csv_sucesso(self):
        """Testa o fluxo de upload de CSV bem formatado"""
        import io
        csv_content = (
            "Data;Ativo;Quantidade;Preço;Operacao\n"
            "20/02/2026;PETRC250;1.000;1,50;Compra\n"
            "21/02/2026;VALE3;500;65,20;Venda\n"
        ).encode('utf-8')
        
        csv_file = SimpleUploadedFile("ordens_teste.csv", csv_content, content_type="text/csv")
        
        # Envia POST
        url = reverse('trading:upload_ordens')
        response = self.client.post(url, {'csv_file': csv_file})
        
        # Deve redirecionar pro dashboard após importacao
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('trading:dashboard_estruturas'))
        
        # Verifica se as ordens foram inseridas na Sem Estrutura
        ordens = Ordem.objects.filter(estrutura=self.estrutura_padrao).order_by('data')
        self.assertEqual(ordens.count(), 2)
        
        # Verifica a primeira ordem (Compra)
        self.assertEqual(ordens[0].ativo, self.ativo_1)
        self.assertEqual(ordens[0].quantidade, 1000)
        self.assertEqual(ordens[0].preco, Decimal('1.50'))
        
        # Verifica a segunda ordem (Venda, logo qtd negativa)
        self.assertEqual(ordens[1].ativo, self.ativo_2)
        self.assertEqual(ordens[1].quantidade, -500)
        self.assertEqual(ordens[1].preco, Decimal('65.20'))
        
    def test_upload_ordens_ignora_nao_cadastrados(self):
        """Testa o comportamento ao enviar um ativo não existente no banco"""
        csv_content = (
            "Data;Ativo;Quantidade;Preço;Operacao\n"
            "20/02/2026;NAOEXISTE1;1.000;1,50;Compra\n"
        ).encode('utf-8')
        
        csv_file = SimpleUploadedFile("ordens_erro.csv", csv_content, content_type="text/csv")
        response = self.client.post(reverse('trading:upload_ordens'), {'csv_file': csv_file})
        
        self.assertEqual(response.status_code, 302)
        
        # Não deve haver ordens importadas
        ordens = Ordem.objects.filter(estrutura=self.estrutura_padrao)
        self.assertEqual(ordens.count(), 0)
