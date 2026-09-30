"""
Repasse em lote: cria os repasses de várias extrações de uma vez, aplicando
regras de minutos/valores e marcando as especialidades de cada profissional,
e mostra um relatório consolidado.
"""
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import Extracao, Repasse
from ..services import repasse_service, auditoria
from ..services.resumo_service import linhas_resumo, anexar_resumo_planilha
from ..services.profissionais_service import extracoes_do_mes, agrupar_por_equipe
from .repasse import _listar_ambiguidades

MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho',
         'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']


def _mes_ano(request):
    hoje = date.today()
    try:
        ano = int(request.GET.get('ano', hoje.year))
        mes = int(request.GET.get('mes', hoje.month))
        date(ano, mes, 1)
    except ValueError:
        ano, mes = hoje.year, hoje.month
    return ano, mes


@login_required
def lote_home(request):
    ano, mes = _mes_ano(request)
    extracoes = extracoes_do_mes(request.user, ano, mes)
    linhas = [{'ext': e, 'repasse': getattr(e, 'repasse', None)} for e in extracoes]

    return render(request, 'siresp_app/repasse/lote.html', {
        'linhas': linhas,
        'sem_repasse': sum(1 for l in linhas if not l['repasse']),
        'ids_mes': ','.join(str(l['repasse'].pk) for l in linhas if l['repasse']),
        'competencia_padrao': repasse_service.competencia_padrao().strftime('%Y-%m'),
        'rascunhos': sum(1 for l in linhas if l['repasse'] and not l['repasse'].finalizado),
        'ano': ano,
        'mes': mes,
        'meses': list(enumerate(MESES, start=1)),
        'anos': range(date.today().year - 3, date.today().year + 1),
    })


@login_required
@require_POST
def lote_gerar(request):
    try:
        ids = [int(i) for i in request.POST.getlist('extracao_ids')]
    except ValueError:
        messages.error(request, 'IDs inválidos.')
        return redirect('siresp_app:repasse_lote')

    if not ids:
        messages.warning(request, 'Selecione pelo menos uma extração.')
        return redirect('siresp_app:repasse_lote')

    extracoes = list(
        Extracao.objects.filter(pk__in=ids, usuario_web=request.user)
        .select_related('repasse')
    )
    criados, refeitos, ignorados = repasse_service.criar_repasses_lote(
        request.user, extracoes)

    for r in criados:
        auditoria.registrar(request, 'REPASSE_CRIADO', 'Repasse gerado em lote', repasse=r)
    for r in refeitos:
        auditoria.registrar(request, 'REPASSE_REFEITO',
                            'Rascunho refeito em lote (ajustes manuais descartados)', repasse=r)
    if refeitos:
        messages.info(request, f'{len(refeitos)} rascunho(s) refeito(s) com as regras atuais.')
    if ignorados:
        messages.warning(
            request,
            f'{len(ignorados)} finalizado(s) não foi(foram) alterado(s) '
            '(reabra o repasse para refazer): '
            + ', '.join(e.medico_nome for e in ignorados)
        )

    gerados = criados + refeitos
    if not gerados:
        messages.warning(request, 'Nenhum repasse foi gerado.')
        return redirect('siresp_app:repasse_lote')

    return redirect(
        reverse('siresp_app:repasse_lote_relatorio') + '?ids='
        + ','.join(str(r.pk) for r in gerados)
    )


