from django.urls import path
from . import views

app_name = 'dadosb3'

urlpatterns = [
    path('upload/', views.upload_view, name='upload'),
    path('upload/progress/<str:task_id>/', views.upload_progress, name='upload_progress'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('api/tickers/', views.get_tickers, name='get_tickers'),
    path('api/chart-data/', views.get_chart_data, name='get_chart_data'),
]
