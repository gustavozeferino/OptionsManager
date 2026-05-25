from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Custom User Model para o OptionsManager.
    Estende AbstractUser do Django para permitir customizações futuras.
    """
    email = models.EmailField(_('email address'), unique=True)

    @property
    def layout(self):
        config, created = LayoutConfig.objects.get_or_create(usuario=self)
        return config
    
    class Meta:
        verbose_name = _('Usuário')
        verbose_name_plural = _('Usuários')
        ordering = ['username']


class LayoutConfig(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='layout_config')
    compra_color = models.CharField(max_length=7, default='#10b981', verbose_name=_('Cor de Compra'))
    venda_color = models.CharField(max_length=7, default='#ef4444', verbose_name=_('Cor de Venda'))
    call_color = models.CharField(max_length=7, default='#00d4aa', verbose_name=_('Cor de CALL'))
    put_color = models.CharField(max_length=7, default='#f59e0b', verbose_name=_('Cor de PUT'))
    ativo_color = models.CharField(max_length=7, default='#6c63ff', verbose_name=_('Cor de Ativo'))

    class Meta:
        verbose_name = _('Configuração de Layout')
        verbose_name_plural = _('Configurações de Layout')

    def __str__(self):
        return f"Layout de {self.usuario.username}"
