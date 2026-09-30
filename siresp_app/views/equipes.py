"""
Equipes médicas: grupos de profissionais cujo repasse sai em conjunto.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from ..models import EquipeMedica, Profissional
from ..permissions import admin_required
from ..services import auditoria


@login_required
def lista(request):
    equipes = EquipeMedica.objects.prefetch_related('membros').annotate(qtd=Count('membros'))
    return render(request, 'siresp_app/equipes/lista.html', {
        'equipes': equipes,
        'sem_equipe': Profissional.objects.filter(equipe__isnull=True, ativo=True).count(),
    })


def _salvar(request, equipe=None):
    nome = request.POST.get('nome', '').strip()
    try:
        ids = {int(i) for i in request.POST.getlist('membros')}
    except ValueError:
        messages.error(request, 'Seleção inválida.')
        return redirect(request.path)

    if not nome:
        messages.error(request, 'Informe o nome da equipe.')
        return redirect(request.path)

    dup = EquipeMedica.objects.filter(nome__iexact=nome)
    if equipe:
        dup = dup.exclude(pk=equipe.pk)
    if dup.exists():
        messages.error(request, f'Já existe uma equipe chamada "{nome}".')
        return redirect(request.path)

    nova_equipe = equipe is None
    antes_nome = '' if nova_equipe else equipe.nome
    antes_membros = set() if nova_equipe else set(equipe.membros.values_list('nome', flat=True))
    if equipe is None:
        equipe = EquipeMedica()
    equipe.nome = nome
    equipe.save()

    # Um profissional só pode estar em uma equipe: ignora quem já está em outra
    ocupados = set(
        Profissional.objects.filter(pk__in=ids, equipe__isnull=False)
        .exclude(equipe=equipe).values_list('nome', flat=True)
    )
    livres = Profissional.objects.filter(pk__in=ids).filter(
        Q(equipe__isnull=True) | Q(equipe=equipe))

    Profissional.objects.filter(equipe=equipe).exclude(pk__in=livres).update(equipe=None)
    livres.update(equipe=equipe)

    if ocupados:
        messages.warning(
            request,
            'Já pertencem a outra equipe (não incluídos): ' + ', '.join(sorted(ocupados)))
    depois_membros = set(equipe.membros.values_list('nome', flat=True))
    detalhes = []
    if not nova_equipe and antes_nome != equipe.nome:
        detalhes.append({'item': '', 'campo': 'Nome', 'de': antes_nome, 'para': equipe.nome})
    for n in sorted(depois_membros - antes_membros):
        detalhes.append({'item': n, 'campo': 'Membro', 'de': '', 'para': 'incluído'})
    for n in sorted(antes_membros - depois_membros):
        detalhes.append({'item': n, 'campo': 'Membro', 'de': 'incluído', 'para': 'removido'})
    if nova_equipe or detalhes:
        auditoria.registrar(
            request, 'EQUIPE_CRIADA' if nova_equipe else 'EQUIPE_EDITADA',
            f'Equipe "{equipe.nome}" ({len(depois_membros)} profissional(is))', detalhes=detalhes)
    messages.success(request, f'Equipe "{equipe.nome}" salva com {livres.count()} profissional(is).')
    return redirect('siresp_app:equipes_lista')


def _contexto_form(equipe):
    profs = Profissional.objects.filter(ativo=True).select_related('equipe')
    return {
        'equipe': equipe,
        'profissionais': [
            {'p': p,
             'marcado': bool(equipe and p.equipe_id == equipe.pk),
             'bloqueado': bool(p.equipe_id and (not equipe or p.equipe_id != equipe.pk))}
            for p in profs
        ],
    }


@admin_required
def nova(request):
    if request.method == 'POST':
        return _salvar(request)
    return render(request, 'siresp_app/equipes/form.html', _contexto_form(None))


@admin_required
def editar(request, pk):
    equipe = get_object_or_404(EquipeMedica, pk=pk)
    if request.method == 'POST':
        return _salvar(request, equipe)
    return render(request, 'siresp_app/equipes/form.html', _contexto_form(equipe))


@admin_required
@require_POST
def remover(request, pk):
    equipe = get_object_or_404(EquipeMedica, pk=pk)
    nome = equipe.nome
    membros = list(equipe.membros.values_list('nome', flat=True))
    equipe.delete()
    auditoria.registrar(request, 'EQUIPE_EXCLUIDA',
                        f'Equipe "{nome}" excluída (membros: {", ".join(membros) or "nenhum"})')  # profissionais ficam sem equipe (SET_NULL)
    messages.success(request, f'Equipe "{nome}" removida. Os profissionais continuam na base.')
    return redirect('siresp_app:equipes_lista')