@login_required
@require_POST
def lote_finalizar(request):
    """Finaliza os repasses (rascunho) das extrações marcadas, com competência."""
    try:
        ids = [int(i) for i in request.POST.getlist('extracao_ids')]
    except ValueError:
        messages.error(request, 'IDs inválidos.')
        return redirect('siresp_app:repasse_lote')

    origem = request.POST.get('voltar', '')
    destino = redirect('siresp_app:repasse_lote')
    if not ids:
        messages.warning(request, 'Selecione pelo menos um repasse.')
        return destino

    try:
        competencia = repasse_service.parse_competencia(request.POST.get('competencia'))
    except ValueError as e:
        messages.error(request, str(e))
        if origem == 'relatorio':
            return redirect(reverse('siresp_app:repasse_lote_relatorio') + '?ids='
                            + request.POST.get('ids', ''))
        return destino

    repasses = list(Repasse.objects.filter(
        extracao_id__in=ids, usuario_web=request.user).select_related('extracao'))
    sem_repasse = len(set(ids)) - len(repasses)

    finalizados, ja, vazios = [], [], []
    for r in repasses:
        if r.finalizado:
            ja.append(r)
            continue
        ok, _ = repasse_service.finalizar_repasse(r, competencia)
        (finalizados if ok else vazios).append(r)
        if ok:
            auditoria.registrar(
                request, 'REPASSE_FINALIZADO',
                f'Finalizado em lote com competência {competencia:%m/%Y}: '
                f'{r.horas_total_final} h, R$ {r.valor_total_final}',
                repasse=r,
                detalhes=[{'item': '', 'campo': 'Competência', 'de': '', 'para': f'{competencia:%m/%Y}'},
                          {'item': '', 'campo': 'Total (final)', 'de': '',
                           'para': f'{r.valor_total_final:.2f}'}])

    if finalizados:
        messages.success(
            request,
            f'{len(finalizados)} repasse(s) finalizado(s) com competência '
            f'{competencia.strftime("%m/%Y")}. Excel liberado.')
    if vazios:
        messages.warning(
            request,
            'Sem linhas marcadas (não finalizados): '
            + ', '.join(r.extracao.medico_nome for r in vazios))
    if sem_repasse:
        messages.warning(
            request, f'{sem_repasse} extração(ões) selecionada(s) ainda não têm repasse: gere-o primeiro.')
    if ja and not finalizados:
        messages.info(request, 'Os repasses selecionados já estavam finalizados.')

    alvo = finalizados + ja
    if not alvo:
        return destino
    return redirect(reverse('siresp_app:repasse_lote_relatorio') + '?ids='
                    + ','.join(str(r.pk) for r in alvo))


def _montar_relatorio(request):
    """Lê ?ids=1,2,3 e monta um bloco por profissional."""
    if request.GET.get('mes') and request.GET.get('ano'):
        ano, mes = _mes_ano(request)
        ids = [e.repasse.pk for e in extracoes_do_mes(request.user, ano, mes)
               if getattr(e, 'repasse', None)]
    else:
        try:
            ids = [int(i) for i in request.GET.get('ids', '').split(',') if i.strip()]
        except ValueError:
            ids = []

    # Consulta liberada para todos; edição/finalização continuam só para o dono (ver 'bloqueado').
    repasses = (Repasse.objects.filter(pk__in=ids)
                .select_related('extracao', 'usuario_web').order_by('extracao__medico_nome'))

    blocos = []
    tot_horas = Decimal('0')
    tot_valor = Decimal('0')
    for r in repasses:
        itens = list(r.itens.all())
        blocos.append({
            'repasse': r,
            'extracao': r.extracao,
            'itens': itens,
            'bloqueado': r.finalizado or r.usuario_web_id != request.user.id,
            'outro_dono': r.usuario_web_id != request.user.id,
            'aplicadas': [i for i in itens if i.marcado],
            'sem_regra': [i for i in itens if i.faltou_regra],
            'ambiguas': [a['esp'] for a in _listar_ambiguidades(r)],
            'horas': r.horas_total_final,
            'valor': r.valor_total_final,
        })
        tot_horas += r.horas_total_final
        tot_valor += r.valor_total_final
    return blocos, tot_horas, tot_valor, ids


def _grupos(blocos):
    """Agrupa os blocos por equipe (avulsos por último), com totais."""
    return agrupar_por_equipe(
        blocos,
        chave_nome=lambda b: b['extracao'].medico_nome,
        valor_horas=lambda b: b['horas'],
        valor_total=lambda b: b['valor'],
    )


def _resumo(grupos):
    return linhas_resumo(
        grupos,
        nome_item=lambda b: b['extracao'].medico_nome,
        horas_item=lambda b: b['horas'],
        valor_item=lambda b: b['valor'],
        id_item=lambda b: b['repasse'].pk,
    )


@login_required
def lote_relatorio(request):
    blocos, tot_horas, tot_valor, ids = _montar_relatorio(request)
    if not blocos:
        messages.warning(request, 'Nenhum repasse encontrado para o relatório.')
        return redirect('siresp_app:repasse_lote')

    return render(request, 'siresp_app/repasse/lote_relatorio.html', {
        'blocos': blocos,
        'grupos': _grupos(blocos),
        'resumo': _resumo(_grupos(blocos)),
        'tot_horas': tot_horas,
        'tot_valor': tot_valor,
        'ids': ','.join(map(str, ids)),
        'qtd_sem_regra': sum(len(b['sem_regra']) for b in blocos),
        'todos_finalizados': all(b['repasse'].finalizado for b in blocos),
        'qtd_rascunho': sum(1 for b in blocos if not b['repasse'].finalizado),
        'competencia_padrao': repasse_service.competencia_padrao().strftime('%Y-%m'),
    })


