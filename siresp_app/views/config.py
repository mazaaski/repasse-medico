import os
from decimal import Decimal
import re
import tempfile
import unicodedata

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import models
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from ..permissions import admin_required, eh_admin
from ..services import auditoria
from ..models import (
    GrupoValor, EspecialidadeGrupo, EspecialidadeConhecida,
)


def _normalizar(texto):
    if texto is None:
        return ""
    texto = str(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip().upper()


# =========================================================
# GRUPOS
# =========================================================
@login_required
def lista_grupos(request):
    grupos = GrupoValor.objects.prefetch_related('especialidades').all()
    especialidades = EspecialidadeConhecida.objects.all()
    return render(request, 'siresp_app/config/lista.html', {
        'grupos': grupos,
        'especialidades': especialidades,
    })


@admin_required
def novo_grupo(request):
    if request.method == 'POST':
        return _salvar_grupo(request)
    return render(request, 'siresp_app/config/form.html', {
        'grupo': None,
        'especialidades': EspecialidadeConhecida.objects.all(),
        'selecionadas': set(),
    })


@admin_required
def editar_grupo(request, pk):
    grupo = get_object_or_404(GrupoValor, pk=pk)
    if request.method == 'POST':
        return _salvar_grupo(request, grupo)

    selecionadas = set(grupo.especialidades.values_list('nome', flat=True))
    return render(request, 'siresp_app/config/form.html', {
        'grupo': grupo,
        'especialidades': EspecialidadeConhecida.objects.all(),
        'selecionadas': selecionadas,
    })


def _salvar_grupo(request, grupo=None):
    nome = request.POST.get('nome', '').strip()
    valor_base = request.POST.get('valor_base', '').replace(',', '.').strip()
    bonus = request.POST.get('bonus', '').replace(',', '.').strip()
    especialidades = request.POST.getlist('especialidades')

    if not nome:
        messages.error(request, 'Informe um nome para o grupo.')
        return redirect(request.path)

    try:
        valor_base = float(valor_base or 0)
        bonus = float(bonus or 0)
    except ValueError:
        messages.error(request, 'Valor base ou bônus inválido.')
        return redirect(request.path)

    qs = GrupoValor.objects.filter(nome__iexact=nome)
    if grupo:
        qs = qs.exclude(pk=grupo.pk)
    if qs.exists():
        messages.error(request, f'Já existe um grupo chamado "{nome}".')
        return redirect(request.path)

    conflitos = EspecialidadeGrupo.objects.filter(nome__in=especialidades)
    if grupo:
        conflitos = conflitos.exclude(grupo=grupo)
    conflitos_lista = list(conflitos.values_list('nome', flat=True))
    if conflitos_lista:
        messages.error(
            request,
            'As seguintes especialidades já estão em outro grupo: '
            + ', '.join(conflitos_lista)
        )
        return redirect(request.path)

    novo = grupo is None
    if novo:
        antes = {}
    else:
        antes = {
            'nome': grupo.nome, 'valor_base': grupo.valor_base, 'bonus': grupo.bonus,
            'especialidades': ', '.join(sorted(grupo.especialidades.values_list('nome', flat=True))),
        }
    if grupo is None:
        grupo = GrupoValor()
    grupo.nome = nome
    grupo.valor_base = valor_base
    grupo.bonus = bonus
    grupo.save()

    grupo.especialidades.all().delete()
    for esp_nome in especialidades:
        EspecialidadeGrupo.objects.create(grupo=grupo, nome=esp_nome)

    depois = {
        'nome': grupo.nome, 'valor_base': Decimal(str(valor_base)), 'bonus': Decimal(str(bonus)),
        'especialidades': ', '.join(sorted(especialidades)),
    }
    rotulos = {'nome': 'Nome', 'valor_base': 'Valor base', 'bonus': 'Bônus 100%',
               'especialidades': 'Especialidades'}
    if novo:
        auditoria.registrar(
            request, 'GRUPO_CRIADO',
            f'Grupo "{grupo.nome}": base R$ {depois["valor_base"]:.2f}, bônus R$ {depois["bonus"]:.2f}',
            detalhes=auditoria.diff_simples({}, depois, rotulos))
    else:
        mudancas = auditoria.diff_simples(antes, depois, rotulos)
        if mudancas:
            auditoria.registrar(request, 'GRUPO_EDITADO', f'Grupo "{grupo.nome}" editado',
                                detalhes=mudancas)

    messages.success(request, 'Grupo salvo com sucesso.')
    return redirect('siresp_app:config_lista')


@admin_required
@require_POST
def remover_grupo(request, pk):
    grupo = get_object_or_404(GrupoValor, pk=pk)
    nome = grupo.nome
    resumo = f'base R$ {grupo.valor_base}, bônus R$ {grupo.bonus}'
    grupo.delete()
    auditoria.registrar(request, 'GRUPO_EXCLUIDO', f'Grupo "{nome}" excluído ({resumo})')
    messages.success(request, f'Grupo "{nome}" removido.')
    return redirect('siresp_app:config_lista')


@admin_required
@require_POST
def excluir_grupos(request):
    """Exclui os grupos marcados (ou todos, com todos=1)."""
    if request.POST.get('todos') == '1':
        qs = GrupoValor.objects.all()
    else:
        try:
            ids = [int(i) for i in request.POST.getlist('grupo_ids')]
        except ValueError:
            messages.error(request, 'IDs inválidos.')
            return redirect('siresp_app:config_lista')
        if not ids:
            messages.warning(request, 'Selecione pelo menos um grupo.')
            return redirect('siresp_app:config_lista')
        qs = GrupoValor.objects.filter(pk__in=ids)

    nomes = list(qs.values_list('nome', flat=True))
    qtd = len(nomes)
    qs.delete()
    auditoria.registrar(request, 'GRUPO_EXCLUIDO',
                        f'{qtd} grupo(s) excluído(s): ' + ', '.join(nomes))
    messages.success(request, f'{qtd} grupo(s) excluído(s).')
    return redirect('siresp_app:config_lista')


# =========================================================
# ESPECIALIDADES CONHECIDAS
# =========================================================
@login_required
def lista_especialidades(request):
    esp = EspecialidadeConhecida.objects.all()
    return render(request, 'siresp_app/config/especialidades.html', {
        'especialidades': esp,
    })


@admin_required
def nova_especialidade(request):
    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        if nome:
            EspecialidadeConhecida.objects.get_or_create(nome=nome)
            messages.success(request, f'Especialidade "{nome}" adicionada.')
        return redirect('siresp_app:config_especialidades')
    return redirect('siresp_app:config_especialidades')


# =========================================================
# IMPORTAÇÃO
# =========================================================
@login_required
def importar_planilha(request):
    from ..services.planilha_service import ler_planilha
    from ..services.valores_service import registrar_regras

    if request.method == 'POST' and not eh_admin(request.user):
        messages.error(request, 'Somente administradores podem importar a planilha.')
        return redirect('siresp_app:config_importar')

    if request.method == 'POST':
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            messages.error(request, 'Selecione um arquivo.')
            return redirect('siresp_app:config_importar')

        nome = arquivo.name
        ext = os.path.splitext(nome)[1].lower()
        if ext not in ('.xls', '.xlsx', '.xlsm'):
            messages.error(request, f'Extensão não suportada: {ext}')
            return redirect('siresp_app:config_importar')

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            for chunk in arquivo.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            linhas = ler_planilha(tmp_path)
        except ImportError as e:
            messages.error(request, f'Biblioteca faltando: {e}')
            return redirect('siresp_app:config_importar')
        except Exception as e:
            messages.error(request, f'Erro ao ler planilha: {e}')
            return redirect('siresp_app:config_importar')
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        if not linhas:
            messages.warning(
                request,
                'Nenhuma linha válida encontrada com PROFISSIONAL, '
                'ESPECIALIDADE e INTERVALO ENTRE AS CONSULTAS.'
            )
            return redirect('siresp_app:config_importar')

        stats = registrar_regras(linhas)
        auditoria.registrar(
            request, 'IMPORTACAO',
            f'Planilha "{nome}": {stats["linhas"]} linhas, {stats["pares"]} pares, '
            f'{stats["novos_prof"]} profissionais novos')
        messages.success(
            request,
            f'✅ Importação concluída! '
            f'{stats["linhas"]} linhas, {stats["pares"]} pares, '
            f'{stats["novas_esp"]} especialidades novas, '
            f'{stats["novos_prof"]} profissionais novos na base.'
        )
        return redirect('siresp_app:config_regras')

    return render(request, 'siresp_app/config/importar.html')


# =========================================================
# REGRAS
# =========================================================
@login_required
def lista_regras(request):
    from ..models import RegraMinuto

    busca = request.GET.get('q', '').strip()
    qs = RegraMinuto.objects.all()

    if busca:
        busca_n = _normalizar(busca)
        qs = qs.filter(
            models.Q(profissional_norm__icontains=busca_n) |
            models.Q(especialidade_norm__icontains=busca_n)
        )

    total = RegraMinuto.objects.count()

    return render(request, 'siresp_app/config/regras.html', {
        'regras': qs[:500],
        'total': total,
        'busca': busca,
        'especialidades': EspecialidadeConhecida.objects.all(),
    })


@admin_required
@require_POST
def limpar_regras(request):
    from ..services.valores_service import limpar_regras as _limpar
    qtd = _limpar()
    auditoria.registrar(request, 'REGRAS_LIMPAS', f'{qtd} regra(s) de minutos apagadas')
    messages.success(request, f'{qtd} regras removidas.')
    return redirect('siresp_app:config_regras')


# =========================================================
# REGRAS — CRIAR / EDITAR / DELETAR MANUALMENTE
# =========================================================
@admin_required
@require_POST
def nova_regra(request):
    from ..services.regras_service import criar_ou_atualizar_regra

    profissional = request.POST.get('profissional', '').strip()
    especialidade = request.POST.get('especialidade', '').strip()
    minutos_str = request.POST.get('minutos', '').strip()
    valor_base_str = request.POST.get('valor_base', '').strip()
    bonus_str = request.POST.get('bonus', '').strip()

    try:
        minutos = [
            int(m.strip())
            for m in re.split(r'[,;\s]+', minutos_str)
            if m.strip()
        ]
    except ValueError:
        messages.error(request, 'Minutos inválidos.')
        return redirect('siresp_app:config_regras')

    valor_base = None
    if valor_base_str:
        try:
            valor_base = float(valor_base_str.replace(',', '.'))
        except ValueError:
            messages.error(request, 'Valor base inválido.')
            return redirect('siresp_app:config_regras')

    bonus = None
    if bonus_str:
        try:
            bonus = float(bonus_str.replace(',', '.'))
        except ValueError:
            messages.error(request, 'Bônus inválido.')
            return redirect('siresp_app:config_regras')

    try:
        obj, criado = criar_ou_atualizar_regra(
            profissional, especialidade, minutos,
            valor_base, bonus,
        )
        auditoria.registrar(
            request, 'REGRA_CRIADA' if criado else 'REGRA_EDITADA',
            f'{obj.profissional_norm} | {obj.especialidade_norm}',
            profissional=obj.profissional_norm,
            detalhes=[
                {'item': obj.especialidade_norm, 'campo': 'Minutos', 'de': '', 'para': obj.minutos_formatados},
                {'item': obj.especialidade_norm, 'campo': 'Valor base (override)', 'de': '',
                 'para': str(obj.valor_base_override or '')},
                {'item': obj.especialidade_norm, 'campo': 'Bônus (override)', 'de': '',
                 'para': str(obj.bonus_override or '')},
            ])
        if criado:
            messages.success(request, f'Regra criada: {obj}')
        else:
            messages.success(request, f'Regra atualizada: {obj}')

        if especialidade:
            EspecialidadeConhecida.objects.get_or_create(nome=especialidade)
        from ..services.profissionais_service import garantir_profissional
        garantir_profissional(profissional)
    except Exception as e:
        messages.error(request, f'Erro: {e}')

    return redirect('siresp_app:config_regras')


@admin_required
def editar_regra(request, pk):
    from ..models import RegraMinuto
    from ..services.regras_service import criar_ou_atualizar_regra

    regra = get_object_or_404(RegraMinuto, pk=pk)

    if request.method == 'POST':
        profissional = request.POST.get('profissional', '').strip()
        especialidade = request.POST.get('especialidade', '').strip()
        minutos_str = request.POST.get('minutos', '').strip()
        valor_base_str = request.POST.get('valor_base', '').strip()
        bonus_str = request.POST.get('bonus', '').strip()

        try:
            minutos = [
                int(m.strip())
                for m in re.split(r'[,;\s]+', minutos_str)
                if m.strip()
            ]
        except ValueError:
            messages.error(request, 'Minutos inválidos.')
            return redirect('siresp_app:config_regras')

        valor_base = None
        if valor_base_str:
            try:
                valor_base = float(valor_base_str.replace(',', '.'))
            except ValueError:
                pass

        bonus = None
        if bonus_str:
            try:
                bonus = float(bonus_str.replace(',', '.'))
            except ValueError:
                pass

        try:
            antes_regra = {
                'prof': regra.profissional_norm, 'esp': regra.especialidade_norm,
                'minutos': regra.minutos_formatados,
                'base': regra.valor_base_override if regra.valor_base_override is not None else '',
                'bonus': regra.bonus_override if regra.bonus_override is not None else '',
            }
            prof_n = _normalizar(profissional)
            esp_n = _normalizar(especialidade)
            if not prof_n or not esp_n or not minutos:
                raise ValueError('Profissional, especialidade e minutos são obrigatórios.')
            if (prof_n, esp_n) != (regra.profissional_norm, regra.especialidade_norm):
                # Chave mudou: remove a antiga para não deixar regra duplicada
                regra.delete()
            nova_obj, _ = criar_ou_atualizar_regra(
                profissional, especialidade, minutos,
                valor_base, bonus,
            )
            depois_regra = {
                'prof': nova_obj.profissional_norm, 'esp': nova_obj.especialidade_norm,
                'minutos': nova_obj.minutos_formatados,
                'base': nova_obj.valor_base_override if nova_obj.valor_base_override is not None else '',
                'bonus': nova_obj.bonus_override if nova_obj.bonus_override is not None else '',
            }
            mudancas = auditoria.diff_simples(antes_regra, depois_regra, {
                'prof': 'Profissional', 'esp': 'Especialidade', 'minutos': 'Minutos',
                'base': 'Valor base (override)', 'bonus': 'Bônus (override)'})
            if mudancas:
                auditoria.registrar(
                    request, 'REGRA_EDITADA',
                    f'{nova_obj.profissional_norm} | {nova_obj.especialidade_norm}',
                    profissional=nova_obj.profissional_norm, detalhes=mudancas)
            messages.success(request, 'Regra atualizada.')
        except Exception as e:
            messages.error(request, f'Erro: {e}')

        return redirect('siresp_app:config_regras')

    return render(request, 'siresp_app/config/regra_editar.html', {
        'regra': regra,
        'especialidades': EspecialidadeConhecida.objects.all(),
    })


@admin_required
@require_POST
def deletar_regra(request, pk):
    from ..services.regras_service import deletar_regra as _del
    from ..models import RegraMinuto
    alvo = RegraMinuto.objects.filter(pk=pk).first()
    desc = f'{alvo.profissional_norm} | {alvo.especialidade_norm} ({alvo.minutos_formatados} min)' if alvo else f'#{pk}'
    _del(pk)
    auditoria.registrar(request, 'REGRA_EXCLUIDA', desc,
                        profissional=alvo.profissional_norm if alvo else '')
    messages.success(request, 'Regra removida.')
    return redirect('siresp_app:config_regras')