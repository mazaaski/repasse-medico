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

    def log(self, msg):
        if self.callback_log:
            self.callback_log(msg)
        else:
            print(msg)

    # =========================================================
    # FECHAR ALERTA DO SIRESP (SweetAlert2)
    # =========================================================
    def _fechar_alerta_siresp(self):
        """Fecha o popup SweetAlert2 do SIRESP se estiver aberto."""
        try:
            self.driver.switch_to.default_content()

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
    # LOGIN — FASE 2
    # =========================================================
    def continuar_login_apos_captcha(self, cpf_primeiros, cpf_ultimos,
                                      rg_primeiros, rg_ultimos):
        """Roda após o envio do CAPTCHA. NUNCA retorna None."""
        try:
            inicio = time.time()
            timeout = 30

            logado = False
            while time.time() - inicio < timeout:
                try:
                    self.driver.switch_to.default_content()
                    iframes = self.driver.find_elements(By.ID, "site")
                    if iframes:
                        logado = True
                        break
                except Exception:
                    pass
                time.sleep(0.4)

            if not logado:
                self.log("❌ Login não completou. Capturando novo CAPTCHA...")
                self.driver.switch_to.default_content()
                time.sleep(1)

                self._fechar_alerta_siresp()
                time.sleep(0.5)

                if self._capturar_captcha():
                    return {
                        "ok": False,
                        "mensagem": "CAPTCHA inválido. Tente novamente.",
                        "captcha_novo": True,
                    }

                return {
                    "ok": False,
                    "mensagem": "Login não completou. Verifique suas credenciais.",
                    "captcha_novo": False,
                }

            self.log("🎉 Login detectado! Prosseguindo...")

            # ETAPA 3: unidade
            try:
                selecionou_unidade = self._tentar_selecionar_unidade()
                if selecionou_unidade:
                    self.log("✅ Unidade selecionada")
                else:
                    self.log("ℹ️  Tela de unidade não apareceu")
            except Exception as e:
                self.log(f"⚠️ Erro na etapa de unidade: {e}")

            # ETAPA 4: dígitos
            try:
                pediu_digitos = self._tentar_digitos_seguranca(
                    cpf_primeiros, cpf_ultimos, rg_primeiros, rg_ultimos
                )
                if not pediu_digitos:
                    self.log("ℹ️  Tela de dígitos não apareceu")
            except Exception as e:
                msg = str(e)
                self.log(f"❌ Erro nos dígitos: {msg}")
                return {
                    "ok": False,
                    "mensagem": f"Dígitos de segurança rejeitados: {msg}",
                    "captcha_novo": False,
                }

            # FINALIZA
            self.driver.switch_to.default_content()
            WebDriverWait(self.driver, 30).until(
                lambda d: d.find_elements(By.ID, "site")
            )
            time.sleep(0.5)

            self.logado = True
            self.log("🎉 Login completo! Sessão ativa.")
            return {"ok": True, "mensagem": "Login concluído."}

        except Exception as e:
            self.log(f"❌ Erro inesperado no login: {e}")
            import traceback
            traceback.print_exc()
            return {
                "ok": False,
                "mensagem": f"Erro inesperado: {e}",
                "captcha_novo": False,
            }

    # =========================================================
    # SELECIONAR UNIDADE
    # =========================================================
    def _tentar_selecionar_unidade(self):
        try:
            self.driver.switch_to.default_content()
            iframe_site = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.ID, "site"))
            )
            self.driver.switch_to.frame(iframe_site)

            iframes_principal = self.driver.find_elements(By.ID, "principal")
            if not iframes_principal:
                self.driver.switch_to.default_content()
                return False

            self.driver.switch_to.frame(iframes_principal[0])

            try:
                radio = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            f"//input[@name='unidade' and @value='{VALUE_ALVO}']",
                        )
                    )
                )
            except Exception:
                self.driver.switch_to.default_content()
                return False

            radio.click()
            self.driver.find_element(
                By.XPATH, "//input[@name='escolher' and @value='Ok']"
            ).click()

            self.driver.switch_to.default_content()
            time.sleep(0.5)
            return True

        except Exception as e:
            self.log(f"⚠️  Erro ao tentar selecionar unidade: {e}")
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            return False

    # =========================================================
    # DÍGITOS DE SEGURANÇA
    # =========================================================
    def _tentar_digitos_seguranca(self, cpf_primeiros, cpf_ultimos,
                                 rg_primeiros, rg_ultimos):
        try:
            self.driver.switch_to.default_content()
            iframe_site = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.ID, "site"))
            )
            self.driver.switch_to.frame(iframe_site)

            try:
                campo_digito = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((By.ID, "digito_doc"))
                )
            except Exception:
                self.driver.switch_to.default_content()
                return False

            labels = self.driver.find_elements(By.TAG_NAME, "label")
            texto_pedido = None
            for lb in labels:
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
            self.driver.find_element(By.ID, "btn_entrar").click()

            self.driver.switch_to.default_content()
            time.sleep(0.5)

            time.sleep(1)
            self.driver.switch_to.default_content()
            iframe_site = self.driver.find_elements(By.ID, "site")
            if iframe_site:
                self.driver.switch_to.frame(iframe_site[0])
                if self.driver.find_elements(By.ID, "digito_doc"):
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
        WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//table[contains(., 'Especialidade Médica e Grupo de Cota')]",
                )
            )
        )
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