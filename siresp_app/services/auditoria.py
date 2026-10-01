"""
Registro da trilha de auditoria.

Uso típico:
    antes = auditoria.snapshot(repasse)          # antes de alterar
    ... altera os itens ...
    auditoria.registrar_edicao(request, repasse, 'REPASSE_EDITADO', antes)

Nunca deve derrubar a operação principal: falhas ao gravar o log são
apenas registradas no log técnico.
"""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# Rótulos das ações (usados no filtro e na tela de auditoria)
ACOES = {
    'LOGIN': 'Login no sistema',
    'LOGIN_FALHA': 'Tentativa de login inválida',
    'LOGOUT': 'Logout',
    'EXTRACAO_CRIADA': 'Extração criada',
    'EXTRACAO_EXCLUIDA': 'Extração excluída',
    'REPASSE_CRIADO': 'Repasse gerado',
    'REPASSE_REFEITO': 'Repasse refeito',
    'REPASSE_EDITADO': 'Repasse editado',
    'REPASSE_FINALIZADO': 'Repasse finalizado',
    'REPASSE_REABERTO': 'Repasse reaberto',
    'REPASSE_APAGADO': 'Repasse apagado',
    'EXPORTACAO': 'Exportação (Excel/PDF)',
    'UNIDADE_SIRESP': 'Unidade do SIRESP (lembrar/esquecer)',
    'GRUPO_CRIADO': 'Grupo de valores criado',
    'GRUPO_EDITADO': 'Grupo de valores editado',
    'GRUPO_EXCLUIDO': 'Grupo de valores excluído',
    'REGRA_CRIADA': 'Regra de minutos criada',
    'REGRA_EDITADA': 'Regra de minutos editada',
    'REGRA_EXCLUIDA': 'Regra de minutos excluída',
    'REGRAS_LIMPAS': 'Regras de minutos apagadas (todas)',
    'IMPORTACAO': 'Planilha de agendas importada',
    'EQUIPE_CRIADA': 'Equipe criada',
    'EQUIPE_EDITADA': 'Equipe editada',
    'EQUIPE_EXCLUIDA': 'Equipe excluída',
    'PROFISSIONAL_ALTERADO': 'Base de profissionais alterada',
}

CAMPOS_ITEM = ('minutos', 'valor_base', 'bonus_cheio', 'bonus_percent',
               'marcado', 'horas_final', 'total_final')
ROTULOS_CAMPO = {
    'minutos': 'Minutos', 'valor_base': 'Valor base', 'bonus_cheio': 'Bônus 100%',
    'bonus_percent': 'Bônus %', 'marcado': 'Incluído no repasse',
    'horas_final': 'Horas (final)', 'total_final': 'Total (final)',
}
MAX_DETALHES = 300


def _ip(request):
    if request is None or not hasattr(request, 'META'):
        return ''
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (fwd.split(',')[0].strip() if fwd else request.META.get('REMOTE_ADDR', ''))[:45]


def _texto(v):
    if isinstance(v, Decimal):
        return f'{v:.2f}'
    if isinstance(v, bool):
        return 'sim' if v else 'não'
    return str(v)


def registrar(request_ou_user, acao, descricao='', repasse=None, profissional='', detalhes=None):
    """Grava uma linha de auditoria. `request_ou_user` pode ser request ou User."""
    from ..models import LogAuditoria

    try:
        request = request_ou_user if hasattr(request_ou_user, 'META') else None
        user = request.user if request is not None else request_ou_user
        if user is not None and not getattr(user, 'is_authenticated', False):
            user = None
        if repasse is not None and not profissional:
            profissional = repasse.extracao.medico_nome
        LogAuditoria.objects.create(
            usuario=user,
            usuario_nome=(user.get_username() if user else ''),
            acao=acao,
            descricao=(descricao or '')[:500],
            repasse_id=repasse.pk if repasse is not None else None,
            profissional=(profissional or '')[:200],
            detalhes=(detalhes or [])[:MAX_DETALHES],
            ip=_ip(request),
        )
    except Exception:
        logger.exception('Falha ao gravar auditoria (%s)', acao)


def registrar_como(nome_usuario, request, acao, descricao='', **kw):
    """Variante para tentativas sem usuário autenticado (ex.: login inválido)."""
    from ..models import LogAuditoria
    try:
        LogAuditoria.objects.create(
            usuario=None, usuario_nome=(nome_usuario or '')[:150], acao=acao,
            descricao=(descricao or '')[:500], ip=_ip(request), **kw)
    except Exception:
        logger.exception('Falha ao gravar auditoria (%s)', acao)


# ---------------------------------------------------------
# Comparação de itens do repasse
# ---------------------------------------------------------
def snapshot(repasse):
    """Foto dos campos auditados de todos os itens do repasse (lida do banco)."""
    return {
        i.pk: {'item': i.especialidade, **{c: _texto(getattr(i, c)) for c in CAMPOS_ITEM}}
        for i in repasse.itens.all()
    }


def diferencas(antes, depois):
    """Lista de mudanças campo a campo entre dois snapshots."""
    mudancas = []
    for pk, novo in depois.items():
        velho = antes.get(pk)
        if velho is None:
            continue
        for campo in CAMPOS_ITEM:
            if velho[campo] != novo[campo]:
                mudancas.append({
                    'item': novo['item'],
                    'campo': ROTULOS_CAMPO[campo],
                    'de': velho[campo],
                    'para': novo[campo],
                })
    return mudancas


def registrar_edicao(request, repasse, antes, acao='REPASSE_EDITADO', descricao=''):
    """Compara com o snapshot de antes e, se houve mudança, registra. Retorna nº de mudanças."""
    mudancas = diferencas(antes, snapshot(repasse))
    if mudancas:
        campos_unicos = len(mudancas)
        registrar(
            request, acao,
            descricao or f'{campos_unicos} alteração(ões) em {repasse.extracao.medico_nome}',
            repasse=repasse, detalhes=mudancas)
    return len(mudancas)


def diff_simples(antes, depois, rotulos):
    """Diff de dicts simples (ex.: campos de grupo/regra). Retorna lista de mudanças."""
    saida = []
    for campo, rotulo in rotulos.items():
        a, d = _texto(antes.get(campo, '')), _texto(depois.get(campo, ''))
        if a != d:
            saida.append({'item': '', 'campo': rotulo, 'de': a, 'para': d})
    return saida
