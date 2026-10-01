"""
Módulo com a lógica de scraping do SIRESP.
Modo HEADLESS com CAPTCHA via screenshot (base64).
Login automático (usuário/senha) + CAPTCHA digitado na interface web.

Anti-detecção: user-agent fake + remove navigator.webdriver + flags.
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from datetime import datetime
from io import BytesIO
import base64
import time


# ===== CONSTANTES =====
URL_SIRESP = "https://www.siresp.saude.sp.gov.br/"
# Unidade sugerida (pré-selecionada na tela quando há mais de uma opção)
VALUE_ALVO = "2206_AME SAO JOSE DO RIO PRETO"

CABECALHOS = [
    "Especialidade",
    "Oferta_N",
    "Agend_Total_N", "Agend_Total_Perc",
    "Agend_Bolsao_N", "Agend_Bolsao_Perc",
    "Agend_NaoDist_N", "Agend_NaoDist_Perc",
    "Agend_Cota_N", "Agend_Cota_Perc",
    "Agend_Extra_N", "Agend_Extra_Perc",
    "Agend_TotalGeral_N",
    "Atend_Presencial_N", "Atend_Presencial_Perc",
    "Atend_Teleconsulta_N", "Atend_Teleconsulta_Perc",
    "Atend_Total_N", "Atend_Total_Perc",
    "Ausente_N", "Ausente_Perc",
    "Dispensado_N", "Dispensado_Perc",
    "Desistente_N", "Desistente_Perc",
    "NaoInformado_N", "NaoInformado_Perc",
    "Alta_N", "Alta_Perc",
]


def limpar_valor(txt):
    if txt is None:
        return ""
    return txt.replace("\xa0", " ").replace("&nbsp;", " ").strip()


def _criar_driver():
    """Cria o Chrome em modo HEADLESS com flags anti-detecção."""
    options = Options()

    # === HEADLESS ===
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")

    # === ANTI-DETECÇÃO ===
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option(
        "excludeSwitches", ["enable-automation", "enable-logging"]
    )
    options.add_experimental_option("useAutomationExtension", False)

    # === ESTABILIDADE ===
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=CalculateNativeWinOcclusion")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    # Remove navigator.webdriver (que o Selenium marca como True)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined});"
                )
            },
        )
    except Exception:
        pass

    return driver


class SirespScraper:
    def __init__(self, callback_log=None):
        self.driver = None
        self.wait = None
        self.logado = False
        self.callback_log = callback_log

        self.captcha_disponivel = False
        self.captcha_imagem_b64 = None
        self.captcha_id = 0

        # Escolha de unidade (quando o SIRESP oferece mais de uma)
        self.aguardando_unidade = False
        self.unidades_disponiveis = []
        self._digitos = ("", "", "", "")
        # Unidade com a qual o login foi feito: {valor, texto, nome, codigo} (None = SIRESP não perguntou)
        self.unidade_atual = None

        # Última tela do SIRESP capturada quando o login não segue o caminho conhecido
        self.ultima_tela = None
        self.ultima_tela_id = 0
        self.ultimo_alerta_texto = ""
        self.timeout_pos_captcha = 30

    def log(self, msg):
        if self.callback_log:
            self.callback_log(msg)
        else:
            try:
                print(msg)
            except UnicodeEncodeError:
                print(str(msg).encode('ascii', 'replace').decode('ascii'))

    # =========================================================
    # FECHAR ALERTA DO SIRESP (SweetAlert2)
    # =========================================================
    def _guardar_texto_alerta(self):
        """Lê o texto do popup SweetAlert2 aberto (se houver) antes de fechá-lo."""
        try:
            for p in self.driver.find_elements(By.CLASS_NAME, "swal2-popup"):
                if p.is_displayed():
                    txt = " ".join((p.text or "").split())
                    if txt:
                        self.ultimo_alerta_texto = txt[:300]
                        self.log(f"🚨 Texto do alerta do SIRESP: {self.ultimo_alerta_texto}")
                        return
        except Exception:
            pass

    def _fechar_alerta_siresp(self):
        """Fecha o popup SweetAlert2 do SIRESP se estiver aberto."""
        try:
            self.driver.switch_to.default_content()

            self._guardar_texto_alerta()
            botoes_ok = self.driver.find_elements(
                By.XPATH, "//button[contains(@class, 'swal2-confirm')]"
            )
            for b in botoes_ok:
                if b.is_displayed():
                    try:
                        b.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", b)
                    self.log("🚨 Alerta do SIRESP fechado")
                    time.sleep(0.5)
                    return True

            popups = self.driver.find_elements(By.CLASS_NAME, "swal2-popup")
            for p in popups:
                if p.is_displayed():
                    botoes = p.find_elements(By.TAG_NAME, "button")
                    if botoes:
                        try:
                            botoes[0].click()
                        except Exception:
                            self.driver.execute_script(
                                "arguments[0].click();", botoes[0]
                            )
                        self.log("🚨 Popup do SIRESP fechado (fallback)")
                        time.sleep(0.5)
                        return True

            return False
        except Exception as e:
            self.log(f"⚠️ Erro ao fechar alerta: {e}")
            return False

    # =========================================================
    # CAPTCHA — CAPTURAR
    # =========================================================
    def _capturar_captcha(self):
        """Tira screenshot do elemento #captcha_4 e salva em base64."""
        try:
            self.driver.switch_to.default_content()

            captcha_el = None

            # Tentativa 1: ID exato
            try:
                captcha_el = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.ID, "captcha_4"))
                )
            except Exception:
                pass

            # Tentativa 2: img com 'captcha.php' no src
            if not captcha_el:
                imgs = self.driver.find_elements(
                    By.XPATH, "//img[contains(@src, 'captcha.php')]"
                )
                if imgs:
                    captcha_el = imgs[0]

            # Tentativa 3: img dentro de #captcha-gerado-4
            if not captcha_el:
                imgs = self.driver.find_elements(
                    By.XPATH, "//div[@id='captcha-gerado-4']//img"
                )
                if imgs:
                    captcha_el = imgs[0]

            if not captcha_el:
                self.log("⚠️ Não encontrei o elemento do CAPTCHA")
                return False

            # Espera a imagem carregar
            try:
                carregada = False
                for _ in range(10):
                    carregada = self.driver.execute_script(
                        "var img = arguments[0];"
                        "if (!img) return false;"
                        "return img.complete && img.naturalWidth > 0;",
                        captcha_el,
                    )
                    if carregada:
                        break
                    time.sleep(0.5)

                if not carregada:
                    self.log("⚠️ Imagem do CAPTCHA não carregou direito")

                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", captcha_el
                )
                time.sleep(0.3)
            except Exception as e:
                self.log(f"⚠️ Erro ao esperar carregamento: {e}")

            png_bytes = None

            # Método 1: screenshot_as_png
            try:
                png_bytes = captcha_el.screenshot_as_png
                if png_bytes and len(png_bytes) > 500:
                    self.log(f"📸 Screenshot direto OK ({len(png_bytes)} bytes)")
                else:
                    self.log(f"⚠️ Screenshot suspeito ({len(png_bytes)} bytes)")
                    png_bytes = None
            except Exception as e:
                self.log(f"⚠️ screenshot_as_png falhou ({e})")
                png_bytes = None

            # Método 2: página inteira + recorte
            if not png_bytes:
                try:
                    png_bytes = self._capturar_via_recorte(captcha_el)
                    if png_bytes and len(png_bytes) > 500:
                        self.log(f"📸 Screenshot via recorte OK ({len(png_bytes)} bytes)")
                    else:
                        tam = len(png_bytes) if png_bytes else 0
                        self.log(f"⚠️ Recorte suspeito ({tam} bytes)")
                        png_bytes = None
                except Exception as e:
                    self.log(f"⚠️ Recorte falhou: {e}")

            # Método 3: página inteira
            if not png_bytes:
                try:
                    png_bytes = self.driver.get_screenshot_as_png()
                    self.log(f"📸 Screenshot da página inteira ({len(png_bytes)} bytes)")
                except Exception as e:
                    self.log(f"⚠️ Screenshot da página falhou: {e}")

            if not png_bytes:
                self.log("❌ Não consegui capturar o CAPTCHA")
                return False

            b64 = base64.b64encode(png_bytes).decode("ascii")
            self.captcha_imagem_b64 = f"data:image/png;base64,{b64}"
            self.captcha_disponivel = True
            self.captcha_id += 1

            self.log(f"✅ CAPTCHA capturado (id={self.captcha_id})")
            return True

        except Exception as e:
            self.log(f"⚠️ Erro ao capturar CAPTCHA: {e}")
            return False

    def _capturar_via_recorte(self, elemento):
        """Screenshot da página inteira + recorte via Pillow."""
        try:
            from PIL import Image

            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", elemento
            )
            time.sleep(0.3)

            location = elemento.location
            size = elemento.size

            page_png = self.driver.get_screenshot_as_png()
            img = Image.open(BytesIO(page_png))

            left = location["x"]
            top = location["y"]
            right = left + size["width"]
            bottom = top + size["height"]

            cropped = img.crop((left, top, right, bottom))

            buf = BytesIO()
            cropped.save(buf, format="PNG")
            return buf.getvalue()

        except ImportError:
            self.log("⚠️ Pillow não instalado")
            return None
        except Exception as e:
            self.log(f"⚠️ Erro no recorte: {e}")
            return None

    # =========================================================
    # CAPTCHA — RECARREGAR
    # =========================================================
    def recarregar_captcha(self):
        """Fecha alertas, clica em img4 e captura a nova imagem."""
        try:
            self.driver.switch_to.default_content()

            self._fechar_alerta_siresp()
            time.sleep(0.3)

            src_antigo = None
            try:
                captcha_el = self.driver.find_element(By.ID, "captcha_4")
                src_antigo = captcha_el.get_attribute("src") or ""
            except Exception:
                pass

            botao_reload = None
            try:
                botao_reload = self.driver.find_element(By.ID, "img4")
            except Exception:
                pass

            if not botao_reload:
                try:
                    candidatos = self.driver.find_elements(
                        By.XPATH,
                        "//img[contains(@src, 'reload') "
                        "or contains(@onclick, 'reload')]",
                    )
                    for c in candidatos:
                        if c.is_displayed():
                            botao_reload = c
                            break
                except Exception:
                    pass

            if not botao_reload:
                return {"ok": False, "mensagem": "Não achei o botão de recarregar CAPTCHA."}

            try:
                self.driver.execute_script("arguments[0].click();", botao_reload)
                self.log("🔄 Botão de recarregar clicado (via JS)")
            except Exception:
                botao_reload.click()
                self.log("🔄 Botão de recarregar clicado")

            # Espera o src mudar
            novo_src = None
            inicio = time.time()
            while time.time() - inicio < 5:
                try:
                    captcha_el = self.driver.find_element(By.ID, "captcha_4")
                    novo_src = captcha_el.get_attribute("src") or ""
                    if novo_src and novo_src != src_antigo:
                        self.log("✅ CAPTCHA trocou de src")
                        break
                except Exception:
                    pass
                time.sleep(0.2)

            if not novo_src or novo_src == src_antigo:
                self.log("⚠️ CAPTCHA não trocou de src")

            time.sleep(0.5)

            self.captcha_disponivel = False
            self.captcha_imagem_b64 = None

            if self._capturar_captcha():
                return {
                    "ok": True,
                    "captcha_b64": self.captcha_imagem_b64,
                    "captcha_id": self.captcha_id,
                    "mensagem": "Novo CAPTCHA carregado.",
                }

            return {
                "ok": False,
                "mensagem": "CAPTCHA foi recarregado mas não consegui capturar a imagem.",
            }

        except Exception as e:
            return {"ok": False, "mensagem": f"Erro ao recarregar: {e}"}

    # =========================================================
    # CAPTCHA — ENVIAR
    # =========================================================
    def enviar_captcha(self, texto):
        """
        Preenche o CAPTCHA em txt_captcha_4, copia o valor pro hidden cg_4
        e chama valida(4).
        """
        if not self.driver:
            return {"ok": False, "mensagem": "Driver não está ativo."}

        texto = (texto or "").strip()
        if not texto:
            return {"ok": False, "mensagem": "Digite o texto do CAPTCHA."}
        self.ultimo_alerta_texto = ""

        try:
            self.driver.switch_to.default_content()

            # --- 1) Acha o input visível ---
            campo_captcha = None
            try:
                campo_captcha = self.driver.find_element(By.ID, "txt_captcha_4")
            except Exception:
                try:
                    campo_captcha = self.driver.find_element(
                        By.XPATH, "//input[@name='captcha']"
                    )
                except Exception:
                    pass

            if not campo_captcha:
                return {"ok": False, "mensagem": "Não achei o campo do CAPTCHA."}

            # --- 2) Preenche via JS ---
            try:
                self.driver.execute_script(
                    """
                    var el = arguments[0];
                    var txt = arguments[1];
                    el.focus();
                    el.value = txt;
                    el.dispatchEvent(new Event('input',  {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
                    el.dispatchEvent(new Event('blur', {bubbles: true}));
                    """,
                    campo_captcha,
                    texto,
                )
                self.log(f"📝 CAPTCHA preenchido via JS: '{texto}'")
            except Exception:
                try:
                    campo_captcha.clear()
                    campo_captcha.send_keys(texto)
                    self.log(f"📝 CAPTCHA preenchido via send_keys: '{texto}'")
                except Exception as e2:
                    return {"ok": False, "mensagem": f"Erro ao preencher: {e2}"}

            # --- 3) Preenche o hidden cg_4 ---
            try:
                cg_preenchido = self.driver.execute_script(
                    """
                    var cg = document.getElementById('cg_4');
                    if (!cg) return false;
                    cg.value = arguments[0];
                    return true;
                    """,
                    texto,
                )
                if cg_preenchido:
                    self.log(f"✅ cg_4 preenchido com '{texto}'")
                else:
                    self.log("⚠️ Campo cg_4 não encontrado")
            except Exception as e:
                self.log(f"⚠️ Erro ao preencher cg_4: {e}")

            # --- 4) Confere ---
            try:
                valores = self.driver.execute_script(
                    """
                    var txt = document.getElementById('txt_captcha_4');
                    var cg  = document.getElementById('cg_4');
                    return {
                        txt: txt ? txt.value : '(sem txt)',
                        cg:  cg  ? cg.value  : '(sem cg)'
                    };
                    """
                )
                self.log(
                    f"🔎 txt_captcha_4='{valores.get('txt')}' | "
                    f"cg_4='{valores.get('cg')}'"
                )
            except Exception:
                pass

            # --- 5) Chama valida(4) ---
            time.sleep(0.3)
            clicou = False

            try:
                self.driver.execute_script("valida(4);")
                self.log("🖱️ valida(4) executada")
                clicou = True
            except Exception as e:
                self.log(f"⚠️ valida(4) falhou: {e}")

            if not clicou:
                try:
                    botao = self.driver.find_element(By.ID, "btn_entrar_4")
                    self.driver.execute_script("arguments[0].click();", botao)
                    self.log("🖱️ btn_entrar_4 clicado (via JS)")
                    clicou = True
                except Exception as e:
                    self.log(f"⚠️ clique no botão falhou: {e}")

            if not clicou:
                return {"ok": False, "mensagem": "Não consegui clicar em Entrar."}

            # --- 6) Espera pra ver se aparece alerta ---
            time.sleep(1.5)
            self._fechar_alerta_siresp()

            self.captcha_disponivel = False
            return {"ok": True, "mensagem": "CAPTCHA enviado."}

        except Exception as e:
            return {"ok": False, "mensagem": f"Erro ao enviar CAPTCHA: {e}"}

    # =========================================================
    # LOGIN — FASE 1
    # =========================================================
    def fazer_login(self, usuario, senha,
                    cpf_primeiros, cpf_ultimos,
                    rg_primeiros, rg_ultimos):

        self.unidade_atual = None
        self.log("🌐 Abrindo navegador (headless)...")
        self.driver = _criar_driver()
        self.driver.get(URL_SIRESP)
        self.wait = WebDriverWait(self.driver, 15)

        self.log("🥇 Preenchendo usuário e senha...")
        self.driver.find_element(By.ID, "btn-4").click()

        campo_user = self.wait.until(
            EC.presence_of_element_located((By.ID, "usuario_4"))
        )
        campo_user.send_keys(usuario)
        self.driver.find_element(By.ID, "senha_4").send_keys(senha)

        time.sleep(1.5)

        if not self._capturar_captcha():
            raise Exception(
                "Não consegui capturar o CAPTCHA. "
                "Verifique se o seletor ainda bate com a página do SIRESP."
            )

        self.log("⏳ Aguardando o usuário digitar o CAPTCHA...")

    # =========================================================
    # LOCALIZAR ELEMENTOS EM QUALQUER IFRAME
    # =========================================================
    def _caminho_ate(self, seletor, profundidade=4):
        """
        Procura `seletor` (CSS) na página e, recursivamente, em todos os iframes/frames.
        Retorna a lista de índices de frame até o primeiro contexto que o contém
        ([] = página principal) ou None. Deixa o driver na página principal.
        """
        def dfs(caminho):
            try:
                if self.driver.find_elements(By.CSS_SELECTOR, seletor):
                    return list(caminho)
                if len(caminho) >= profundidade:
                    return None
                total = len(self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
            except Exception:
                return None
            for i in range(total):
                try:
                    frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
                    self.driver.switch_to.frame(frames[i])
                except Exception:
                    continue
                achou = dfs(caminho + [i])
                if achou is not None:
                    return achou
                try:
                    self.driver.switch_to.parent_frame()
                except Exception:
                    return None
            return None

        try:
            self.driver.switch_to.default_content()
            return dfs([])
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

    def _entrar_no_caminho(self, caminho):
        self.driver.switch_to.default_content()
        for i in caminho:
            frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            self.driver.switch_to.frame(frames[i])

    def _entrar_onde_existe(self, seletor, espera=0):
        """Entra no frame que contém `seletor`. True se achou (o driver fica lá dentro)."""
        fim = time.time() + espera
        while True:
            caminho = self._caminho_ate(seletor)
            if caminho is not None:
                try:
                    self._entrar_no_caminho(caminho)
                    return True
                except Exception:
                    pass
            if time.time() >= fim:
                break
            time.sleep(0.4)
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        return False

    # =========================================================
    # O QUE O SIRESP MOSTROU (diagnóstico para a tela do app)
    # =========================================================
    def _diagnosticar_tela(self):
        """
        Captura a tela atual do SIRESP (imagem + texto visível) para o app mostrar ao
        usuário quando o login não segue o caminho conhecido. Nunca levanta exceção.
        """
        diag = {"imagem_b64": "", "texto": "", "url": "", "titulo": "", "alerta": self.ultimo_alerta_texto}
        try:
            self.driver.switch_to.default_content()
            diag["url"] = self.driver.current_url
            diag["titulo"] = self.driver.title
        except Exception:
            pass
        try:
            png = self.driver.get_screenshot_as_png()
            diag["imagem_b64"] = "data:image/png;base64," + base64.b64encode(png).decode()
        except Exception as e:
            self.log(f"⚠️ Não consegui tirar screenshot da tela: {e}")

        partes = []

        def texto_do_contexto(prof):
            try:
                t = self.driver.execute_script(
                    "return (document.body ? document.body.innerText : '') || '';")
                t = " ".join((t or "").split())
                if t:
                    partes.append(t)
                if prof >= 3:
                    return
                total = len(self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
                for i in range(total):
                    frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
                    self.driver.switch_to.frame(frames[i])
                    texto_do_contexto(prof + 1)
                    self.driver.switch_to.parent_frame()
            except Exception:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass

        try:
            self.driver.switch_to.default_content()
            texto_do_contexto(0)
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
        diag["texto"] = " | ".join(partes)[:1500]
        self.ultima_tela = diag
        self.ultima_tela_id += 1
        self.log(f"🖼️ Tela do SIRESP capturada (#{self.ultima_tela_id}): {diag['texto'][:200]}")
        return diag

    def _estado_pos_captcha(self):
        """'unidade' | 'digitos' | 'logado' | None, olhando a página e todos os iframes."""
        if self._caminho_ate("input[name='unidade']") is not None:
            return "unidade"
        if self._caminho_ate("#digito_doc") is not None:
            return "digitos"
        try:
            self.driver.switch_to.default_content()
            if self.driver.find_elements(By.ID, "site"):
                return "logado"
        except Exception:
            pass
        return None

    # =========================================================
    # LOGIN — FASE 2
    # =========================================================
    def continuar_login_apos_captcha(self, cpf_primeiros, cpf_ultimos,
                                      rg_primeiros, rg_ultimos, unidade_preferida=""):
        """
        Roda após o envio do CAPTCHA. NUNCA retorna None.

        A tela que o SIRESP mostra depois do CAPTCHA pode ser a escolha de unidade, os
        dígitos de CPF/RG ou já o sistema — e pode vir fora do iframe "site". Por isso
        olhamos a página inteira. Se houver mais de uma unidade (sem preferência salva),
        o login PAUSA e retorna {"aguardando_unidade": True, "unidades": [...]}: a escolha
        é feita depois por escolher_unidade() e o login é concluído por concluir_login().
        """
        try:
            inicio = time.time()
            self.ultima_tela = None

            estado = None
            visto_logado = None
            while time.time() - inicio < self.timeout_pos_captcha:
                estado = self._estado_pos_captcha()
                if estado in ("unidade", "digitos"):
                    break
                if estado == "logado":
                    # o sistema carregou: dá uma folga curta para uma tela de unidade/dígitos
                    # aparecer dentro dele antes de concluir que não há nenhuma
                    visto_logado = visto_logado or time.time()
                    if time.time() - visto_logado >= 3:
                        break
                time.sleep(0.4)

            if estado is None:
                self.log("❌ Login não completou. Capturando a tela do SIRESP e um novo CAPTCHA...")
                self.driver.switch_to.default_content()
                time.sleep(1)

                self._fechar_alerta_siresp()
                time.sleep(0.5)
                self._diagnosticar_tela()          # mostra no app o que o SIRESP exibiu

                if self._capturar_captcha():
                    extra = f" O SIRESP avisou: {self.ultimo_alerta_texto}" if self.ultimo_alerta_texto else ""
                    return {
                        "ok": False,
                        "mensagem": "CAPTCHA inválido. Tente novamente." + extra,
                        "captcha_novo": True,
                    }

                return {
                    "ok": False,
                    "mensagem": "Login não completou. Veja a tela do SIRESP abaixo.",
                    "captcha_novo": False,
                }

            self.log(f"🎉 Tela detectada após o CAPTCHA: {estado}. Prosseguindo...")
            self._digitos = (cpf_primeiros, cpf_ultimos, rg_primeiros, rg_ultimos)

            # ETAPA 3: unidade (pode pausar para o usuário escolher)
            if estado != "digitos":
                etapa = self._etapa_unidade(unidade_preferida, espera=8 if estado == "unidade" else 3)
                if etapa == "aguardando":
                    self.log(f"⏸️  {len(self.unidades_disponiveis)} unidades: aguardando escolha do usuário")
                    return {
                        "ok": False,
                        "aguardando_unidade": True,
                        "unidades": list(self.unidades_disponiveis),
                        "sugerida": VALUE_ALVO,
                        "mensagem": "Selecione a unidade para continuar.",
                        "captcha_novo": False,
                    }
            else:
                etapa = "nao_apareceu"

            # ETAPA 4: dígitos + finalização (se acabou de passar pela tela de unidade,
            # a página de dígitos pode demorar mais a carregar)
            return self._finalizar_login(
                *self._digitos, espera_digitos=10 if etapa == "selecionada" else 3
            )

        except Exception as e:
            self.log(f"❌ Erro inesperado no login: {e}")
            import traceback
            traceback.print_exc()
            try:
                self._diagnosticar_tela()
            except Exception:
                pass
            return {
                "ok": False,
                "mensagem": f"Erro inesperado: {e}",
                "captcha_novo": False,
            }

    def concluir_login(self):
        """Continua o login (dígitos de CPF/RG) depois que a unidade foi escolhida."""
        try:
            return self._finalizar_login(*self._digitos, espera_digitos=10)
        except Exception as e:
            self.log(f"❌ Erro inesperado ao concluir o login: {e}")
            try:
                self._diagnosticar_tela()
            except Exception:
                pass
            return {"ok": False, "mensagem": f"Erro inesperado: {e}", "captcha_novo": False}

    def _finalizar_login(self, cpf_primeiros, cpf_ultimos, rg_primeiros, rg_ultimos,
                         espera_digitos=3):
        # dígitos de segurança
        try:
            pediu_digitos = self._tentar_digitos_seguranca(
                cpf_primeiros, cpf_ultimos, rg_primeiros, rg_ultimos, espera_digitos
            )
            if not pediu_digitos:
                self.log("ℹ️  Tela de dígitos não apareceu")
        except Exception as e:
            msg = str(e)
            self.log(f"❌ Erro nos dígitos: {msg}")
            self._diagnosticar_tela()
            return {
                "ok": False,
                "mensagem": f"Dígitos de segurança rejeitados: {msg}",
                "captcha_novo": False,
            }

        self.driver.switch_to.default_content()
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.find_elements(By.ID, "site")
            )
        except TimeoutException:
            self.log("❌ O sistema do SIRESP não carregou depois do login")
            self._diagnosticar_tela()
            return {
                "ok": False,
                "mensagem": "O SIRESP não abriu o sistema depois do login. Veja a tela abaixo.",
                "captcha_novo": False,
            }
        time.sleep(0.5)

        self.logado = True
        self.ultima_tela = None
        self.log("🎉 Login completo! Sessão ativa.")
        return {"ok": True, "mensagem": "Login concluído."}

    # =========================================================
    # SELECIONAR UNIDADE
    # =========================================================
    _JS_UNIDADES = """
        return Array.from(document.querySelectorAll("input[name='unidade']")).map(function (r) {
            var lb = r.closest('label') || r.parentElement;
            var txt = (lb ? lb.innerText : r.value) || r.value;
            return {valor: r.value, texto: txt.replace(/\\s+/g, ' ').trim()};
        });
    """

    def _entrar_no_frame_unidade(self, espera=5):
        """
        Procura os radios 'unidade' na página ou em qualquer iframe.
        Retorna True se achou (o driver fica dentro do frame certo).
        Retorna False logo que aparece a tela de dígitos (não há escolha de unidade).
        """
        fim = time.time() + espera
        while True:
            if self._entrar_onde_existe("input[name='unidade']", 0):
                return True
            if self._caminho_ate("#digito_doc") is not None:
                return False
            if time.time() >= fim:
                break
            time.sleep(0.4)
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        return False

    def _listar_unidades(self, espera=5):
        """Lista [{valor, texto}] das unidades oferecidas pelo SIRESP (vazio se não há a tela)."""
        if not self._entrar_no_frame_unidade(espera):
            return []
        unidades = self.driver.execute_script(self._JS_UNIDADES) or []
        self.driver.switch_to.default_content()
        return unidades

    @staticmethod
    def _info_unidade(valor, texto=""):
        """'2206_AME SAO JOSE DO RIO PRETO' -> código 2206, nome 'AME SAO JOSE DO RIO PRETO'."""
        codigo, _, nome = (valor or "").partition("_")
        if not nome:
            codigo, nome = "", (texto or valor or "")
        return {"valor": valor, "texto": texto or nome, "nome": nome.strip(), "codigo": codigo.strip()}

    def _clicar_unidade(self, valor, texto=""):
        """Marca o radio da unidade e confirma com OK."""
        if not self._entrar_no_frame_unidade(8):
            raise Exception("A tela de seleção de unidade não está mais disponível.")

        marcou = self.driver.execute_script(
            """
            var alvo = arguments[0];
            var rs = document.querySelectorAll("input[name='unidade']");
            for (var i = 0; i < rs.length; i++) {
                if (rs[i].value === alvo) { rs[i].click(); return true; }
            }
            return false;
            """,
            valor,
        )
        if not marcou:
            self.driver.switch_to.default_content()
            raise Exception("Unidade não encontrada na lista do SIRESP.")

        # Botão OK: <input type="submit" name="escolher" id="escolher" value="Ok">
        botoes = (
            self.driver.find_elements(By.ID, "escolher")
            or self.driver.find_elements(
                By.XPATH, "//input[@name='escolher' and @value='Ok']")
            or self.driver.find_elements(
                By.XPATH, "//input[@type='submit' or @type='button']")
        )
        if not botoes:
            self.driver.switch_to.default_content()
            raise Exception("Botão OK da seleção de unidade não encontrado.")
        self.driver.execute_script("arguments[0].click();", botoes[0])
        self.driver.switch_to.default_content()

        # Só segue quando a tela de unidade sumiu (vem a tela de dígitos de CPF/RG)
        if not self._aguardar_saida_unidade(10):
            raise Exception(
                "O SIRESP não avançou depois de clicar em OK. Tente escolher a unidade de novo."
            )
        self.unidade_atual = self._info_unidade(valor, texto)
        self.log(f"✅ Unidade selecionada: {valor}")

    def _aguardar_saida_unidade(self, timeout=10):
        """True quando não há mais radios de unidade na tela (ou apareceu o campo de dígitos)."""
        fim = time.time() + timeout
        while time.time() < fim:
            if not self._entrar_no_frame_unidade(espera=0):
                return True
            time.sleep(0.4)
        return False

    def _etapa_unidade(self, preferida="", espera=5):
        """
        Retorna 'nao_apareceu' | 'selecionada' | 'aguardando'.
        Escolhe sozinho se a unidade preferida está na lista ou se só há uma;
        caso contrário guarda a lista e pausa para o usuário escolher.
        """
        self.unidades_disponiveis = []
        self.aguardando_unidade = False
        try:
            unidades = self._listar_unidades(espera)
        except Exception as e:
            self.log(f"⚠️ Erro ao listar unidades: {e}")
            return "nao_apareceu"

        if not unidades:
            self.log("ℹ️  Tela de unidade não apareceu")
            return "nao_apareceu"

        valores = [u["valor"] for u in unidades]
        if preferida and preferida in valores:
            escolha = preferida
        elif len(valores) == 1:
            escolha = valores[0]
        else:
            escolha = None

        if escolha:
            texto = next((u["texto"] for u in unidades if u["valor"] == escolha), "")
            self._clicar_unidade(escolha, texto)
            return "selecionada"

        self.unidades_disponiveis = unidades
        self.aguardando_unidade = True
        return "aguardando"

    def escolher_unidade(self, valor):
        """Aplica a unidade escolhida pelo usuário. Depois chame concluir_login()."""
        if not self.aguardando_unidade:
            return {"ok": False, "mensagem": "Nenhuma escolha de unidade está pendente."}
        if valor not in [u["valor"] for u in self.unidades_disponiveis]:
            return {"ok": False, "mensagem": "Unidade inválida."}
        texto = next((u["texto"] for u in self.unidades_disponiveis if u["valor"] == valor), "")
        try:
            self._clicar_unidade(valor, texto)
        except Exception as e:
            return {"ok": False, "mensagem": str(e)}
        self.aguardando_unidade = False
        self.unidades_disponiveis = []
        return {"ok": True, "mensagem": "Unidade selecionada."}

    # =========================================================
    # DÍGITOS DE SEGURANÇA
    # =========================================================
    def _tentar_digitos_seguranca(self, cpf_primeiros, cpf_ultimos,
                                 rg_primeiros, rg_ultimos, espera=3):
        try:
            # o campo pode estar dentro do iframe "site" ou na página principal
            if not self._entrar_onde_existe("#digito_doc", espera):
                self.driver.switch_to.default_content()
                return False
            campo_digito = self.driver.find_element(By.ID, "digito_doc")

            texto_pedido = None
            for lb in self.driver.find_elements(By.TAG_NAME, "label"):
                try:
                    txt = lb.text.strip()
                    if "dígitos" in txt.lower() and ("RG" in txt or "CPF" in txt):
                        texto_pedido = txt
                        break
                except Exception:
                    continue

            if texto_pedido:
                t = texto_pedido.lower()
                if "rg" in t:
                    digito = rg_ultimos if "últimos" in t else rg_primeiros
                else:
                    digito = cpf_ultimos if "últimos" in t else cpf_primeiros
                self.log(f"📋 SIRESP pedindo: {texto_pedido} → enviando: {digito}")
            else:
                digito = cpf_ultimos
                self.log(f"⚠️ Label não achado. Enviando CPF_ULTIMOS: {digito}")

            campo_digito.send_keys(digito)
            botao = (self.driver.find_elements(By.ID, "btn_entrar")
                     or self.driver.find_elements(By.XPATH, "//input[@type='submit' or @type='button']"))
            if not botao:
                raise Exception("Botão de confirmar os dígitos não encontrado.")
            botao[0].click()

            self.driver.switch_to.default_content()
            time.sleep(1.5)

            # se o campo continua na tela, o SIRESP recusou os dígitos
            if self._caminho_ate("#digito_doc") is not None:
                self.log("❌ Dígitos de segurança rejeitados pelo SIRESP")
                raise Exception(
                    "Dígitos de segurança rejeitados. "
                    "Verifique se CPF/RG estão corretos."
                )

            return True

        except Exception as e:
            self.log(f"⚠️  Erro ao tentar preencher dígitos: {e}")
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            raise

    # =========================================================
    # ESCONDER / MOSTRAR (headless não faz nada)
    # =========================================================
    def esconder_navegador(self):
        pass

    def mostrar_navegador(self):
        pass

    def _entrar_no_iframe_relatorio(self):
        self.driver.switch_to.default_content()
        iframe_site = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "site"))
        )
        self.driver.switch_to.frame(iframe_site)
        iframe_principal = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "principal"))
        )
        self.driver.switch_to.frame(iframe_principal)

    # =========================================================
    # VALIDAÇÃO / ALERTA
    # =========================================================
    def _validar_periodo(self, data_ini, data_fim):
        try:
            d1 = datetime.strptime(data_ini, "%d/%m/%Y")
            d2 = datetime.strptime(data_fim, "%d/%m/%Y")
        except ValueError:
            raise Exception("Formato de data inválido. Use DD/MM/AAAA.")

        if d2 < d1:
            raise Exception("A data final não pode ser anterior à inicial.")

        dias = (d2 - d1).days
        if dias > 120:
            raise Exception(
                f"O período máximo do SIRESP é de 120 dias.\n"
                f"Você pediu {dias} dias ({data_ini} a {data_fim}).\n"
                f"Reduza o intervalo e tente de novo."
            )

        self.log(f"✔️  Período válido: {dias} dias")

    def _tratar_alerta(self):
        try:
            alerta = self.driver.switch_to.alert
            texto = alerta.text
            self.log(f"⚠️ Alerta do SIRESP: {texto}")
            alerta.accept()
            return texto
        except Exception:
            return None

    # =========================================================
    # NAVEGAR ATÉ O P05
    # =========================================================
    def _ir_para_p05(self):
        self.log("📊 Navegando até P05...")

        self.driver.switch_to.default_content()
        url_atual = self.driver.current_url
        if "principal.php" not in url_atual:
            self.driver.get(URL_SIRESP + "principal.php")
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "site"))
            )

        self._tratar_alerta()

        self.driver.switch_to.default_content()
        iframe_site = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "site"))
        )
        self.driver.switch_to.frame(iframe_site)

        self.wait.until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Relatório')]"))
        ).click()

        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Produtividade')]"))
        ).click()

        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(., 'Produção X Profissional')]")
            )
        ).click()

        self._entrar_no_iframe_relatorio()
        self.log("✅ Dentro do P05")

    # =========================================================
    # LISTAR MÉDICOS
    # =========================================================
    def listar_medicos(self, nome_parcial, origem="CRM"):
        if not self.logado:
            raise Exception("Faça o login primeiro.")

        self._ir_para_p05()

        self.log(f"🔍 Buscando médicos com: '{nome_parcial}'")

        select_origem = Select(
            self.wait.until(
                EC.presence_of_element_located((By.ID, "FLT_ORIGEM"))
            )
        )
        select_origem.select_by_value(origem)

        self._entrar_no_iframe_relatorio()

        campo_nome = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.ID, "nameProfissional"))
        )
        campo_nome.clear()
        campo_nome.send_keys(nome_parcial)

        self.driver.find_element(
            By.XPATH, "//input[@name='btn_acao' and @value='Buscar']"
        ).click()

        self._tratar_alerta()
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//td[contains(@onclick, 'selectProf')]")
                )
            )
        except Exception:
            pass

        self._entrar_no_iframe_relatorio()
        tds = self.driver.find_elements(
            By.XPATH, "//td[contains(@onclick, 'selectProf')]"
        )

        medicos = []
        for td in tds:
            try:
                nome = td.text.strip()
                onclick = td.get_attribute("onclick")

                import re
                match = re.search(
                    r"selectProf\('([^']+)',\s*'([^']+)',\s*'([^']+)'\)", onclick
                )
                if match:
                    medicos.append(
                        {
                            "nome": match.group(1),
                            "crm": match.group(2),
                            "codigo": match.group(3),
                        }
                    )
                elif nome:
                    medicos.append({"nome": nome, "crm": "", "codigo": ""})
            except Exception:
                continue

        self.log(f"✅ Encontrados {len(medicos)} médicos")
        return medicos

    # =========================================================
    # BUSCAR PRODUÇÃO DO MÉDICO
    # =========================================================
    def buscar_producao_do_medico(self, nome_medico, crm_medico, codigo_medico,
                                   data_ini, data_fim):
        if not self.logado:
            raise Exception("Faça o login primeiro.")

        self._validar_periodo(data_ini, data_fim)

        self.log(f"📌 Selecionando: {nome_medico}")
        self._entrar_no_iframe_relatorio()

        td_medico = None
        try:
            td_medico = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        f"//td[contains(@onclick, \"selectProf('{nome_medico}'\")]",
                    )
                )
            )
        except Exception:
            try:
                td_medico = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            f"//td[contains(@onclick, 'selectProf') and "
                            f"contains(text(), \"{nome_medico}\")]",
                        )
                    )
                )
            except Exception:
                try:
                    self.driver.save_screenshot("debug_erro_medico.png")
                except Exception:
                    pass
                raise Exception(f"Não achei '{nome_medico}' na lista de médicos.")

        td_medico.click()

        self._entrar_no_iframe_relatorio()
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.ID, "DATA_INI"))
        )

        self.log(f"📌 Datas: {data_ini} a {data_fim}")

        try:
            self._entrar_no_iframe_relatorio()
            self.driver.execute_script(
                "var el=document.getElementById('DATA_INI'); if(el){el.onblur=null;}"
            )
            campo_ini = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "DATA_INI"))
            )
            self.driver.execute_script("arguments[0].focus();", campo_ini)
            time.sleep(0.5)
            campo_ini.clear()
            time.sleep(0.2)
            campo_ini.send_keys(data_ini)
            time.sleep(0.5)
        except Exception as e:
            self.log(f"   ⚠️ Erro no DATA_INI: {e}")

        try:
            self._entrar_no_iframe_relatorio()
            self.driver.execute_script(
                "var el=document.getElementById('DATA_FIM'); if(el){el.onblur=null;}"
            )
            campo_fim = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "DATA_FIM"))
            )
            self.driver.execute_script("arguments[0].focus();", campo_fim)
            time.sleep(0.5)
            campo_fim.clear()
            time.sleep(0.2)
            campo_fim.send_keys(data_fim)
            time.sleep(0.5)
        except Exception as e:
            self.log(f"   ⚠️ Erro no DATA_FIM: {e}")

        try:
            self._entrar_no_iframe_relatorio()
            v_ini = self.driver.execute_script(
                "return document.getElementById('DATA_INI').value;"
            )
            v_fim = self.driver.execute_script(
                "return document.getElementById('DATA_FIM').value;"
            )
            self.log(f"   ✔️  DATA_INI='{v_ini}' DATA_FIM='{v_fim}'")
        except Exception as e:
            self.log(f"   ⚠️ Não consegui ler: {e}")

        try:
            checkbox = self.driver.find_element(By.ID, "mostra_agenda")
            if not checkbox.is_selected():
                checkbox.click()
        except Exception:
            pass

        self.log("📌 Buscar final...")
        try:
            self.driver.find_element(
                By.XPATH,
                "//input[@type='submit' and @name='btn_acao' and @value='Buscar']",
            ).click()
        except Exception:
            self.driver.execute_script(
                "document.querySelector(\"input[type='submit'][name='btn_acao']\").click();"
            )

        self._tratar_alerta()

        self._entrar_no_iframe_relatorio()
        try:
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//table[contains(., 'Especialidade Médica e Grupo de Cota')]",
                    )
                )
            )
        except TimeoutException:
            # Sem tabela = médico sem produção no período
            self.log("ℹ️ Tabela de produção não apareceu: sem produção no período")
            return []
        self.log("✅ Relatório carregado. Extraindo...")

        tabelas = self.driver.find_elements(By.TAG_NAME, "table")
        tabela = None
        for t in tabelas:
            try:
                texto = t.text
                if (
                    "Especialidade Médica e Grupo de Cota" in texto
                    and "Oferta" in texto
                    and "Agendamentos" in texto
                ):
                    tabela = t
                    break
            except Exception:
                continue

        if not tabela:
            try:
                self.driver.save_screenshot("debug_erro_tabela.png")
            except Exception:
                pass
            raise Exception("Não encontrei a tabela de produção!")

        linhas = tabela.find_elements(By.TAG_NAME, "tr")
        dados = []
        for i, linha in enumerate(linhas):
            celulas = linha.find_elements(By.TAG_NAME, "td")
            if len(celulas) != 29:
                continue
            valores = [limpar_valor(c.text) for c in celulas]
            nome = valores[0]
            if not nome:
                continue
            reg = {"linha_origem": i}
            for j, cab in enumerate(CABECALHOS):
                reg[cab] = valores[j]
            dados.append(reg)

        self.log(f"✅ Extraídos {len(dados)} registros")
        return dados

    # =========================================================
    # FECHAR
    # =========================================================
    def fechar(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self.logado = False
            self.aguardando_unidade = False
            self.unidades_disponiveis = []