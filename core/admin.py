from django.contrib import admin
from .models import AtivoB3
from .models import AtivoMonitorado
from .models import AcessoLog
from django import forms
from .models import HistoricoPreco, HistoricoImportacao

class AtivoB3Form(forms.ModelForm):
    class Meta:
        model = AtivoB3
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Verificamos se o campo existe antes de tentar alterá-lo
        if 'ticker' in self.fields and self.instance.pk:
            self.fields['ticker'].widget.attrs['readonly'] = True
            self.fields['ticker'].disabled = True # Garante que o Django não aceite mudanças no POST

@admin.register(AtivoB3)
class AtivoB3Admin(admin.ModelAdmin):
    form = AtivoB3Form
    list_display = ('codigo_isin', 'ticker', 'ativo_objeto', 'preco_exercicio', 'data_expiracao')
    search_fields = ('codigo_isin', 'ticker')
    list_filter = ('tipo_opcao', 'mercado', 'data_expiracao')
    
    # Isso torna o campo ticker somente leitura na interface do Admin padrão
    def get_readonly_fields(self, request, obj=None):
        if obj: # Se estiver editando um objeto existente
            return ('ticker',)
        return ()


@admin.register(AtivoMonitorado)
class AtivoMonitoradoAdmin(admin.ModelAdmin):
    # Colunas que aparecerão na lista do Admin
    list_display = ('ticker', 'nome', 'ativo_no_dashboard')
    
    # Permite editar o checkbox diretamente na lista
    list_editable = ('ativo_no_dashboard',)
    
    # Adiciona uma barra de pesquisa pelo ticker ou nome
    search_fields = ('ticker', 'nome')

@admin.register(AcessoLog)
class AcessoLogAdmin(admin.ModelAdmin):
    # Colunas que aparecerão na lista
    list_display = ('data_acesso', 'usuario', 'metodo', 'path', 'ip_address')
    
    # Filtros na lateral direita
    list_filter = ('metodo', 'data_acesso', 'usuario')
    
    # Campo de busca (busca por nome de usuário ou URL)
    search_fields = ('usuario__username', 'path', 'ip_address')
    
    # Ordenação padrão (mais recente primeiro)
    ordering = ('-data_acesso',)
    
    # Bloquear edição (Logs devem ser imutáveis para garantir a integridade)
    def has_change_permission(self, request, obj=None):
        return False

    # Opcional: Permitir apenas visualização e exclusão
    readonly_fields = ('usuario', 'path', 'metodo', 'ip_address', 'data_acesso')


@admin.register(HistoricoPreco)
class HistoricoPrecoAdmin(admin.ModelAdmin):
    # Exibe as colunas principais na lista
    list_display = ('get_ticker', 'data_pregao', 'fechamento', 'ajuste', 'quantidade_negocios', 'volume_financeiro')
    
    # Filtros laterais para facilitar a análise
    list_filter = ('data_pregao', 'ativo__ativo_objeto')
    
    # Busca pelo ticker da opção (via relacionamento com AtivoB3)
    search_fields = ('ativo__ticker', 'ativo__codigo_isin')
    
    # Ordenação: mais recente primeiro
    ordering = ('-data_pregao', 'ativo__ticker')

    # Função auxiliar para mostrar o ticker do ativo relacionado na listagem
    @admin.display(ordering='ativo__ticker', description='Ticker')
    def get_ticker(self, obj):
        return obj.ativo.ticker


@admin.register(HistoricoImportacao)
class HistoricoImportacaoAdmin(admin.ModelAdmin):
    list_display = ('data_importacao', 'tipo_importacao', 'arquivo_nome', 'novos', 'atualizados', 'sem_alteracao')
    list_filter = ('tipo_importacao', 'data_importacao')
    search_fields = ('arquivo_nome', 'tipo_importacao')
    ordering = ('-data_importacao',)
    readonly_fields = ('data_importacao', 'tipo_importacao', 'arquivo_nome', 'novos', 'atualizados', 'sem_alteracao', 'detalhes')

    def has_add_permission(self, request):
        return False
