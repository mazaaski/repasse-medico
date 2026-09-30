"""
Views da aba Produção — modo HEADLESS com CAPTCHA via web.
"""
import csv
import json
import threading

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET

from ..models import (
    ConfiguracaoLogin, SessaoSiresp, Extracao, ItemProducao,
)
from ..services import scraper_service, auditoria


# Resultado das extrações individuais que falharam ou vieram vazias
# {extracao_id: mensagem}. Em memória: só serve para o polling da tela.
_FALHAS_EXTRACAO = {}


# =========================================================
# TELA PRINCIPAL
# =========================================================
@login_required
def producao_home(request):
    config = ConfiguracaoLogin.get_para(request.user)
    sessao, _ = SessaoSiresp.objects.get_or_create(usuario_web=request.user)

    return render(request, 'siresp_app/producao/home.html', {
        'config': config,
        'sessao': sessao,
        'sessoes_ativas': scraper_service.contar_sessoes(),
        'limite_sessoes': scraper_service.LIMITE_SESSOES,
        'extracoes_recentes': Extracao.objects.filter(usuario_web=request.user)[:5],
    })


# =========================================================
# SALVAR CREDENCIAIS
# =========================================================
@login_required
@require_POST
def salvar_credenciais(request):
    config = ConfiguracaoLogin.get_para(request.user)
    config.usuario = request.POST.get('usuario', '').strip()
    config.senha = request.POST.get('senha', '').strip()
    config.cpf_primeiros = request.POST.get('cpf_primeiros', '').strip()
    config.cpf_ultimos = request.POST.get('cpf_ultimos', '').strip()
    config.rg_primeiros = request.POST.get('rg_primeiros', '').strip()
    config.rg_ultimos = request.POST.get('rg_ultimos', '').strip()
    config.origem = request.POST.get('origem', 'CRM').strip()
    config.save()

    messages.success(request, '✅ Credenciais salvas.')
    return redirect('siresp_app:producao_home')


# =========================================================
# LOGIN SIRESP — ABRE CHROME E CAPTURA CAPTCHA
# =========================================================
@login_required
@require_POST
def login_siresp(request):
    config = ConfiguracaoLogin.get_para(request.user)

    if not config.usuario or not config.senha:
        return JsonResponse({
            'ok': False,
            'mensagem': 'Preencha usuário e senha antes de fazer login.',
        })

    if scraper_service.sessao_ativa(request.user):
        return JsonResponse({
            'ok': False,
            'mensagem': 'Você já tem uma sessão aberta.',
        })

    credenciais = {
        'usuario': config.usuario,
        'senha': config.senha,
        'cpf_primeiros': config.cpf_primeiros,
        'cpf_ultimos': config.cpf_ultimos,
        'rg_primeiros': config.rg_primeiros,
        'rg_ultimos': config.rg_ultimos,
    }

    resultado = scraper_service.iniciar_login(request.user, credenciais)

    if resultado.get('ok'):
        sessao, _ = SessaoSiresp.objects.get_or_create(usuario_web=request.user)
        sessao.status = 'aguardando'
        sessao.mensagem = 'CAPTCHA aguardando digitação.'
        sessao.save()

    return JsonResponse(resultado)


# =========================================================
# ENVIAR CAPTCHA
# =========================================================
@login_required
@require_POST
def enviar_captcha(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'mensagem': 'Payload inválido.'})

    texto = data.get('captcha', '').strip()
    if not texto:
        return JsonResponse({'ok': False, 'mensagem': 'Digite o texto do CAPTCHA.'})

    resultado = scraper_service.enviar_captcha_e_continuar(request.user, texto)
    return JsonResponse(resultado)


# =========================================================
# RECARREGAR CAPTCHA
# =========================================================
@login_required
@require_POST
def recarregar_captcha(request):
    resultado = scraper_service.recarregar_captcha(request.user)
    return JsonResponse(resultado)


