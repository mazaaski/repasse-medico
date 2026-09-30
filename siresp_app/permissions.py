"""
Papéis do sistema.

Princípio: TODOS ENXERGAM AS MESMAS TELAS E DADOS; o que muda é o que cada um pode FAZER.

- Usuário comum: vê tudo (painel e relatórios de todos os usuários, cadastros,
  regras, grupos, equipes, auditoria) em modo consulta e opera o próprio fluxo
  do mês: extrair, gerar/editar/finalizar os SEUS repasses e exportar Excel/PDF.
- Administrador (is_superuser ou is_staff): o mesmo, mais o direito de ALTERAR:
    * reabrir repasses finalizados (com motivo registrado);
    * grupos de valores, regras de minutos, importação de planilha, equipes
      médicas e a base de profissionais;
    * usuários e permissões (admin do Django).
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect


def eh_admin(user):
    return bool(user.is_authenticated and (user.is_superuser or user.is_staff))


def admin_required(view=None, *, json=False):
    """
    Exige login + administrador.
    json=True: responde JSON (para endpoints chamados por fetch) em vez de redirecionar.
    """
    def decorador(func):
        @wraps(func)
        @login_required
        def _view(request, *args, **kwargs):
            if not eh_admin(request.user):
                if json:
                    return JsonResponse(
                        {'ok': False, 'mensagem': 'Somente administradores podem fazer isso.'},
                        status=403)
                messages.error(request, 'Acesso restrito a administradores.')
                return redirect('siresp_app:home')
            return func(request, *args, **kwargs)
        return _view

    return decorador(view) if view else decorador


def repasses_visiveis(user):
    """Todos os usuários autenticados consultam os repasses de todos (edição é só do dono)."""
    from .models import Repasse
    return Repasse.objects.all()
