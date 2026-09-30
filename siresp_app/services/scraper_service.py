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

    def _run():
        try:
            resultado_continuar = scraper.continuar_login_apos_captcha(
                cpf_pri, cpf_ult, rg_pri, rg_ult,
            )

            if not isinstance(resultado_continuar, dict):
                resultado_continuar = {
                    'ok': False,
                    'mensagem': 'Resposta inválida do scraper.',
                    'captcha_novo': False,
                }

            if resultado_continuar.get('ok'):
                _atualizar_status_sessao(user, 'logado', 'Login concluído.')
                print(f"[SIRESP] Login OK para user {user.id}")
            else:
                msg = resultado_continuar.get('mensagem', 'Erro desconhecido.')
                captcha_novo = resultado_continuar.get('captcha_novo', False)

                if captcha_novo:
                    _atualizar_status_sessao(user, 'aguardando', msg)
                else:
                    _atualizar_status_sessao(user, 'erro', msg)

                print(f"[SIRESP] Login falhou: {msg}")

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
def status_login(user):
    scraper = _SCRAPERS.get(user.id)
    if not scraper:
        return {'estado': 'sem_sessao', 'logado': False}

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
        return {'estado': 'logado', 'logado': True}

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

    return {'estado': 'logado', 'logado': True}


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