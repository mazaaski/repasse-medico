"""
Base de profissionais e situação dos repasses no mês.
"""
from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from ..models import Profissional
from ..permissions import admin_required
from ..services import auditoria
from ..services.profissionais_service import garantir_profissional, situacao_mes

MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho',
         'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']


@login_required
def lista(request):
    hoje = date.today()
    try:
        ano = int(request.GET.get('ano', hoje.year))
        mes = int(request.GET.get('mes', hoje.month))
        date(ano, mes, 1)
    except ValueError:
        ano, mes = hoje.year, hoje.month

    situacoes = situacao_mes(request.user, ano, mes)
    contagem = {'finalizado': 0, 'rascunho': 0, 'extraido': 0, 'pendente': 0}
    for s in situacoes:
        contagem[s['status']] += 1

    filtro = request.GET.get('status', '')
    if filtro in contagem:
        situacoes = [s for s in situacoes if s['status'] == filtro]

    return render(request, 'siresp_app/profissionais/lista.html', {
        'situacoes': situacoes,
        'contagem': contagem,
        'ano': ano,
        'mes': mes,
        'meses': list(enumerate(MESES, start=1)),
        'anos': range(hoje.year - 3, hoje.year + 1),
        'filtro': filtro,
        'inativos': Profissional.objects.filter(ativo=False),
        'total_base': Profissional.objects.count(),
    })


@admin_required
@require_POST
def novo(request):
    nome = request.POST.get('nome', '').strip()
    obj, criado = garantir_profissional(nome)
    if not obj:
        messages.error(request, 'Informe o nome do profissional.')
    elif criado:
        auditoria.registrar(request, 'PROFISSIONAL_ALTERADO', f'"{obj.nome}" adicionado à base',
                            profissional=obj.nome)
        messages.success(request, f'"{obj.nome}" adicionado à base.')
    else:
        messages.info(request, f'"{obj.nome}" já está na base.')
    return redirect('siresp_app:profissionais_lista')


@admin_required
@require_POST
def alternar(request, pk):
    p = get_object_or_404(Profissional, pk=pk)
    p.ativo = not p.ativo
    p.save(update_fields=['ativo'])
    auditoria.registrar(request, 'PROFISSIONAL_ALTERADO',
                        f'"{p.nome}" {"reativado" if p.ativo else "desativado"}', profissional=p.nome)
    messages.success(
        request, f'"{p.nome}" {"reativado" if p.ativo else "desativado"}.'
    )
    return redirect('siresp_app:profissionais_lista')


@admin_required
@require_POST
def remover(request, pk):
    p = get_object_or_404(Profissional, pk=pk)
    p.delete()
    auditoria.registrar(request, 'PROFISSIONAL_ALTERADO', f'"{p.nome}" removido da base',
                        profissional=p.nome)
    messages.success(request, f'"{p.nome}" removido da base.')
    return redirect('siresp_app:profissionais_lista')
