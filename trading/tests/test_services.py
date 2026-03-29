from django.test import TestCase
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date
from trading.models import Estrutura, Ordem, PosicaoConsolidada
from core.models import AtivoB3, HistoricoPreco
from trading.services import recalcular_posicao, recalcular_estrutura

User = get_user_model()

class TradingServicesTestCase(TestCase):
    def setUp(self):
        # Usuário base
        self.user = User.objects.create_user(username='testuser', password='password')
        
        # O signal deve ter criado a estrutura padrão
        self.estrutura = Estrutura.objects.get(usuario=self.user, slug='sem-estrutura')
        
        # Cria um ativo de teste
        self.ativo = AtivoB3.objects.create(
            codigo_isin='BRTESTE12345',
            ticker='TESTE1',
            ativo_objeto='TESTE1',
            data_expiracao='2026-12-31'
        )
        
        # Cria histórico de preço para hoje
        HistoricoPreco.objects.create(
            ativo=self.ativo,
            data_pregao=date.today(),
            fechamento=Decimal('15.00')
        )

    def test_posicao_compra_simples(self):
        """Testa o cálculo de uma posição com apenas compras"""
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=100, preco=Decimal('10.00'), data=date.today()
        )
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=100, preco=Decimal('12.00'), data=date.today()
        )
        
        # recalcular_posicao já é chamado pelo signal
        posicao = PosicaoConsolidada.objects.get(estrutura=self.estrutura, ativo=self.ativo)
        
        self.assertEqual(posicao.quantidade_atual, 200)
        self.assertEqual(posicao.preco_medio, Decimal('11.00'))
        self.assertEqual(posicao.pl_realizado_acumulado, Decimal('0.00'))

    def test_posicao_compra_venda_parcial(self):
        """Testa o cálculo do PL Realizado ao vender parcialmente uma posição"""
        # Compra 100 a $10
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=100, preco=Decimal('10.00'), data=date.today()
        )
        # Vende 50 a $15 (Lucro de $5 por ação = $250)
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=-50, preco=Decimal('15.00'), data=date.today()
        )
        
        posicao = PosicaoConsolidada.objects.get(estrutura=self.estrutura, ativo=self.ativo)
        
        self.assertEqual(posicao.quantidade_atual, 50)
        self.assertEqual(posicao.preco_medio, Decimal('10.00')) # Preço médio não muda na venda
        self.assertEqual(posicao.pl_realizado_acumulado, Decimal('250.00'))

    def test_posicao_virar_a_mao(self):
        """Testa virar a mão de comprado para vendido"""
        # Compra 100 a $10
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=100, preco=Decimal('10.00'), data=date.today()
        )
        # Vende 150 a $15 
        # (Zera 100 com lucro de $500, fica vendido em 50 a PM $15)
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=-150, preco=Decimal('15.00'), data=date.today()
        )
        
        posicao = PosicaoConsolidada.objects.get(estrutura=self.estrutura, ativo=self.ativo)
        
        self.assertEqual(posicao.quantidade_atual, -50)
        self.assertEqual(posicao.preco_medio, Decimal('15.00'))
        self.assertEqual(posicao.pl_realizado_acumulado, Decimal('500.00'))
        
    def test_recalcular_estrutura_pl_aberto(self):
        """Testa o cálculo total da Estrutura incluindo PL Aberto"""
        # Compra 100 a $10. PM = 10. Qtd = 100.
        # Preço de Fechamento de hoje = $15 (configurado no setUp)
        # PL Aberto = (15 - 10) * 100 = 500
        # PL Realizado = 0
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=100, preco=Decimal('10.00'), data=date.today()
        )
        
        self.estrutura.refresh_from_db()
        
        self.assertEqual(self.estrutura.pl_realizado, Decimal('0.00'))
        self.assertEqual(self.estrutura.pl_aberto, Decimal('500.00'))
        self.assertEqual(self.estrutura.valor_total, Decimal('500.00'))

    def test_exposicao_financeira(self):
        """Testa o cálculo da exposição financeira total da estrutura"""
        from trading.models import DailySnapshot
        
        # 1. Compra 100 a $10. Último Preço = $15 (definido no setUp).
        # Exposição = abs(100) * 15 = 1500
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=100, preco=Decimal('10.00'), data=date.today()
        )
        
        # recarregar do banco para pegar os valores atualizados pelo signal -> recalcular_estrutura
        self.estrutura.refresh_from_db()
        self.assertEqual(self.estrutura.exposicao_atual, Decimal('1500.00'))
        
        # 2. Vende 50 a $12. Qtd Restante = 50. 
        # Exposição = abs(50) * 15 = 750
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=-50, preco=Decimal('12.00'), data=date.today()
        )
        self.estrutura.refresh_from_db()
        self.assertEqual(self.estrutura.exposicao_atual, Decimal('750.00'))
        
        # 3. Vende mais 100 a $13. Qtd Restante = -50 (Vendida).
        # Exposição = -50 * 15 = -750
        Ordem.objects.create(
            estrutura=self.estrutura, ativo=self.ativo,
            quantidade=-100, preco=Decimal('13.00'), data=date.today()
        )
        self.estrutura.refresh_from_db()
        self.assertEqual(self.estrutura.exposicao_atual, Decimal('-750.00'))
        
        # Verifica se o snapshot diário também tem a exposição
        snapshot = DailySnapshot.objects.filter(estrutura=self.estrutura, data=date.today()).first()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.exposicao_diaria, Decimal('-750.00'))