# =========================================================
# STATUS DO LOGIN
# =========================================================
@login_required
@require_GET
def status_login(request):
    info = scraper_service.status_login(request.user)

    sessao, _ = SessaoSiresp.objects.get_or_create(usuario_web=request.user)

    if info['estado'] == 'logado' and sessao.status != 'logado':
        sessao.status = 'logado'
        sessao.mensagem = 'Login concluído.'
        sessao.save()
    elif info['estado'] == 'sem_sessao' and sessao.status == 'logado':
        sessao.status = 'fechada'
        sessao.mensagem = 'Sessão encerrada.'
        sessao.save()

    resposta = {
        'estado': info['estado'],
        'logado': info['logado'],
        'mensagem': sessao.mensagem,
    }
    if 'captcha_b64' in info:
        resposta['captcha_b64'] = info['captcha_b64']
        resposta['captcha_id'] = info.get('captcha_id', 0)

    return JsonResponse(resposta)


# =========================================================
# FECHAR SESSÃO
# =========================================================
@login_required
@require_POST
def fechar_sessao(request):
    fechou = scraper_service.fechar_sessao(request.user)

    sessao, _ = SessaoSiresp.objects.get_or_create(usuario_web=request.user)
    sessao.status = 'fechada'
    sessao.mensagem = 'Sessão encerrada pelo usuário.'
    sessao.save()

    return JsonResponse({
        'ok': True,
        'mensagem': 'Sessão fechada.' if fechou else 'Nenhuma sessão estava ativa.',
    })


# =========================================================
# BUSCAR MÉDICOS
# =========================================================
@login_required
@require_GET
def buscar_medicos(request):
    nome = request.GET.get('nome', '').strip()
    origem = request.GET.get('origem', 'CRM').strip()

    if not nome:
        return JsonResponse({'ok': False, 'mensagem': 'Digite parte do nome.'})

    if not scraper_service.sessao_ativa(request.user):
        return JsonResponse({'ok': False, 'mensagem': 'Faça login no SIRESP primeiro.'})

    from ..services import lote_service
    if lote_service.job_ativo(request.user):
        return JsonResponse({'ok': False, 'mensagem': 'Há um lote em andamento. Aguarde terminar.'})

    info = scraper_service.status_login(request.user)
    if not info['logado']:
        return JsonResponse({'ok': False, 'mensagem': 'Login ainda não concluído.'})

    try:
        medicos = scraper_service.listar_medicos(request.user, nome, origem)
        return JsonResponse({'ok': True, 'medicos': medicos})
    except Exception as e:
        return JsonResponse({'ok': False, 'mensagem': str(e)})


