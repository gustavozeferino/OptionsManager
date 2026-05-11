from django.db import models

class Instrumento(models.Model):
    ticker = models.CharField(max_length=100)
    ativo_objeto = models.CharField(max_length=100, null=True, blank=True)
    descricao = models.TextField(null=True, blank=True)
    segmento = models.CharField(max_length=100, null=True, blank=True)
    mercado = models.CharField(max_length=100, null=True, blank=True)
    categoria = models.CharField(max_length=100, null=True, blank=True)
    data_expiracao = models.DateField(null=True, blank=True)
    data_inicio_negocio = models.DateField(null=True, blank=True)
    data_fim_negocio = models.DateField(null=True, blank=True)
    isin = models.CharField(max_length=12, unique=True)
    cfi = models.CharField(max_length=100, null=True, blank=True)
    tipo_opcao = models.CharField(max_length=10, null=True, blank=True) # CALL/PUT
    lote_alocacao = models.IntegerField(null=True, blank=True)
    moeda = models.CharField(max_length=50, null=True, blank=True)
    tipo_entrega = models.CharField(max_length=50, null=True, blank=True)
    strike = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    estilo_opcao = models.CharField(max_length=10, null=True, blank=True) # AMER/EURO
    ind_premio_antecipado = models.BooleanField(null=True, blank=True)
    id_distribuicao = models.CharField(max_length=50, null=True, blank=True)
    fator_preco = models.IntegerField(null=True, blank=True)
    dias_liquidacao = models.IntegerField(null=True, blank=True)
    tipo_serie = models.CharField(max_length=50, null=True, blank=True)
    ind_protecao = models.BooleanField(null=True, blank=True)
    ind_exercicio_automatico = models.BooleanField(null=True, blank=True)
    especificacao = models.CharField(max_length=100, null=True, blank=True)
    nome_instituicao = models.CharField(max_length=255, null=True, blank=True)
    data_evento_corp = models.DateField(null=True, blank=True)
    tipo_custodia = models.CharField(max_length=100, null=True, blank=True)
    capital_social = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    nivel_governanca = models.CharField(max_length=100, null=True, blank=True)
    data = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'instrumento'

class InstrumentoAtualizacao(models.Model):
    data_atualizacao = models.DateTimeField(auto_now_add=True)
    data_arquivo = models.DateField()
    isin = models.CharField(max_length=12)
    coluna = models.CharField(max_length=100)
    valor_antigo = models.TextField(null=True, blank=True)
    valor_novo = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'instrumento_atualizacao'

class NegocioDiario(models.Model):
    data_pregao = models.DateField()
    ticker = models.CharField(max_length=100, db_index=True)
    isin = models.CharField(max_length=12, db_index=True)
    segmento = models.CharField(max_length=100, null=True, blank=True)
    preco_abertura = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_minimo = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_maximo = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_medio = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_fechamento = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    oscilacao = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    ajuste = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    ajuste_referencia = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    ajuste_anterior = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    preco_referencia = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    variacao = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    valor_ajuste_contrato = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    bid = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    ask = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    qtd_negocios = models.BigIntegerField(null=True, blank=True)
    qtd_contratos = models.BigIntegerField(null=True, blank=True)
    volume_financeiro = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    vwap = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'negocio_diario'
        unique_together = ('data_pregao', 'ticker', 'isin')

class PosicaoAberta(models.Model):
    data = models.DateField(null=True, blank=True)
    ticker = models.CharField(max_length=100)
    isin = models.CharField(max_length=12)
    ativo_objeto = models.CharField(max_length=100, null=True, blank=True)
    codigo_expiracao = models.CharField(max_length=100, null=True, blank=True)
    segmento = models.CharField(max_length=100, null=True, blank=True)
    contratos_abertos = models.BigIntegerField(null=True, blank=True)
    variacao_abertos = models.BigIntegerField(null=True, blank=True)
    id_distribuicao = models.CharField(max_length=50, null=True, blank=True)
    qtd_coberta = models.BigIntegerField(null=True, blank=True)
    posicoes_bloqueadas = models.BigIntegerField(null=True, blank=True)
    qtd_descoberta = models.BigIntegerField(null=True, blank=True)
    total_posicoes = models.BigIntegerField(null=True, blank=True)
    qtd_tomadores = models.IntegerField(null=True, blank=True)
    qtd_doadores = models.IntegerField(null=True, blank=True)
    qtd_atual = models.BigIntegerField(null=True, blank=True)
    contratos_travados = models.BigIntegerField(null=True, blank=True)
    contratos_transferidos = models.BigIntegerField(null=True, blank=True)
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
