from django.urls import path
from . import views

app_name = 'dadosb3'

urlpatterns = [
    path('upload/cadastro/', views.upload_cadastro_view, name='upload_cadastro'),
    path('upload/negocios/', views.upload_negocios_view, name='upload_negocios'),
    path('upload/posicoes/', views.upload_posicoes_view, name='upload_posicoes'),
    path('upload/cothist/', views.upload_cothist_view, name='upload_cothist'),
    path('upload/progress/<str:task_id>/', views.upload_progress, name='upload_progress'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('api/check-filename/', views.check_filename, name='check_filename'),
    path('api/tickers/', views.get_tickers, name='get_tickers'),
    path('api/chart-data/', views.get_chart_data, name='get_chart_data'),
    path('api/admin/estatisticas/', views.admin_estatisticas, name='admin_estatisticas'),
    path('api/admin/consolidar/', views.admin_consolidar, name='admin_consolidar'),
    path('api/admin/sincronizar/', views.admin_sincronizar, name='admin_sincronizar'),
]
