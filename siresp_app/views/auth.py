from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages

from ..services import auditoria


def login_view(request):
    if request.user.is_authenticated:
        return redirect('siresp_app:home')

    if request.method == 'POST':
        usuario = request.POST.get('usuario', '').strip()
        senha = request.POST.get('senha', '')
        user = authenticate(request, username=usuario, password=senha)
        if user is not None:
            login(request, user)
            auditoria.registrar(request, 'LOGIN', 'Login no sistema')
            return redirect('siresp_app:home')
        else:
            auditoria.registrar_como(usuario, request, 'LOGIN_FALHA',
                                     'Usuário ou senha inválidos')
            messages.error(request, 'Usuário ou senha inválidos.')

    return render(request, 'siresp_app/login.html')


def logout_view(request):
    # Fecha a sessão SIRESP do usuário antes de sair
    try:
        from ..services import scraper_service
        scraper_service.fechar_sessao(request.user)
    except Exception:
        pass

    if request.user.is_authenticated:
        auditoria.registrar(request, 'LOGOUT', 'Logout')
    logout(request)
    return redirect('siresp_app:login')
