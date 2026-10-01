"""
Service que gerencia sessões do SirespScraper na web.
Modo HEADLESS — Chrome roda invisível.
O CAPTCHA é capturado como base64 e enviado pra UI.
"""
import threading
import time
import os
import sys

from django.conf import settings

# Adiciona a raiz do projeto ao sys.path
BASE_DIR = settings.BASE_DIR
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# =========================================================
# ESTADO GLOBAL EM MEMÓRIA
# =========================================================
_SCRAPERS = {}          # {user_id: SirespScraper}
_LOCK = threading.Lock()

LIMITE_SESSOES = 2

# Usuários cujo Chrome está ocupado (lote/extração). Enquanto ocupado,
# status_login não consulta o driver — a consulta ficaria presa na fila
# do chromedriver e travaria as requisições da tela.
_OCUPADOS = set()


def marcar_ocupado(user, ocupado):
    if ocupado:
        _OCUPADOS.add(user.id)
    else:
        _OCUPADOS.discard(user.id)


# =========================================================
# HELPERS
# =========================================================
def _importar_scraper():
    try:
        from siresp_scraper import SirespScraper
        return SirespScraper
    except ImportError as e:
        raise ImportError(
            "Não encontrei o arquivo 'siresp_scraper.py' na raiz do projeto. "
            f"Erro: {e}"
        )


def _atualizar_status_sessao(user, status, mensagem):
    try:
        from ..models import SessaoSiresp
        sessao, _ = SessaoSiresp.objects.get_or_create(usuario_web=user)
        sessao.status = status
        sessao.mensagem = mensagem
        sessao.save(update_fields=['status', 'mensagem', 'atualizada_em'])
    except Exception as e:
        print(f"[SIRESP] Não consegui atualizar SessaoSiresp de {user.id}: {e}")


def _tratar_erro_scraper(user, exc):
    msg = str(exc).lower()
    erros_fatais = [
        'invalid session id',
        'disconnected',
        'not connected to devtools',
        'chrome not reachable',
        'no such window',
        'target window already closed',
        'session deleted',
    ]
    if any(e in msg for e in erros_fatais):
        print(f"[SIRESP] Sessão morta detectada para user {user.id}. Fechando...")
        fechar_sessao(user)
        _atualizar_status_sessao(
            user, 'fechada',
            'Sessão foi encerrada. Faça login novamente.'
        )


# =========================================================
# CONSULTAS DE ESTADO
# =========================================================
def sessao_ativa(user):
    return user.id in _SCRAPERS


def contar_sessoes():
    return len(_SCRAPERS)


def tem_vaga():
    return contar_sessoes() < LIMITE_SESSOES


def get_scraper(user):
    return _SCRAPERS.get(user.id)


# =========================================================
# LOGIN — PARTE 1: ABRE CHROME E CAPTURA CAPTCHA
# =========================================================
def iniciar_login(user, credenciais):
    """
    Abre o Chrome headless, preenche user/senha, captura o CAPTCHA
    e retorna o screenshot (base64).

    Retorna:
      {'ok': True, 'captcha_b64': '...', 'captcha_id': N}
      ou
      {'ok': False, 'mensagem': '...'}
    """
    with _LOCK:
        # Limpa scraper órfão
        if user.id in _SCRAPERS:
            scraper_antigo = _SCRAPERS[user.id]
            chrome_vivo = False
            try:
                if scraper_antigo.driver:
                    _ = scraper_antigo.driver.current_url
                    chrome_vivo = True
            except Exception:
                chrome_vivo = False

            if chrome_vivo:
                return {
                    'ok': False,
                    'mensagem': 'Você já tem uma sessão aberta. Clique em "Fechar" primeiro.',
                }

            print(f"[SIRESP] Limpando scraper órfão do user {user.id}")
            try:
                scraper_antigo.fechar()
            except Exception:
                pass
            _SCRAPERS.pop(user.id, None)

        if not tem_vaga():
            return {
                'ok': False,
                'mensagem': (
                    f'Limite de {LIMITE_SESSOES} sessões simultâneas atingido. '
                    'Tente novamente em alguns minutos.'
                ),
            }

        SirespScraper = _importar_scraper()

        scraper = SirespScraper(callback_log=None)
        _SCRAPERS[user.id] = scraper

    _atualizar_status_sessao(
        user, 'abrindo',
        'Preparando login. Aguardando CAPTCHA...'
    )

    try:
        scraper.fazer_login(
            credenciais['usuario'],
            credenciais['senha'],
            credenciais.get('cpf_primeiros', ''),
            credenciais.get('cpf_ultimos', ''),
            credenciais.get('rg_primeiros', ''),
            credenciais.get('rg_ultimos', ''),
        )
    except Exception as e:
        print(f"[SIRESP] Erro no fazer_login do user {user.id}: {e}")
        import traceback
        traceback.print_exc()
        _tratar_erro_scraper(user, e)
        _atualizar_status_sessao(user, 'erro', f'Erro no login: {e}')
        fechar_sessao(user)
        return {'ok': False, 'mensagem': f'Erro ao abrir navegador: {e}'}

    if not scraper.captcha_imagem_b64:
        _atualizar_status_sessao(user, 'erro', 'Não consegui capturar o CAPTCHA.')
        return {
            'ok': False,
            'mensagem': 'Não consegui capturar o CAPTCHA. Tente novamente.',
        }

    _atualizar_status_sessao(
        user, 'aguardando',
        'CAPTCHA capturado. Digite na interface.'
    )

    return {
        'ok': True,
        'captcha_b64': scraper.captcha_imagem_b64,
        'captcha_id': scraper.captcha_id,
        'mensagem': 'Digite o CAPTCHA abaixo.',
    }


