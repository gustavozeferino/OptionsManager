from django.contrib.auth.views import LoginView, LogoutView
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.urls import reverse_lazy
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .forms import LayoutConfigForm

class CustomLoginView(LoginView):
    """View customizada para login."""
    template_name = 'users/login.html'
    
    def form_valid(self, form):
        messages.success(self.request, _('Login realizado com sucesso!'))
        return super().form_valid(form)
        
    def get_success_url(self):
        url = self.get_redirect_url()
        if url:
            return url
        if self.request.user.is_superuser or self.request.user.is_staff:
            return reverse_lazy('core:home')
        return reverse_lazy('trading:dashboard_estruturas')


class CustomLogoutView(LogoutView):
    """View customizada para logout."""
    def dispatch(self, request, *args, **kwargs):
        messages.success(request, _('Logout realizado com sucesso!'))
        return super().dispatch(request, *args, **kwargs)


@login_required
def customizar_layout(request):
    """View para customização de cores do layout pelo usuário."""
    layout_config = request.user.layout
    
    if request.method == 'POST':
        if 'reset_defaults' in request.POST:
            layout_config.compra_color = '#10b981'
            layout_config.venda_color = '#ef4444'
            layout_config.call_color = '#00d4aa'
            layout_config.put_color = '#f59e0b'
            layout_config.ativo_color = '#6c63ff'
            layout_config.save()
            messages.success(request, _('Cores restauradas para o padrão com sucesso!'))
            return redirect('users:customizar_layout')
            
        form = LayoutConfigForm(request.POST, instance=layout_config)
        if form.is_valid():
            form.save()
            messages.success(request, _('Cores do layout salvas com sucesso!'))
            return redirect('users:customizar_layout')
    else:
        form = LayoutConfigForm(instance=layout_config)
        
    return render(request, 'users/customizar_layout.html', {
        'form': form,
        'layout_config': layout_config
    })