# =========================================================
# EXTRAIR PRODUÇÃO
# =========================================================
@login_required
@require_POST
def extrair_producao(request):
    try:
        payload = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'mensagem': 'Payload inválido.'})

    medico = payload.get('medico') or {}
    data_ini = payload.get('data_ini', '').strip()
    data_fim = payload.get('data_fim', '').strip()

    if not medico.get('nome') or not data_ini or not data_fim:
        return JsonResponse({'ok': False, 'mensagem': 'Preencha médico e datas.'})

    if not scraper_service.sessao_ativa(request.user):
        return JsonResponse({'ok': False, 'mensagem': 'Sessão expirada. Faça login novamente.'})

    from ..services import lote_service
    if lote_service.job_ativo(request.user):
        return JsonResponse({'ok': False, 'mensagem': 'Há um lote em andamento. Aguarde terminar.'})

    info = scraper_service.status_login(request.user)
    if not info['logado']:
        return JsonResponse({'ok': False, 'mensagem': 'Login ainda não concluído.'})

    extracao = Extracao.objects.create(
        usuario_web=request.user,
        medico_nome=medico['nome'],
        medico_crm=medico.get('crm', ''),
        medico_codigo=medico.get('codigo', ''),
        data_ini=data_ini,
        data_fim=data_fim,
    )

    def _run():
        scraper_service.marcar_ocupado(request.user, True)
        try:
            dados = scraper_service.extrair_producao(
                request.user, medico, data_ini, data_fim,
            )
            if not dados:
                _FALHAS_EXTRACAO[extracao.id] = 'Nenhuma produção encontrada neste período.'
                extracao.delete()
                return
            for i, d in enumerate(dados):
                ItemProducao.objects.create(
                    extracao=extracao,
                    especialidade=d.get('Especialidade', ''),
                    dados=d,
                    ordem=i,
                )
            from ..models import EspecialidadeConhecida
            for d in dados:
                esp = d.get('Especialidade', '').strip()
                if esp:
                    EspecialidadeConhecida.objects.get_or_create(nome=esp)
            auditoria.registrar(
                request.user, 'EXTRACAO_CRIADA',
                f'Extração de {extracao.medico_nome} ({data_ini} a {data_fim}): {len(dados)} linhas',
                profissional=extracao.medico_nome)
        except Exception as e:
            print(f"[SIRESP] Erro na extração {extracao.id}: {e}")
            _FALHAS_EXTRACAO[extracao.id] = (
                str(e).split('Stacktrace:')[0].replace('Message:', '').strip()
                or 'O SIRESP demorou demais para responder.'
            )
            extracao.delete()
        finally:
            scraper_service.marcar_ocupado(request.user, False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return JsonResponse({
        'ok': True,
        'extracao_id': extracao.id,
        'mensagem': 'Extração iniciada. Aguarde...',
    })


# =========================================================
# LOTE (busca + extração de vários médicos)
# =========================================================
@login_required
@require_POST
def lote_iniciar(request):
    from ..services import lote_service

    try:
        payload = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'mensagem': 'Payload inválido.'})

    nomes = payload.get('nomes') or []
    if isinstance(nomes, str):
        nomes = nomes.splitlines()
    data_ini = str(payload.get('data_ini', '')).strip()
    data_fim = str(payload.get('data_fim', '')).strip()
    origem = str(payload.get('origem') or 'CRM').strip()

    if len(data_ini) != 10 or len(data_fim) != 10:
        return JsonResponse({'ok': False, 'mensagem': 'Informe as duas datas (DD/MM/AAAA).'})

    if not scraper_service.sessao_ativa(request.user) or \
            not scraper_service.status_login(request.user)['logado']:
        return JsonResponse({'ok': False, 'mensagem': 'Faça login no SIRESP primeiro.'})

    ok, msg = lote_service.iniciar(request.user, nomes, data_ini, data_fim, origem)
    return JsonResponse({'ok': ok, 'mensagem': msg})


@login_required
@require_GET
def lote_status(request):
    from ..services import lote_service

    job = lote_service.obter_job(request.user)
    if not job:
        return JsonResponse({'ok': True, 'existe': False})
    itens = job['itens']
    feitos = sum(1 for i in itens if i['status'] not in ('aguardando', 'buscando', 'extraindo'))
    return JsonResponse({
        'ok': True,
        'existe': True,
        'rodando': job['rodando'],
        'total': len(itens),
        'feitos': feitos,
        'itens': itens,
    })


@login_required
@require_POST
def lote_cancelar(request):
    from ..services import lote_service
    return JsonResponse({'ok': lote_service.cancelar(request.user)})


@login_required
@require_GET
def lote_pendentes(request):
    """
    Nomes dos profissionais da base que ainda precisam ser extraídos.

    Com data_ini/data_fim (o período da tela): pendente = sem extração que cubra
    o período inteiro. Sem datas (compatibilidade): pendente = sem nenhuma
    extração no mês informado.
    """
    from datetime import date
    from ..services.profissionais_service import situacao_mes, pendentes_extracao

    data_ini = request.GET.get('data_ini', '').strip()
    data_fim = request.GET.get('data_fim', '').strip()

    if data_ini or data_fim:
        try:
            res = pendentes_extracao(request.user, data_ini, data_fim)
        except ValueError as e:
            return JsonResponse({'ok': False, 'mensagem': str(e)})
        return JsonResponse({'ok': True, **res})

    hoje = date.today()
    try:
        ano = int(request.GET.get('ano', hoje.year))
        mes = int(request.GET.get('mes', hoje.month))
        date(ano, mes, 1)
    except ValueError:
        return JsonResponse({'ok': False, 'mensagem': 'Mês inválido.'})

    nomes = [s['profissional'].nome for s in situacao_mes(request.user, ano, mes)
             if s['status'] == 'pendente']
    return JsonResponse({'ok': True, 'nomes': nomes})


