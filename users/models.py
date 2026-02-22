from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Custom User Model para o OptionsManager.
    Estende AbstractUser do Django para permitir customizações futuras.
    """
    email = models.EmailField(_('email address'), unique=True)
    
    class Meta:
        verbose_name = _('Usuário')
        verbose_name_plural = _('Usuários')
        ordering = ['username']
