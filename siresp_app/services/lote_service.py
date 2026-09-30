"""
Busca e extração de produção em lote (vários médicos, um período).

Roda em thread de fundo, um job por usuário. O estado fica em memória e é
consultado por polling. Cada nome vira um item com status próprio.
"""
import logging
import threading

from django.db import close_old_connections

from . import scraper_service
from .profissionais_service import normalizar

logger = logging.getLogger(__name__)

_JOBS = {}          # {user_id: job}
_LOCK = threading.Lock()


def job_ativo(user):
    job = _JOBS.get(user.id)
    return bool(job and job['rodando'])


def obter_job(user):
    return _JOBS.get(user.id)


def _limpar_nomes(nomes):
    vistos, saida = set(), []
    for n in nomes:
        n = ' '.join(str(n).split())
        chave = normalizar(n)
        if chave and chave not in vistos:
            vistos.add(chave)
            saida.append(n)
    return saida


def iniciar(user, nomes, data_ini, data_fim, origem='CRM'):
    """Retorna (ok, mensagem)."""
    nomes = _limpar_nomes(nomes)
    if not nomes:
        return False, 'Informe pelo menos um nome.'

    with _LOCK:
        if job_ativo(user):
            return False, 'Já existe um lote em andamento.'
        _JOBS[user.id] = {
            'rodando': True,
            'cancelar': False,
            'data_ini': data_ini,
            'data_fim': data_fim,
            'itens': [
                {'nome': n, 'status': 'aguardando', 'mensagem': '',
                 'medico': '', 'extracao_id': None, 'candidatos': []}
                for n in nomes
            ],
        }
        job = _JOBS[user.id]

    threading.Thread(
        target=_executar, args=(user, job, origem), daemon=True
    ).start()
    return True, f'Lote iniciado com {len(nomes)} nome(s).'


def cancelar(user):
    job = _JOBS.get(user.id)
    if job and job['rodando']:
        job['cancelar'] = True
        # Os que ainda não começaram são cancelados na hora; o item em
        # andamento termina a etapa atual do navegador.
        for item in job['itens']:
            if item['status'] == 'aguardando':
                item['status'] = 'cancelado'
        return True
    return False


def escolher_medico(nome, medicos):
    """
    Decide qual resultado da busca usar.
    Retorna (medico | None, status, candidatos).
    """
    if not medicos:
        return None, 'nao_encontrado', []
    alvo = normalizar(nome)
    exatos = [m for m in medicos if normalizar(m['nome']) == alvo]
    if len(exatos) == 1:
        return exatos[0], 'ok', []
    if not exatos and len(medicos) == 1:
        return medicos[0], 'ok', []
    return None, 'ambiguo', [m['nome'] for m in medicos][:10]


def _processar_item(user, job, item, origem):
    from ..models import Extracao, ItemProducao, EspecialidadeConhecida

    item['status'] = 'buscando'
    medicos = scraper_service.listar_medicos(user, item['nome'], origem)
    medico, status, candidatos = escolher_medico(item['nome'], medicos)

    if not medico:
        item['status'] = status
        item['candidatos'] = candidatos
        item['mensagem'] = (
            'Nenhum médico encontrado.' if status == 'nao_encontrado'
            else 'Mais de um resultado — refine o nome.'
        )
        return

    item['medico'] = medico['nome']
    ja = [
        e for e in Extracao.objects.filter(
            usuario_web=user, data_ini=job['data_ini'], data_fim=job['data_fim']
        ) if normalizar(e.medico_nome) == normalizar(medico['nome'])
    ]
    if ja:
        item['status'] = 'ja_extraido'
        item['extracao_id'] = ja[0].pk
        item['mensagem'] = 'Já existe extração deste período.'
        return

    item['status'] = 'extraindo'
    dados = scraper_service.extrair_producao(
        user, medico, job['data_ini'], job['data_fim']
    )
    if not dados:
        from ..models import SemProducao
        SemProducao.objects.update_or_create(
            usuario_web=user, nome_norm=normalizar(medico['nome']),
            data_ini=job['data_ini'], data_fim=job['data_fim'],
            defaults={'medico_nome': medico['nome']})
        item['status'] = 'sem_dados'
        item['mensagem'] = 'Nenhuma produção no período.'
        return

    extracao = Extracao.objects.create(
        usuario_web=user,
        medico_nome=medico['nome'],
        medico_crm=medico.get('crm', ''),
        medico_codigo=medico.get('codigo', ''),
        data_ini=job['data_ini'],
        data_fim=job['data_fim'],
    )
    for i, d in enumerate(dados):
        ItemProducao.objects.create(
            extracao=extracao, especialidade=d.get('Especialidade', ''),
            dados=d, ordem=i,
        )
        esp = d.get('Especialidade', '').strip()
        if esp:
            EspecialidadeConhecida.objects.get_or_create(nome=esp)

    from . import auditoria
    from ..models import SemProducao
    SemProducao.objects.filter(
        usuario_web=user, nome_norm=normalizar(medico['nome']),
        data_ini=job['data_ini'], data_fim=job['data_fim']).delete()
    auditoria.registrar(
        user, 'EXTRACAO_CRIADA',
        f'Extração em lote de {extracao.medico_nome} ({job["data_ini"]} a {job["data_fim"]}): {len(dados)} linhas',
        profissional=extracao.medico_nome)
    item['status'] = 'concluido'
    item['extracao_id'] = extracao.pk
    item['mensagem'] = f'{len(dados)} linhas extraídas.'


def _descrever_erro(e):
    """Mensagem legível: tipo do erro + primeira linha, sem o stacktrace do chromedriver."""
    texto = str(e).split('Stacktrace:')[0].replace('Message:', '').strip()
    if type(e).__name__ == 'TimeoutException' and not texto:
        texto = 'O SIRESP demorou demais para responder (tempo esgotado).'
    return (texto or type(e).__name__)[:300]


def _executar(user, job, origem):
    scraper_service.marcar_ocupado(user, True)
    try:
        for item in job['itens']:
            if job['cancelar']:
                item['status'] = 'cancelado'
                continue
            try:
                _processar_item(user, job, item, origem)
            except Exception as e:
                logger.exception('Erro no lote (%s)', item['nome'])
                item['status'] = 'erro'
                item['mensagem'] = _descrever_erro(e)
                if not scraper_service.sessao_ativa(user):
                    # sessão caiu: marca o restante e para
                    job['cancelar'] = True
    finally:
        scraper_service.marcar_ocupado(user, False)
        job['rodando'] = False
        close_old_connections()