# =========================================================
# STATUS DA EXTRAÇÃO
# =========================================================
@login_required
@require_GET
def status_extracao(request, pk):
    if pk in _FALHAS_EXTRACAO:
        return JsonResponse({
            'ok': True, 'extracao_id': pk, 'finalizada': False,
            'erro': _FALHAS_EXTRACAO.pop(pk),
        })
    extracao = get_object_or_404(Extracao, pk=pk, usuario_web=request.user)
    total = extracao.itens.count()
    return JsonResponse({
        'ok': True,
        'extracao_id': extracao.id,
        'total_itens': total,
        'medico': extracao.medico_nome,
        'finalizada': total > 0,
    })


# =========================================================
# VER RESULTADO
# =========================================================
@login_required
def ver_extracao(request, pk):
    # Consulta liberada para todos; só o dono gera repasse/exclui a partir dela.
    extracao = get_object_or_404(Extracao.objects.select_related('usuario_web'), pk=pk)
    itens = extracao.itens.all()

    colunas_visiveis = [
        "Especialidade",
        "Oferta_N",
        "Agend_Total_N", "Agend_Total_Perc",
        "Agend_Cota_N", "Agend_Cota_Perc",
        "Agend_TotalGeral_N",
        "Atend_Presencial_N", "Atend_Presencial_Perc",
        "Atend_Total_N", "Atend_Total_Perc",
        "Ausente_N", "Ausente_Perc",
        "Dispensado_N", "Dispensado_Perc",
        "NaoInformado_N", "NaoInformado_Perc",
        "Alta_N", "Alta_Perc",
    ]

    linhas = []
    for item in itens:
        linhas.append([item.dados.get(col, '') for col in colunas_visiveis])

    return render(request, 'siresp_app/producao/resultado.html', {
        'extracao': extracao,
        'colunas': colunas_visiveis,
        'linhas': linhas,
        'outro_dono': extracao.usuario_web_id != request.user.id,
        'repasse': getattr(extracao, 'repasse', None),
    })


# =========================================================
# HISTÓRICO
# =========================================================
@login_required
def historico(request):
    extracoes = (
        Extracao.objects
        .select_related('usuario_web')
        .prefetch_related('repasse')
        .order_by('-criada_em')
    )

    lista = []
    for e in extracoes:
        try:
            repasse = e.repasse
            repasse_info = {
                'existe': True,
                'pk': repasse.pk,
                'status': repasse.status,
                'finalizado': repasse.status == 'finalizado',
            }
        except Exception:
            repasse_info = {
                'existe': False,
                'pk': None,
                'status': None,
                'finalizado': False,
            }
        lista.append({
            'obj': e,
            'repasse': repasse_info,
            'dono': e.usuario_web_id == request.user.id,
        })

    return render(request, 'siresp_app/producao/historico.html', {
        'extracoes': lista,
    })


# =========================================================
# EXCLUIR EXTRAÇÃO (individual)
# =========================================================
@login_required
@require_POST
def excluir_extracao(request, pk):
    extracao = get_object_or_404(Extracao, pk=pk, usuario_web=request.user)

    try:
        repasse = extracao.repasse
        if repasse.status == 'finalizado':
            messages.error(
                request,
                f'Não posso excluir "{extracao.medico_nome}" porque o repasse está '
                f'FINALIZADO. Reabra o repasse primeiro.'
            )
            return redirect('siresp_app:producao_historico')
    except Exception:
        pass

    auditoria.registrar(request, 'EXTRACAO_EXCLUIDA',
                        f'Extração de {extracao.medico_nome} ({extracao.data_ini} a {extracao.data_fim}) excluída',
                        profissional=extracao.medico_nome)
    extracao.delete()
    messages.success(request, 'Extração excluída.')
    return redirect('siresp_app:producao_historico')


