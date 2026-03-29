from django.urls import path
from . import views

app_name = 'trading'

urlpatterns = [
    # Dashboard (Lista de Estruturas)
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
    path('ordens/<int:ordem_id>/excluir/', views.excluir_ordem, name='excluir_ordem'),

    # Relatórios
    path('relatorios/', views.relatorio_performance, name='relatorio_performance'),
]
