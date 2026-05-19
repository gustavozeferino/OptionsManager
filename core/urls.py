from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('ativos/', views.lista_ativos, name='lista_ativos'),
    path('upload/', views.upload_csv, name='upload_csv'),
    path('limpar-banco/', views.limpar_ativos_nao_monitorados, name='limpar_banco'),
    path('upload-precos/', views.upload_precos, name='upload_precos'),
    path('limpar-ativos/', views.limpar_ativos_nao_monitorados, name='limpar_ativos_nao_monitorados'),
    path('remover-historico-precos-duplicados/', views.remover_historico_precos_duplicados, name='remover_historico_precos_duplicados'),
    path('logs/', views.lista_logs, name='lista_logs'),
    path('recalcular-estruturas/', views.recalcular_estruturas, name='recalcular_estruturas'),
    path('sync-precos-b3/', views.sync_precos_b3, name='sync_precos_b3'),
    path('recalcular-rolagens/', views.recalcular_rolagens, name='recalcular_rolagens'),
    path('liquidez-vencimentos/', views.liquidez_vencimentos, name='liquidez_vencimentos'),
    path('ativo/<str:ticker>/', views.detalhe_ativo, name='detalhe_ativo'),
    path('upload-open-interest/', views.upload_open_interest, name='upload_open_interest'),
    path('consultar-open-interest/', views.consultar_open_interest, name='consultar_open_interest'),
    path('grafico-open-interest/', views.grafico_open_interest, name='grafico_open_interest'),
    path('fluxo-open-interest/', views.fluxo_open_interest, name='fluxo_open_interest'),
    path('barreiras-open-interest/', views.barreiras_open_interest, name='barreiras_open_interest'),
]