# =========================================================
# LOGIN — PARTE 2: ENVIA CAPTCHA E CONTINUA
# =========================================================
def enviar_captcha_e_continuar(user, texto):
    """
    Envia o CAPTCHA (preenche + clica em Entrar) e roda a
    continuação do login em background.
    """
    scraper = _SCRAPERS.get(user.id)
    if not scraper:
        return {'ok': False, 'mensagem': 'Sessão expirou. Faça login novamente.'}

    try:
        resultado = scraper.enviar_captcha(texto)
    except Exception as e:
        print(f"[SIRESP] Erro ao enviar CAPTCHA do user {user.id}: {e}")
        return {'ok': False, 'mensagem': f'Erro ao enviar CAPTCHA: {e}'}

    if not resultado or not resultado.get('ok'):
        msg = (resultado or {}).get('mensagem', 'Erro desconhecido.')
        return {'ok': False, 'mensagem': msg}

    _atualizar_status_sessao(user, 'abrindo', 'Validando CAPTCHA...')

    from ..models import ConfiguracaoLogin
    try:
        config = ConfiguracaoLogin.get_para(user)
    except Exception:
        config = None

    if not config:
        return {'ok': False, 'mensagem': 'Credenciais não encontradas.'}

    cpf_pri = config.cpf_primeiros or ""
    cpf_ult = config.cpf_ultimos or ""
    rg_pri = config.rg_primeiros or ""
    rg_ult = config.rg_ultimos or ""
    unidade_pref = config.unidade_preferida or ""

    def _run():
        try:
            resultado_continuar = scraper.continuar_login_apos_captcha(
                cpf_pri, cpf_ult, rg_pri, rg_ult, unidade_pref,
            )
            _tratar_resultado_login(user, resultado_continuar)
        except Exception as e:
            print(f"[SIRESP] Erro na continuação do login: {e}")
            import traceback
            traceback.print_exc()
            _atualizar_status_sessao(user, 'erro', f'Erro: {e}')
            _tratar_erro_scraper(user, e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {
        'ok': True,
        'mensagem': 'CAPTCHA enviado. Validando...',
    }


def _tratar_resultado_login(user, resultado):
    """Converte o retorno do scraper (continuar/concluir login) no status da sessão."""
    if not isinstance(resultado, dict):
        resultado = {
            'ok': False,
            'mensagem': 'Resposta inválida do scraper.',
            'captcha_novo': False,
        }

    if resultado.get('ok'):
        _atualizar_status_sessao(user, 'logado', 'Login concluído.')
        print(f"[SIRESP] Login OK para user {user.id}")
        return

    if resultado.get('aguardando_unidade'):
        _atualizar_status_sessao(user, 'aguardando', 'Selecione a unidade.')
        print(f"[SIRESP] Aguardando escolha de unidade do user {user.id}")
        return

    msg = resultado.get('mensagem', 'Erro desconhecido.')
    if resultado.get('captcha_novo', False):
        _atualizar_status_sessao(user, 'aguardando', msg)
    else:
        _atualizar_status_sessao(user, 'erro', msg)
    print(f"[SIRESP] Login falhou: {msg}")


def escolher_unidade(user, valor):
    """
    Aplica a unidade escolhida pelo usuário e continua o login (dígitos de
    CPF/RG) em segundo plano. Retorna {'ok': bool, 'mensagem': str}.
    """
    scraper = _SCRAPERS.get(user.id)
    if not scraper:
        return {'ok': False, 'mensagem': 'Sessão expirou. Faça login novamente.'}
    if not getattr(scraper, 'aguardando_unidade', False):
        return {'ok': False, 'mensagem': 'Nenhuma escolha de unidade está pendente.'}

    try:
        res = scraper.escolher_unidade(valor)
    except Exception as e:
        print(f"[SIRESP] Erro ao escolher unidade do user {user.id}: {e}")
        return {'ok': False, 'mensagem': f'Erro ao escolher a unidade: {e}'}
    if not res.get('ok'):
        return {'ok': False, 'mensagem': res.get('mensagem', 'Não consegui escolher a unidade.')}

    _atualizar_status_sessao(user, 'abrindo', 'Unidade selecionada. Enviando dígitos de segurança...')

    def _run():
        try:
            _tratar_resultado_login(user, scraper.concluir_login())
        except Exception as e:
            print(f"[SIRESP] Erro ao concluir o login: {e}")
            _atualizar_status_sessao(user, 'erro', f'Erro: {e}')
            _tratar_erro_scraper(user, e)

    threading.Thread(target=_run, daemon=True).start()
    return {'ok': True, 'mensagem': 'Unidade selecionada. Concluindo o login...'}


# =========================================================
# RECARREGAR CAPTCHA
# =========================================================
def recarregar_captcha(user):
    """Pede pro SIRESP gerar um novo CAPTCHA e devolve a nova imagem."""
    scraper = _SCRAPERS.get(user.id)
    if not scraper:
        return {'ok': False, 'mensagem': 'Sessão expirou. Faça login novamente.'}

    try:
        return scraper.recarregar_captcha()
    except Exception as e:
        print(f"[SIRESP] Erro ao recarregar CAPTCHA do user {user.id}: {e}")
        return {'ok': False, 'mensagem': f'Erro ao recarregar: {e}'}


# =========================================================
# STATUS DO LOGIN
# =========================================================
def _status_login_base(user):
    scraper = _SCRAPERS.get(user.id)
    if not scraper:
        return {'estado': 'sem_sessao', 'logado': False}

    if getattr(scraper, 'aguardando_unidade', False):
        from siresp_scraper import VALUE_ALVO
        return {
            'estado': 'aguardando_unidade',
            'logado': False,
            'unidades': list(scraper.unidades_disponiveis),
            'sugerida': VALUE_ALVO,
        }

    try:
        if scraper.captcha_disponivel and scraper.captcha_imagem_b64:
            return {
                'estado': 'aguardando_captcha',
                'logado': False,
                'captcha_b64': scraper.captcha_imagem_b64,
                'captcha_id': scraper.captcha_id,
            }
    except Exception:
        pass

    if not scraper.logado:
        return {'estado': 'abrindo', 'logado': False}

    if user.id in _OCUPADOS:
        return {'estado': 'logado', 'logado': True, 'unidade': getattr(scraper, 'unidade_atual', None)}

    try:
        _ = scraper.driver.current_url
    except Exception as e:
        print(f"[SIRESP] Chrome morto detectado no status_login do user {user.id}: {e}")
        fechar_sessao(user)
        _atualizar_status_sessao(
            user, 'fechada',
            'Sessão encerrada. Faça login novamente.'
        )
        return {'estado': 'sem_sessao', 'logado': False}

    return {'estado': 'logado', 'logado': True, 'unidade': getattr(scraper, 'unidade_atual', None)}


def status_login(user):
    """Estado do login + (quando houver) o id da última tela do SIRESP capturada."""
    info = _status_login_base(user)
    scraper = _SCRAPERS.get(user.id)
    if scraper is not None and getattr(scraper, 'ultima_tela', None):
        info['tela_id'] = scraper.ultima_tela_id
    return info


def unidade_atual(user):
    """Unidade do SIRESP com a qual o usuário está logado ({valor, texto, nome, codigo}) ou None."""
    scraper = _SCRAPERS.get(user.id)
    return getattr(scraper, 'unidade_atual', None) if scraper is not None else None


def tela_siresp(user):
    """Última tela do SIRESP capturada (imagem em base64, texto e URL) ou None."""
    scraper = _SCRAPERS.get(user.id)
    return getattr(scraper, 'ultima_tela', None) if scraper is not None else None


# =========================================================
# LISTAR MÉDICOS
# =========================================================
def listar_medicos(user, nome, origem='CRM'):
    scraper = _SCRAPERS.get(user.id)
    if not scraper:
        raise Exception('Você não tem sessão ativa. Faça login primeiro.')
    if not scraper.logado:
        raise Exception('Login ainda não concluído.')

    try:
        return scraper.listar_medicos(nome, origem)
    except Exception as e:
        _tratar_erro_scraper(user, e)
        raise


# =========================================================
# EXTRAIR PRODUÇÃO
# =========================================================
def extrair_producao(user, medico, data_ini, data_fim):
    scraper = _SCRAPERS.get(user.id)
    if not scraper:
        raise Exception('Você não tem sessão ativa. Faça login primeiro.')
    if not scraper.logado:
        raise Exception('Sessão ainda não está logada.')

    try:
        dados = scraper.buscar_producao_do_medico(
            medico['nome'], medico.get('crm', ''), medico.get('codigo', ''),
            data_ini, data_fim,
        )
    except Exception as e:
        _tratar_erro_scraper(user, e)
        raise

    nome_medico = medico['nome']
    filtrados = []
    for d in dados:
        esp = d.get('Especialidade', '').strip()
        if esp == nome_medico:
            continue
        if not esp:
            continue
        filtrados.append(d)

    return filtrados


# =========================================================
# FECHAR SESSÃO
# =========================================================
def fechar_sessao(user):
    with _LOCK:
        scraper = _SCRAPERS.pop(user.id, None)

    if scraper:
        try:
            scraper.fechar()
        except Exception as e:
            print(f"[SIRESP] Erro ao fechar scraper do user {user.id}: {e}")
        return True
    return False


def fechar_sessoes_inativas():
    pass