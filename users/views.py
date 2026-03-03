from django.contrib.auth.views import LoginView, LogoutView
from django.contrib import messages
from django.utils.translation import gettext_lazy as _


from django.urls import reverse_lazy

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
