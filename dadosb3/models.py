from django.db import models

class Instrumento(models.Model):
    ticker = models.CharField(max_length=100)
    ativo_objeto = models.CharField(max_length=100, null=True, blank=True)
    descricao = models.CharField(max_length=255, null=True, blank=True)
    segmento = models.CharField(max_length=100, null=True, blank=True)
    mercado = models.CharField(max_length=100, null=True, blank=True)
    categoria = models.CharField(max_length=100, null=True, blank=True)
    data_expiracao = models.DateField(null=True, blank=True)
    data_inicio_negocio = models.DateField(null=True, blank=True)
    isin = models.CharField(max_length=100)
    strike = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    estilo_opcao = models.CharField(max_length=100, null=True, blank=True)
    nome_instituicao = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'instrumento'

class NegocioDiario(models.Model):
    data_pregao = models.DateField()
    ticker = models.CharField(max_length=100)
    isin = models.CharField(max_length=100)
    preco_abertura = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_minimo = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_maximo = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_medio = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_fechamento = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    qtd_negocios = models.BigIntegerField(null=True, blank=True)
    volume_financeiro = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'negocio_diario'
        unique_together = ('data_pregao', 'ticker', 'isin')

class PosicaoAberta(models.Model):
    ticker = models.CharField(max_length=100)
    isin = models.CharField(max_length=100)
    codigo_expiracao = models.CharField(max_length=100, null=True, blank=True)
    contratos_abertos = models.BigIntegerField(null=True, blank=True)
    qtd_coberta = models.BigIntegerField(null=True, blank=True)
    qtd_descoberta = models.BigIntegerField(null=True, blank=True)
    preco_termo = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'posicao_aberta'

class LogProcessamento(models.Model):
    data_hora = models.DateTimeField(auto_now_add=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=50)
    descricao_falha = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'log_processamento'
