from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required


def login_view(request):
    if request.user.is_authenticated:
        return redirect('siresp_app:home')

    if request.method == 'POST':
        usuario = request.POST.get('usuario', '').strip()
        senha = request.POST.get('senha', '')
        user = authenticate(request, username=usuario, password=senha)
        if user is not None:
            login(request, user)
            return redirect('siresp_app:home')
        else:
            messages.error(request, 'Usuário ou senha inválidos.')

    return render(request, 'siresp_app/login.html')


def logout_view(request):
    # Fecha a sessão SIRESP do usuário antes de sair
    try:
        from ..services import scraper_service
        scraper_service.fechar_sessao(request.user)
    except Exception:
        pass

    logout(request)
    return redirect('siresp_app:login')


@login_required
def home_view(request):
    # Redireciona pra Produção
    return redirect('siresp_app:producao_home')