from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings
from .models import Estrutura, Ordem

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_estrutura_padrao(sender, instance, created, **kwargs):
    """
    Cria uma Estrutura vazia padrão ("Sem Estrutura") 
    quando um novo usuário é registrado.
    """
    if created:
        Estrutura.objects.get_or_create(
            usuario=instance,
            nome='Sem Estrutura',
            defaults={'slug': 'sem-estrutura'}
        )

@receiver(post_save, sender=Ordem)
@receiver(post_delete, sender=Ordem)
def atualizar_consolidacao_ordem(sender, instance, **kwargs):
    """
    Sempre que uma ordem for salva ou deletada, disparar o
    recálculo da consolidação.
    Importação lazy de services para não gerar erro de dependência cíclica
    """
    from .services import recalcular_posicao, recalcular_estrutura
    
    # 1. Recalcula a Posição do ativo específico nesta Estrutura
    recalcular_posicao(instance.estrutura, instance.ativo)
    
    # 2. Recalcula P&L total e Snapshot da Estrutura
    recalcular_estrutura(instance.estrutura)
