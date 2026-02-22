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
    path('ativo/<str:ticker>/', views.detalhe_ativo, name='detalhe_ativo'),
]