# =========================================================
# EXCLUIR VÁRIAS
# =========================================================
@login_required
@require_POST
def excluir_varias(request):
    ids_str = request.POST.getlist('extracao_ids')

    if not ids_str:
        messages.warning(request, 'Selecione pelo menos uma extração.')
        return redirect('siresp_app:producao_historico')

    try:
        ids = [int(i) for i in ids_str]
    except ValueError:
        messages.error(request, 'IDs inválidos.')
        return redirect('siresp_app:producao_historico')

    extracoes = Extracao.objects.filter(
        pk__in=ids, usuario_web=request.user
    )

    bloqueadas = []
    apagaveis = []

    for e in extracoes:
        try:
            repasse = e.repasse
            if repasse.status == 'finalizado':
                bloqueadas.append(e)
                continue
        except Exception:
            pass
        apagaveis.append(e)

    qtd_apagadas = 0
    for e in apagaveis:
        try:
            auditoria.registrar(request, 'EXTRACAO_EXCLUIDA',
                                f'Extração de {e.medico_nome} ({e.data_ini} a {e.data_fim}) excluída',
                                profissional=e.medico_nome)
            e.delete()
            qtd_apagadas += 1
        except Exception as ex:
            print(f"[SIRESP] Erro ao excluir extração {e.id}: {ex}")

    if bloqueadas:
        nomes = ', '.join(e.medico_nome for e in bloqueadas)
        messages.warning(
            request,
            f'{qtd_apagadas} extração(ões) excluída(s). '
            f'{len(bloqueadas)} NÃO puderam ser excluídas porque têm '
            f'repasse FINALIZADO: {nomes}. Reabra o repasse primeiro.'
        )
    else:
        messages.success(request, f'{qtd_apagadas} extração(ões) excluída(s).')

    return redirect('siresp_app:producao_historico')


# =========================================================
# EXPORTAR CSV
# =========================================================
@login_required
def exportar_csv(request, pk):
    extracao = get_object_or_404(Extracao, pk=pk)
    itens = extracao.itens.all()

    colunas = [
        "Especialidade",
        "Oferta_N",
        "Agend_Total_N", "Agend_Total_Perc",
        "Agend_Cota_N", "Agend_Cota_Perc",
        "Agend_TotalGeral_N",
        "Atend_Presencial_N", "Atend_Presencial_Perc",
        "Atend_Total_N", "Atend_Total_Perc",
        "Ausente_N", "Ausente_Perc",
        "Dispensado_N", "Dispensado_Perc",
        "NaoInformado_N", "NaoInformado_Perc",
        "Alta_N", "Alta_Perc",
    ]

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    nome_arquivo = (
        f"producao_{extracao.medico_nome.replace(' ', '_')}_"
        f"{extracao.data_ini.replace('/', '-')}_a_{extracao.data_fim.replace('/', '-')}.csv"
    )
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'

    writer = csv.writer(response)
    writer.writerow(colunas)
    for item in itens:
        writer.writerow([item.dados.get(col, '') for col in colunas])

    return response


# =========================================================
# EXPORTAR JSON
# =========================================================
@login_required
def exportar_json(request, pk):
    extracao = get_object_or_404(Extracao, pk=pk)
    itens = extracao.itens.all()

    dados = {
        'extracao': {
            'id': extracao.id,
            'medico': extracao.medico_nome,
            'crm': extracao.medico_crm,
            'codigo': extracao.medico_codigo,
            'periodo': {
                'inicio': extracao.data_ini,
                'fim': extracao.data_fim,
            },
            'extraido_em': extracao.criada_em.isoformat(),
        },
        'itens': [item.dados for item in itens],
    }

    response = JsonResponse(
        dados, json_dumps_params={'ensure_ascii': False, 'indent': 2},
    )
    nome_arquivo = (
        f"producao_{extracao.medico_nome.replace(' ', '_')}_"
        f"{extracao.data_ini.replace('/', '-')}.json"
    )
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    return response