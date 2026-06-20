from django.urls import path
from . import views

app_name = 'trading'

urlpatterns = [
    # Dashboard Principal do Usuário
    path('dashboard/', views.dashboard, name='dashboard'),

    # Estruturas
    path('estruturas/', views.dashboard_estruturas, name='dashboard_estruturas'),
    path('estruturas/nova/', views.criar_estrutura, name='criar_estrutura'),
    
    # Detalhe da Estrutura
    path('estruturas/<slug:slug>/', views.detalhe_estrutura, name='detalhe_estrutura'),
    path('estruturas/<slug:slug>/adicionar-ordem/', views.adicionar_ordem, name='adicionar_ordem_manual'),
    path('estruturas/<slug:slug>/alternar-status/', views.alternar_status_estrutura, name='alternar_status_estrutura'),
    
    # AJAX / API
    path('api/ativos/', views.buscar_ativos, name='api_buscar_ativos'),
    path('api/ativos/<str:codigo_isin>/', views.detalhe_ativo_json, name='api_detalhe_ativo'),
    
    # Upload e Gestão de Ordens
    path('upload-ordens/', views.upload_ordens, name='upload_ordens'),
    path('alocar-orfas/', views.alocar_ordens_orfas, name='alocar_orfas'),
    
    # Ações em Ordens
    path('ordens/<int:ordem_id>/editar/', views.editar_ordem, name='editar_ordem'),
    path('ordens/<int:ordem_id>/excluir/', views.excluir_ordem, name='excluir_ordem'),

    # Relatórios
    path('relatorios/', views.relatorio_performance, name='relatorio_performance'),

    # Posições
    path('posicoes/', views.posicoes_view, name='posicoes'),

    # Spreads
    path('spreads/', views.lista_rolagens, name='lista_rolagens'),
    path('spreads/novo/', views.criar_rolagem, name='criar_rolagem'),
    path('spreads/recalcular-todos/', views.recalcular_todas_rolagens_view, name='recalcular_todas_rolagens'),
    path('spreads/<slug:slug>/', views.detalhe_rolagem, name='detalhe_rolagem'),
    path('spreads/<slug:slug>/editar/', views.editar_rolagem, name='editar_rolagem'),
    path('spreads/<slug:slug>/arquivar/', views.arquivar_rolagem, name='arquivar_rolagem'),
    path('spreads/<slug:slug>/excluir/', views.excluir_rolagem, name='excluir_rolagem'),
    # Backup e Restauração
    path('backup/', views.backup_estruturas, name='backup_estruturas'),
    path('backup/exportar/', views.exportar_backup, name='exportar_backup'),
    path('backup/restaurar/', views.restaurar_backup, name='restaurar_backup'),
]