def _exigir_finalizados(request, blocos, ids, o_que):
    """Redireciona de volta ao relatório se ainda houver rascunho."""
    if all(b['repasse'].finalizado for b in blocos):
        return None
    messages.warning(
        request,
        f'Finalize todos os repasses do relatório (informando a competência) para gerar {o_que}.')
    return redirect(reverse('siresp_app:repasse_lote_relatorio') + '?ids='
                    + ','.join(map(str, ids)))


@login_required
def lote_relatorio_pdf(request):
    from django.http import HttpResponse
    from ..services.pdf_service import gerar_pdf

    blocos, tot_horas, tot_valor, ids = _montar_relatorio(request)
    if not blocos:
        return redirect('siresp_app:repasse_lote')
    bloqueio = _exigir_finalizados(request, blocos, ids, 'o PDF')
    if bloqueio:
        return bloqueio

    grupos = _grupos(blocos)
    grupos_pdf = [{
        'equipe': g['equipe'].nome if g['equipe'] else None,
        'horas': g['horas'],
        'valor': g['valor'],
        'profissionais': [{
            'nome': b['extracao'].medico_nome,
            'periodo': f"{b['extracao'].data_ini} a {b['extracao'].data_fim}",
            'competencia': b['repasse'].competencia_fmt,
            'horas': b['horas'],
            'valor': b['valor'],
            'linhas': [{
                'especialidade': i.especialidade, 'minutos': i.minutos,
                'horas': i.horas_final, 'valor_hora': i.valor_hora, 'total': i.total_final,
            } for i in b['aplicadas']],
        } for b in g['itens']],
    } for g in grupos]

    competencias = sorted({b['repasse'].competencia_fmt for b in blocos if b['repasse'].competencia})
    pdf = gerar_pdf(
        'Relatório de Repasse Médico',
        'Competência: ' + (', '.join(competencias) or '-')
        + f' | {len(blocos)} profissional(is)',
        grupos_pdf, _resumo(grupos), tot_horas, tot_valor)
    auditoria.registrar(request, 'EXPORTACAO',
                        f'PDF do lote: {len(blocos)} repasse(s), R$ {tot_valor}')
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="relatorio_repasse_lote.pdf"'
    return resp


