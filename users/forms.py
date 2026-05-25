from django import forms
from django.utils.translation import gettext_lazy as _
from .models import LayoutConfig

class LayoutConfigForm(forms.ModelForm):
    class Meta:
        model = LayoutConfig
        fields = ['compra_color', 'venda_color', 'call_color', 'put_color', 'ativo_color']
        widgets = {
            'compra_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color w-100', 'style': 'height: 45px;'}),
            'venda_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color w-100', 'style': 'height: 45px;'}),
            'call_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color w-100', 'style': 'height: 45px;'}),
            'put_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color w-100', 'style': 'height: 45px;'}),
            'ativo_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color w-100', 'style': 'height: 45px;'}),
        }
        labels = {
            'compra_color': _('Cor de Compra (Quantidade Positiva)'),
            'venda_color': _('Cor de Venda (Quantidade Negativa)'),
            'call_color': _('Cor de Opções de Compra (CALL)'),
            'put_color': _('Cor de Opções de Venda (PUT)'),
            'ativo_color': _('Cor de Ativos Objeto (Ações/Índices)'),
        }
