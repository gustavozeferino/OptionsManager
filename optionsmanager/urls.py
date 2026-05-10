"""
URL configuration for optionsmanager project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('users/', include('users.urls')),
    path('trading/', include('trading.urls')),
    path('dadosb3/', include('dadosb3.urls')),
]