@login_required
def lote_relatorio_excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    blocos, tot_horas, tot_valor, ids = _montar_relatorio(request)
    if not blocos:
        return redirect('siresp_app:repasse_lote')

    bloqueio = _exigir_finalizados(request, blocos, ids, 'o Excel')
    if bloqueio:
        return bloqueio

    grupos = _grupos(blocos)

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo do Lote"
    ws.append(["Equipe", "Profissional", "Período", "Especialidade", "Minutos",
               "Horas", "Valor/Hora (R$)", "Total (R$)", "Situação", "Competência"])
    for c in ws[1]:
        c.font = Font(bold=True)

    def negrito():
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)

    for g in grupos:
        equipe = g['equipe'].nome if g['equipe'] else ''
        for b in g['itens']:
            ext = b['extracao']
            periodo = f"{ext.data_ini} a {ext.data_fim}"
            comp = b['repasse'].competencia_fmt
            for i in b['aplicadas']:
                ws.append([equipe, ext.medico_nome, periodo, i.especialidade, float(i.minutos),
                           float(i.horas_final), float(i.valor_hora), float(i.total_final),
                           'Aplicada', comp])
            for i in b['sem_regra']:
                ws.append([equipe, ext.medico_nome, periodo, i.especialidade, '', '', '', '',
                           'Sem regra (não aplicada)', comp])
            ws.append([equipe, f"Subtotal {ext.medico_nome}", '', '', '',
                       float(b['horas']), '', float(b['valor']), '', ''])
            negrito()
        if g['equipe']:
            nomes = ', '.join(b['extracao'].medico_nome for b in g['itens'])
            ws.append([f"EQUIPE {equipe} — TOTAL", nomes, '', '', '',
                       float(g['horas']), '', float(g['valor']), '', ''])
            negrito()

    ws.append(["TOTAL GERAL", '', '', '', '', float(tot_horas), '', float(tot_valor), '', ''])
    negrito()
    for col, w in zip("ABCDEFGHIJ", (34, 38, 24, 45, 9, 10, 15, 15, 26, 13)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        row[6].number_format = 'R$ #,##0.00'
        row[7].number_format = 'R$ #,##0.00'

    resumo_linhas = _resumo(grupos)
    # No fim da aba principal, alinhado às colunas Equipe/Profissional/Horas/Total
    anexar_resumo_planilha(ws, resumo_linhas, tot_horas, tot_valor,
                           col_nome=1, col_profs=2, col_horas=3, col_valor=4)

    # Aba própria de fechamento por faturamento
    resumo = wb.create_sheet("Por Equipe")
    resumo.append(["Faturamento", "Profissionais", "Horas", "Valor total (R$)"])
    for c in resumo[1]:
        c.font = Font(bold=True)
    for l in resumo_linhas:
        resumo.append([l['nome'], l['profissionais'], float(l['horas']), float(l['valor'])])
    resumo.append(["TOTAL GERAL", '', float(tot_horas), float(tot_valor)])
    for c in resumo[resumo.max_row]:
        c.font = Font(bold=True)
    for col, w in zip("ABCD", (40, 80, 10, 18)):
        resumo.column_dimensions[col].width = w
    for row in resumo.iter_rows(min_row=2):
        row[3].number_format = 'R$ #,##0.00'

    auditoria.registrar(request, 'EXPORTACAO',
                        f'Excel do lote: {len(blocos)} repasse(s), R$ {tot_valor}')
    resp = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename="resumo_repasse_lote.xlsx"'
    wb.save(resp)
    return resp


@login_required
@require_POST
def lote_salvar(request):
    """
    Salva a edição de várias linhas de uma vez (minutos, valores, bônus,
    marcação) SEM finalizar. Repasses finalizados são recusados.
    Corpo: {"itens": [{"id": 1, "minutos": 30, "valor_base": 100,
                       "bonus_cheio": 40, "bonus_percent": "50%", "marcado": true}]}
    """
    import json
    from django.http import JsonResponse
    from ..models import ItemRepasse
    from .repasse import _serializar_item

    try:
        dados = json.loads(request.body)
        pedidos = {int(i['id']): i for i in dados.get('itens', [])}
    except Exception:
        return JsonResponse({'ok': False, 'mensagem': 'Payload inválido.'})

    itens = list(ItemRepasse.objects.filter(
        pk__in=pedidos, repasse__usuario_web=request.user).select_related('repasse'))

    erros, salvos, repasses = [], [], {}
    antes_por_repasse = {}
    for item in itens:
        if item.repasse_id not in antes_por_repasse and not item.repasse.finalizado:
            antes_por_repasse[item.repasse_id] = auditoria.snapshot(item.repasse)
    for item in itens:
        if item.repasse.finalizado:
            erros.append(f'{item.especialidade}: repasse finalizado (reabra para editar).')
            continue
        p = pedidos[item.pk]
        try:
            for campo in ('minutos', 'valor_base', 'bonus_cheio'):
                if campo in p:
                    valor = Decimal(str(p[campo]).replace(',', '.'))
                    if valor < 0:
                        raise ValueError(f'{campo} não pode ser negativo')
                    setattr(item, campo, valor)
            if 'bonus_percent' in p:
                if p['bonus_percent'] not in ('0%', '50%', '100%'):
                    raise ValueError('percentual de bônus inválido')
                item.bonus_percent = p['bonus_percent']
            if 'marcado' in p:
                item.marcado = bool(p['marcado'])
            item.faltou_regra = item.faltou_regra and not (
                'minutos' in p and Decimal(str(p['minutos']).replace(',', '.')) > 0)
        except Exception as e:
            erros.append(f'{item.especialidade}: {e}')
            continue
        item.save()
        salvos.append(item)
        repasses[item.repasse_id] = item.repasse

    for r in repasses.values():
        r.recalcular_totais()
        auditoria.registrar_edicao(
            request, r, antes_por_repasse[r.pk],
            descricao=f'Edição pelo relatório do lote: {r.extracao.medico_nome}')

    return JsonResponse({
        'ok': not erros,
        'salvos': len(salvos),
        'erros': erros,
        'itens': [_serializar_item(i) for i in salvos],
        'repasses': [
            {'id': r.id,
             'horas': float(r.horas_total_final),
             'valor': float(r.valor_total_final)}
            for r in repasses.values()
        ],
    })
