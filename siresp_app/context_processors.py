from .permissions import eh_admin


def papel(request):
    """Disponibiliza `eh_admin` em todos os templates (menu e botões)."""
    return {'eh_admin': eh_admin(request.user) if hasattr(request, 'user') else False}
