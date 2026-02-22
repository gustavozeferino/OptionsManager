from django.contrib.auth.views import LoginView, LogoutView
from django.contrib import messages
from django.utils.translation import gettext_lazy as _


class CustomLoginView(LoginView):
    """View customizada para login."""
    template_name = 'users/login.html'
    
    def form_valid(self, form):
        messages.success(self.request, _('Login realizado com sucesso!'))
        return super().form_valid(form)


class CustomLogoutView(LogoutView):
    """View customizada para logout."""
    def dispatch(self, request, *args, **kwargs):
        messages.success(request, _('Logout realizado com sucesso!'))
        return super().dispatch(request, *args, **kwargs)
