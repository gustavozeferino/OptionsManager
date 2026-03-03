import uuid
from django.db import models
from django.conf import settings
from core.models import AtivoB3
from django.utils.text import slugify

class Estrutura(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='estruturas')
    nome = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True)
    
    # Consolidação de Performance
    pl_realizado = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    pl_aberto = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            # Gerador de slug único baseado no nome
            base_slug = slugify(self.nome)
            self.slug = base_slug
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.usuario.username})"
        
    class Meta:
        verbose_name = "Estrutura"
        verbose_name_plural = "Estruturas"
        ordering = ['-criado_em']

class Ordem(models.Model):
    estrutura = models.ForeignKey(Estrutura, on_delete=models.CASCADE, related_name='ordens')
    ativo = models.ForeignKey(AtivoB3, on_delete=models.PROTECT, related_name='ordens')
    quantidade = models.IntegerField(help_text="Valores positivos para compra, negativos para venda")
    preco = models.DecimalField(max_digits=15, decimal_places=6)
    data = models.DateField()
    
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        tipo = "COMPRA" if self.quantidade > 0 else "VENDA"
        return f"{tipo} {abs(self.quantidade)} {self.ativo.ticker} @ {self.preco}"
    
    @property
    def qtd_abs(self):
        return abs(self.quantidade)

    class Meta:
        verbose_name = "Ordem"
        verbose_name_plural = "Ordens"
        ordering = ['-data', '-criado_em']

class PosicaoConsolidada(models.Model):
    estrutura = models.ForeignKey(Estrutura, on_delete=models.CASCADE, related_name='posicoes')
    ativo = models.ForeignKey(AtivoB3, on_delete=models.PROTECT, related_name='posicoes_estruturas')
    quantidade_atual = models.IntegerField(default=0)
    preco_medio = models.DecimalField(max_digits=15, decimal_places=6, default=0)
    pl_realizado_acumulado = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.ativo.ticker} em {self.estrutura.nome}: {self.quantidade_atual}"

    class Meta:
        verbose_name = "Posição Consolidada"
        verbose_name_plural = "Posições Consolidadas"
        unique_together = ('estrutura', 'ativo')

class DailySnapshot(models.Model):
    estrutura = models.ForeignKey(Estrutura, on_delete=models.CASCADE, related_name='historico_snapshots')
    data = models.DateField()
    pl_realizado = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    pl_aberto = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Snapshot Diário"
        verbose_name_plural = "Snapshots Diários"
        unique_together = ('estrutura', 'data')
        ordering = ['-data']

    def __str__(self):
        return f"{self.estrutura.nome} em {self.data} - PL: {self.valor_total}"
