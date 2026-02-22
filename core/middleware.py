from .models import AcessoLog

class LogAcessoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Processa a requisição primeiro
        response = self.get_response(request)

        # 2. Só logamos se o usuário estiver autenticado (para não lotar o banco com bots)
        if request.user.is_authenticated:
            # Pegamos o IP (considerando possíveis proxies/herokus)
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0]
            else:
                ip = request.META.get('REMOTE_ADDR')

            # Salvamos no banco
            AcessoLog.objects.create(
                usuario=request.user,
                path=request.path,
                metodo=request.method,
                ip_address=ip
            )

        return response