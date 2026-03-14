from django.db import models
from datetime import date
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator

User = get_user_model()

class AcessoLog(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    path = models.CharField(max_length=255)
    metodo = models.CharField(max_length=10)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    data_acesso = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario} acessou {self.path} em {self.data_acesso}"


class AtivoB3(models.Model):
    """
    Modelo para armazenar informações de ativos B3 importados do Cadastro de Instrumentos.
    """
    # Chave primária
    codigo_isin = models.CharField(
        _('Código ISIN'), 
        max_length=20, 
        primary_key=True, # <--- Mudança aqui
        help_text=_('Identificador único universal do ativo')
    )
    
    # Campos básicos do ativo
    ticker = models.CharField(
        _('Ticker'), 
        max_length=50, 
        db_index=True, # Adicionamos index para busca rápida
        help_text=_('Instrumento financeiro (ex: PETRL280)')
    )
    ativo_objeto = models.CharField(_('Ativo Objeto'), max_length=50, db_index=True)
    descricao_ativo = models.CharField(_('Descrição do Ativo'), max_length=500, blank=True)
    segmento = models.CharField(_('Segmento'), max_length=100, blank=True)
    mercado = models.CharField(_('Mercado'), max_length=100, blank=True)
    categoria = models.CharField(_('Categoria'), max_length=100, blank=True)
    
    # Datas
    data_expiracao = models.DateField(_('Data de Expiração'), null=True, blank=True)
    data_inicio_negocio = models.DateField(_('Data Início Negócio'), null=True, blank=True)
    data_fim_negocio = models.DateField(_('Data Fim Negócio'), null=True, blank=True)
    data_inicio_evento_corp = models.DateField(_('Data Início Evento Corporativo'), null=True, blank=True)
    
    # Códigos e identificadores
    codigo_cfi = models.CharField(_('Código CFI'), max_length=10, blank=True)
    codigo_especificacao = models.CharField(_('Código de Especificação'), max_length=50, blank=True)
    id_distribuicao = models.IntegerField(_('Identificador Distribuição'), null=True, blank=True)
    
    # Informações de opção
    tipo_opcao = models.CharField(_('Tipo de Opção'), max_length=50, blank=True)
    preco_exercicio = models.DecimalField(
        _('Preço de Exercício'),
        max_digits=15,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    estilo_opcao = models.CharField(_('Estilo de Opção'), max_length=50, blank=True)
    tamanho_lote = models.IntegerField(_('Tamanho de Lote'), null=True, blank=True)
    
    # Informações financeiras
    moeda_negociada = models.CharField(_('Moeda Negociada'), max_length=10, blank=True)
    tipo_entrega = models.CharField(_('Tipo de Entrega'), max_length=50, blank=True)
    capital_social = models.DecimalField(
        _('Capital Social'),
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    
    # Flags e indicadores booleanos
    ind_premio_antecipado = models.BooleanField(_('Ind. Prêmio Antecipado'), default=False)
    exercicio_automatico = models.BooleanField(_('Exercício Automático'), default=False)
    
    # Outros campos numéricos
    fator_preco = models.IntegerField(_('Fator de Preço'), null=True, blank=True)
    dias_liquidacao = models.IntegerField(_('Dias para Liquidação'), null=True, blank=True)
    
    # Campos de classificação
    tipo_serie = models.CharField(_('Tipo de Série'), max_length=50, blank=True)
    ind_protecao = models.CharField(_('Indicador de Proteção'), max_length=50, blank=True)
    nivel_governanca = models.CharField(_('Nível Governança'), max_length=50, blank=True)
    tipo_tratamento_custodia = models.CharField(_('Tipo Tratamento Custódia'), max_length=50, blank=True)
    
    # Informações institucionais
    nome_instituicao = models.CharField(_('Nome da Instituição'), max_length=200, blank=True)
    
    # Classificação
    classificacao_vencimento = models.CharField(_('Classificação do Vencimento'), max_length=10, blank=True, null=True, help_text="Mensal ou Semanal")
    
    # Timestamps
    criado_em = models.DateTimeField(_('Criado em'), auto_now_add=True)
    atualizado_em = models.DateTimeField(_('Atualizado em'), auto_now=True)
    
    @property
    def dte(self):
        if self.data_expiracao:
            hoje = date.today()
            # Adicionamos 1 dia ao cálculo conforme sua definição
            delta = (self.data_expiracao - hoje).days + 1
            
            # Se o resultado for negativo, retornamos 0 (já expirou)
            return max(0, delta)
        return None

    @classmethod
    def classificar_vencimentos(cls, ativo_objeto=None):
        """
        Classifica as opções de um ativo objeto (ou de todos) em Mensal ou Semanal
        baseado na regra de: 
        - Único vencimento no mês -> Mensal
        - Múltiplos vencimentos -> O mais próximo da 3ª sexta-feira é Mensal, os outros são Semanais.
        """
        import calendar
        from datetime import date
        from django.db.models import Count
        from django.db.models.functions import ExtractYear, ExtractMonth

        qs = cls.objects.exclude(data_expiracao__isnull=True)
        if ativo_objeto:
            qs = qs.filter(ativo_objeto=ativo_objeto)
            
        ativos_objetos = qs.values_list('ativo_objeto', flat=True).distinct()
        
        for ativo_obj in ativos_objetos:
            # Agrupar por ano e mês
            vencimentos_ativo = qs.filter(ativo_objeto=ativo_obj).values_list('data_expiracao', flat=True).distinct()
            
            # Construir um dicionário estruturado por (ano, mes) -> [datas]
            meses_dict = {}
            for d in vencimentos_ativo:
                key = (d.year, d.month)
                if key not in meses_dict:
                    meses_dict[key] = []
                meses_dict[key].append(d)
                
            for (year, month), dates in meses_dict.items():
                if len(dates) == 1:
                    # Apenas um vencimento no mês, é o Mensal
                    cls.objects.filter(ativo_objeto=ativo_obj, data_expiracao=dates[0]).update(classificacao_vencimento='Mensal')
                else:
                    # Mais de um, encontrar o mais próximo da terceira sexta
                    
                    # Encontrar todas as sextas do mês
                    c = calendar.Calendar(firstweekday=calendar.SUNDAY)
                    monthcal = c.monthdatescalendar(year, month)
                    fridays = [d for week in monthcal for d in week if d.weekday() == calendar.FRIDAY and d.month == month]
                    
                    if len(fridays) >= 3:
                        third_friday = fridays[2]
                        # Achar a data em 'dates' mais próxima da third_friday
                        closest_date = min(dates, key=lambda x: abs((x - third_friday).days))
                        
                        # Atualizar a mais próxima como Mensal e as outras como Semanal
                        cls.objects.filter(ativo_objeto=ativo_obj, data_expiracao=closest_date).update(classificacao_vencimento='Mensal')
                        
                        outras_datas = [d for d in dates if d != closest_date]
                        cls.objects.filter(ativo_objeto=ativo_obj, data_expiracao__in=outras_datas).update(classificacao_vencimento='Semanal')


    class Meta:
        verbose_name = _('Ativo B3')
        verbose_name_plural = _('Ativos B3')
        ordering = ['ativo_objeto', 'ticker']
        indexes = [
            models.Index(fields=['ativo_objeto', 'data_expiracao']),
            models.Index(fields=['tipo_opcao', 'preco_exercicio']),
        ]
    
    def __str__(self):
        return f"{self.ticker} - {self.preco_exercicio}"

class HistoricoImportacao(models.Model):
    data_importacao = models.DateTimeField(auto_now_add=True)
    tipo_importacao = models.CharField(max_length=50, blank=True, default='')
    arquivo_nome = models.CharField(max_length=255)
    novos = models.IntegerField(default=0)
    atualizados = models.IntegerField(default=0)
    sem_alteracao = models.IntegerField(default=0)
    detalhes = models.JSONField(default=dict) # Para guardar as alterações específicas

    class Meta:
        ordering = ['-data_importacao']

class AtivoMonitorado(models.Model):
    ticker = models.CharField(max_length=10, unique=True, help_text="Ex: PETR4, VALE3")
    nome = models.CharField(max_length=100, blank=True, null=True)
    ativo_no_dashboard = models.BooleanField(default=True, help_text="Se desmarcado, ignora na próxima importação")

    def __str__(self):
        return self.ticker

    def save(self, *args, **kwargs):
        self.ticker = self.ticker.strip().upper()  # Garante sempre maiúsculo
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Ativo Monitorado"
        #verbose_name = "Ativos Monitorados"


class HistoricoPreco(models.Model):
    # Relaciona com o cadastro que já temos. Se deletar o ativo, deleta o histórico.
    ativo = models.ForeignKey(AtivoB3, on_delete=models.CASCADE, related_name='historicos')
    data_pregao = models.DateField()
    
    # Campos de preço (usando Decimal para precisão financeira)
    abertura = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    maximo = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    fechamento = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    ajuste = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    
    # Dados de volume
    quantidade_negocios = models.IntegerField(default=0)
    volume_financeiro = models.DecimalField(max_digits=20, decimal_places=2, default=0.0)

    class Meta:
        # Garante que não teremos duas linhas para o mesmo ativo no mesmo dia
        unique_together = ('ativo', 'data_pregao')
        verbose_name = "Histórico de Preço"
        verbose_name_plural = "Históricos de Preços"

    def __str__(self):
        return f"{self.ativo.ticker} - {self.data_pregao}"