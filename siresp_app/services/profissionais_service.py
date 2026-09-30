"""
Base de profissionais e comparação com os repasses do mês.
"""
import calendar
import re
import unicodedata
from datetime import date, datetime


def normalizar(texto):
    if texto is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().upper()


def garantir_profissional(nome):
    """Cria o profissional na base se ainda não existir. Retorna (obj, criado)."""
    from ..models import Profissional

    nome = re.sub(r"\s+", " ", str(nome or "")).strip()
    norm = normalizar(nome)
    if not norm:
        return None, False
    return Profissional.objects.get_or_create(
        nome_norm=norm, defaults={'nome': nome}
    )


def _parse_data(txt):
    try:
        return datetime.strptime((txt or '').strip(), '%d/%m/%Y').date()
    except ValueError:
        return None


def _nomes_batem(a, b):
    """Nomes normalizados iguais, ou um contido no outro (nomes longos)."""
    if a == b:
        return True
    curto, longo = sorted((a, b), key=len)
    if len(curto) < 8:
        return False
    # palavras inteiras e consecutivas: "ANA LIMA" não casa com "MARIANA LIMA"
    tc, tl = curto.split(), longo.split()
    return any(tl[i:i + len(tc)] == tc for i in range(len(tl) - len(tc) + 1))


def situacao_mes(user, ano, mes):
    """
    Retorna lista de dicts, um por profissional ativo da base:
      {'profissional', 'status', 'repasse_pk', 'extracao_pk'}
    status: 'finalizado' | 'rascunho' | 'extraido' | 'pendente'
    Um período conta se cruza o mês escolhido.
    """
    from ..models import Profissional, Extracao

    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])

    # melhor situação por nome normalizado (finalizado > rascunho > extraido)
    prioridade = {'extraido': 1, 'rascunho': 2, 'finalizado': 3}
    achados = {}
    for ext in Extracao.objects.filter(usuario_web=user).select_related('repasse'):
        ini, fim = _parse_data(ext.data_ini), _parse_data(ext.data_fim)
        if not ini or not fim or ini > ultimo or fim < primeiro:
            continue
        repasse = getattr(ext, 'repasse', None)
        status = repasse.status if repasse else 'extraido'
        info = {
            'status': status,
            'repasse_pk': repasse.pk if repasse else None,
            'extracao_pk': ext.pk,
        }
        chave = normalizar(ext.medico_nome)
        atual = achados.get(chave)
        if not atual or prioridade[status] > prioridade[atual['status']]:
            achados[chave] = info

    resultado = []
    for prof in Profissional.objects.filter(ativo=True):
        info = achados.get(prof.nome_norm)
        if not info:
            for chave, val in achados.items():
                if _nomes_batem(prof.nome_norm, chave):
                    info = val
                    break
        resultado.append({
            'profissional': prof,
            'status': info['status'] if info else 'pendente',
            'repasse_pk': info['repasse_pk'] if info else None,
            'extracao_pk': info['extracao_pk'] if info else None,
        })
    return resultado


def extracoes_do_mes(user, ano, mes):
    """Extrações do usuário cujo período cruza o mês (com o repasse, se houver)."""
    from ..models import Extracao

    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    saida = []
    qs = (Extracao.objects.filter(usuario_web=user)
          .select_related('repasse').order_by('medico_nome'))
    for ext in qs:
        ini, fim = _parse_data(ext.data_ini), _parse_data(ext.data_fim)
        if ini and fim and ini <= ultimo and fim >= primeiro:
            saida.append(ext)
    return saida


# =========================================================
# EQUIPES
# =========================================================
def equipe_por_medico(nomes):
    """
    Recebe nomes de médicos (como vêm do SIRESP) e devolve
    {nome: EquipeMedica | None}, casando com a base de profissionais
    (nome normalizado igual, ou um contido no outro com 8+ letras).
    """
    from ..models import Profissional

    membros = [(p.nome_norm, p.equipe) for p in
               Profissional.objects.filter(equipe__isnull=False).select_related('equipe')]
    resultado = {}
    for nome in nomes:
        norm = normalizar(nome)
        achada = None
        for n, eq in membros:
            if n == norm:
                achada = eq
                break
        if achada is None:
            for n, eq in membros:
                if _nomes_batem(n, norm):
                    achada = eq
                    break
        resultado[nome] = achada
    return resultado


def agrupar_por_equipe(itens, chave_nome, valor_horas, valor_total):
    """
    Agrupa itens por equipe. Retorna lista de grupos ordenada
    (equipes por nome; avulsos por último):
      {'equipe': EquipeMedica|None, 'itens': [...], 'horas': Decimal, 'valor': Decimal}
    chave_nome/valor_horas/valor_total são funções aplicadas a cada item.
    """
    from decimal import Decimal

    mapa = equipe_por_medico({chave_nome(i) for i in itens})
    grupos = {}
    for it in itens:
        eq = mapa[chave_nome(it)]
        g = grupos.setdefault(eq.pk if eq else None, {
            'equipe': eq, 'itens': [], 'horas': Decimal('0'), 'valor': Decimal('0')})
        g['itens'].append(it)
        g['horas'] += valor_horas(it)
        g['valor'] += valor_total(it)
    ordenados = sorted(
        grupos.values(),
        key=lambda g: (g['equipe'] is None, g['equipe'].nome if g['equipe'] else ''))
    return ordenados


def pendentes_extracao(user, data_ini, data_fim):
    """
    Profissionais ativos que ainda precisam ser extraídos para o período.

    Conta como já resolvido quem tem uma extração (ou um "sem produção")
    que COBRE o período inteiro. Extração parcial (ex.: só a 1ª quinzena)
    continua pendente.

    Retorna {'nomes': [...], 'ja_extraidos': n, 'sem_producao': n, 'total': n}.
    Levanta ValueError se o período for inválido.
    """
    from ..models import Profissional, Extracao, SemProducao

    ini, fim = _parse_data(data_ini), _parse_data(data_fim)
    if not ini or not fim:
        raise ValueError('Informe as datas do período (DD/MM/AAAA).')
    if fim < ini:
        raise ValueError('A data final não pode ser anterior à inicial.')

    def cobre(a, b):
        a, b = _parse_data(a), _parse_data(b)
        return bool(a and b and a <= ini and b >= fim)

    extraidos = [normalizar(e.medico_nome) for e in Extracao.objects.filter(usuario_web=user)
                 if cobre(e.data_ini, e.data_fim)]
    vazios = [s.nome_norm for s in SemProducao.objects.filter(usuario_web=user)
              if cobre(s.data_ini, s.data_fim)]

    nomes, n_ext, n_vazio, total = [], 0, 0, 0
    for p in Profissional.objects.filter(ativo=True):
        total += 1
        if any(_nomes_batem(p.nome_norm, n) for n in extraidos):
            n_ext += 1
        elif any(_nomes_batem(p.nome_norm, n) for n in vazios):
            n_vazio += 1
        else:
            nomes.append(p.nome)
    return {'nomes': nomes, 'ja_extraidos': n_ext, 'sem_producao': n_vazio, 'total': total}
