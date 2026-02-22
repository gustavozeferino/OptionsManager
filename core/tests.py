from django.test import TestCase, Client
from django.urls import reverse
from .models import AtivoB3, AtivoMonitorado
from .views import clean_numeric, clean_date
import datetime
import io
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

User = get_user_model()

class AtivoUtilsTestCase(TestCase):
    """Testa as funções de limpeza de dados (Helpers)"""

    def test_clean_numeric_format(self):
        # Testa conversão de padrão B3 para float
        self.assertEqual(clean_numeric("R$ 1.250,50"), 1250.50)
        self.assertEqual(clean_numeric("-"), 0.0)
        self.assertEqual(clean_numeric(""), 0.0)

    def test_clean_date_format(self):
        # Testa se converte data brasileira corretamente e ignora hífens
        data_esperada = datetime.date(2026, 3, 6)
        self.assertEqual(clean_date("06/03/2026"), data_esperada)
        self.assertEqual(clean_date("-"), None)

class AtivoFiltroMonitoradoTestCase(TestCase):
    """Testa a lógica de filtro dinâmico e limpeza de banco"""

    def setUp(self):
        # Cadastra PETR4 como monitorado
        AtivoMonitorado.objects.create(ticker="PETR4", ativo_no_dashboard=True)
        # Cadastra VALE3 mas desativa o monitoramento
        AtivoMonitorado.objects.create(ticker="VALE3", ativo_no_dashboard=False)

    def test_limpeza_ativos_nao_monitorados(self):
        # Criamos ativos no banco
        AtivoB3.objects.create(codigo_isin="BR1", ticker="PETRL30", ativo_objeto="PETR4")
        AtivoB3.objects.create(codigo_isin="BR2", ticker="VALEM40", ativo_objeto="VALE3")
        AtivoB3.objects.create(codigo_isin="BR3", ticker="BBASO50", ativo_objeto="BBAS3")

        # Executa a lógica de limpeza que está na sua view
        permitidos = AtivoMonitorado.objects.filter(ativo_no_dashboard=True).values_list('ticker', flat=True)
        AtivoB3.objects.exclude(ativo_objeto__in=permitidos).delete()

        # Deve sobrar apenas PETR4 (VALE3 está False e BBAS3 não existe em monitorados)
        self.assertEqual(AtivoB3.objects.count(), 1)
        self.assertEqual(AtivoB3.objects.first().ativo_objeto, "PETR4")

class AccessControlTestCase(TestCase):
    """Testa se as páginas estão protegidas apenas para Admins"""

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(username='admin', password='password', email='a@a.com')
        self.common_user = User.objects.create_user(username='jose', password='password')

    def test_upload_acesso_negado_anonimo(self):
        # Tenta acessar sem estar logado
        response = self.client.get(reverse('core:upload_csv'))
        # O Django redireciona para o login (302)
        self.assertEqual(response.status_code, 302)

    def test_lista_ativos_acesso_permitido_admin(self):
        self.client.login(username='admin', password='password')
        response = self.client.get(reverse('core:lista_ativos'))
        self.assertEqual(response.status_code, 200)


class ImportacaoCSVTestCase(TestCase):
    """Testa o processo completo de Upload e Processamento do CSV"""

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(username='admin', password='admin123', email='admin@optionsmanager.com')
        # Precisamos cadastrar o ativo no monitoramento para ele não ser ignorado
        AtivoMonitorado.objects.create(ticker="PETR4", ativo_no_dashboard=True)

    def test_upload_csv_valido(self):
        self.client.login(username='admin', password='admin123')

        # Criamos um conteúdo simulando o CSV da B3 com lixo no topo
        # O cabeçalho real começa onde tem 'Código ISIN'
        csv_content = (
            "Código ISIN;Instrumento financeiro;Ativo;Tipo de opção;Preço de exercício;Data de expiração\n"
            "BR12345;PETRL30;PETR4;CALL;R$ 30,50;20/03/2026\n"
            "BR99999;VALEM40;VALE3;CALL;R$ 70,00;20/03/2026\n"
        )
        
        csv_file = SimpleUploadedFile("teste.csv", csv_content.encode('latin1'), content_type="text/csv")

        # Faz o POST para a view de upload
        url = reverse('core:upload_csv')
        response = self.client.post(url, {'arquivo': csv_file}, follow=True)

        # Verificações
        self.assertEqual(response.status_code, 200)
        
        # Deve ter criado apenas 1 ativo (PETR4) porque VALE3 não estava monitorado
        self.assertEqual(AtivoB3.objects.count(), 1)
        
        ativo = AtivoB3.objects.first()
        self.assertEqual(ativo.ticker, "PETRL30")
        self.assertEqual(float(ativo.preco_exercicio), 30.50)
        self.assertEqual(ativo.ativo_objeto, "PETR4")

    def test_upload_csv_historico(self):
        """Testa se o histórico de importação é gravado corretamente no upload_csv"""
        self.client.login(username='admin', password='admin123')
        
        csv_content = (
            "Código ISIN;Instrumento financeiro;Ativo;Tipo de opção;Preço de exercício;Data de expiração\n"
            "BR12345;PETRL30;PETR4;CALL;R$ 30,50;20/03/2026\n"
        )
        csv_file = SimpleUploadedFile("teste_hist.csv", csv_content.encode('latin1'), content_type="text/csv")
        
        from .models import HistoricoImportacao
        initial_count = HistoricoImportacao.objects.count()
        
        response = self.client.post(reverse('core:upload_csv'), {'arquivo': csv_file}, follow=True)
        
        self.assertEqual(HistoricoImportacao.objects.count(), initial_count + 1)
        historico = HistoricoImportacao.objects.first()
        self.assertEqual(historico.tipo_importacao, 'Cadastro de Instrumentos')
        self.assertEqual(historico.novos, 1)


class HistoricoPrecosTestCase(TestCase):
    """Testa o processo de Upload de Preços e gravação de histórico"""

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(username='admin', password='admin123', email='admin@optionsmanager.com')
        # Precisamos de um AtivoB3 já cadastrado para importar preço
        self.ativo = AtivoB3.objects.create(
            codigo_isin="BR_TESTE_123",
            ticker="PETRL30",
            ativo_objeto="PETR4"
        )

    def test_upload_precos_historico(self):
        self.client.login(username='admin', password='admin123')

        # CSV de preços (Negócios Consolidados)
        csv_content = (
            "Código ISIN;Preço de abertura;Preço máximo;Preço mínimo;Preço de fechamento;Quantidade de negócios;Volume financeiro\n"
            "BR_TESTE_123;R$ 1,50;R$ 1,60;R$ 1,45;R$ 1,55;1000;R$ 1.550,00\n"
        )
        csv_file = SimpleUploadedFile("precos.csv", csv_content.encode('latin1'), content_type="text/csv")

        from .models import HistoricoImportacao, HistoricoPreco
        initial_hist_count = HistoricoImportacao.objects.count()

        url = reverse('core:upload_precos')
        # Precisamos enviar data_manual se o CSV não tiver 'Data do negócio'
        response = self.client.post(url, {
            'arquivo': csv_file,
            'data_manual': '2026-02-22'
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(HistoricoPreco.objects.count(), 1)
        
        # Verifica histórico
        self.assertEqual(HistoricoImportacao.objects.count(), initial_hist_count + 1)
        historico = HistoricoImportacao.objects.first()
        self.assertEqual(historico.tipo_importacao, 'Negócios Consolidados')
        self.assertEqual(historico.novos, 1) # Primeiro registro é 'novo'
        self.assertEqual(historico.arquivo_nome, "precos.csv")

