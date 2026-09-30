"""
Diagnóstico completo do projeto SIRESP Web.
Roda esse arquivo e cola o output aqui.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

print("=" * 70)
print("DIAGNÓSTICO DO PROJETO SIRESP")
print("=" * 70)
print(f"Diretório base: {BASE}")
print()

# =========================================================
# 1) ÁRVORE DE ARQUIVOS
# =========================================================
print("=" * 70)
print("1) ÁRVORE DE ARQUIVOS")
print("=" * 70)

IGNORAR = {'__pycache__', '.git', 'node_modules', '.venv', 'venv', 'media', 'staticfiles'}

def arvore(path, prefixo=""):
    try:
        itens = sorted(os.listdir(path))
    except PermissionError:
        return
    itens = [i for i in itens if i not in IGNORAR]
    for i, nome in enumerate(itens):
        caminho = os.path.join(path, nome)
        ultimo = (i == len(itens) - 1)
        conector = "└── " if ultimo else "├── "
        if os.path.isdir(caminho):
            print(prefixo + conector + nome + "/")
            novo_prefixo = prefixo + ("    " if ultimo else "│   ")
            arvore(caminho, novo_prefixo)
        else:
            tamanho = os.path.getsize(caminho)
            print(prefixo + conector + f"{nome}  ({tamanho} bytes)")

arvore(BASE)
print()

# =========================================================
# 2) ARQUIVOS CRÍTICOS
# =========================================================
print("=" * 70)
print("2) ARQUIVOS CRÍTICOS — existem?")
print("=" * 70)

criticos = [
    "manage.py",
    "servico.py",
    "siresp_scraper.py",
    "siresp_project/__init__.py",
    "siresp_project/settings.py",
    "siresp_project/urls.py",
    "siresp_project/wsgi.py",
    "siresp_app/__init__.py",
    "siresp_app/apps.py",
    "siresp_app/admin.py",
    "siresp_app/models.py",
    "siresp_app/urls.py",
    "siresp_app/views/__init__.py",
    "siresp_app/views/auth.py",
    "siresp_app/views/config.py",
    "siresp_app/services/__init__.py",
    "siresp_app/services/valores_service.py",
    "siresp_app/templates/siresp_app/base.html",
    "siresp_app/templates/siresp_app/login.html",
    "siresp_app/templates/siresp_app/config/lista.html",
    "siresp_app/templates/siresp_app/config/form.html",
    "siresp_app/templates/siresp_app/config/especialidades.html",
    "siresp_app/static/siresp_app/css/estilo.css",
]

for c in criticos:
    caminho = os.path.join(BASE, c.replace("/", os.sep))
    existe = "✅" if os.path.exists(caminho) else "❌"
    print(f"  {existe}  {c}")

print()

# =========================================================
# 3) ARQUIVOS DUPLICADOS (não deveriam existir)
# =========================================================
print("=" * 70)
print("3) ARQUIVOS DUPLICADOS (não deveriam existir)")
print("=" * 70)

suspeitos = [
    "siresp_app/auth.py",
    "siresp_app/config.py",
]

encontrou_suspeito = False
for s in suspeitos:
    caminho = os.path.join(BASE, s.replace("/", os.sep))
    if os.path.exists(caminho):
        encontrou_suspeito = True
        print(f"  ⚠️  EXISTE (remover!): {s}")

if not encontrou_suspeito:
    print("  ✅ Nenhum arquivo duplicado encontrado.")

print()

# =========================================================
# 4) CONTEÚDO DOS ARQUIVOS CRÍTICOS
# =========================================================
print("=" * 70)
print("4) CONTEÚDO DOS ARQUIVOS CRÍTICOS")
print("=" * 70)

para_mostrar = [
    "siresp_project/urls.py",
    "siresp_app/urls.py",
    "siresp_app/views/auth.py",
    "siresp_app/views/__init__.py",
    "siresp_app/__init__.py",
]

for arquivo in para_mostrar:
    caminho = os.path.join(BASE, arquivo.replace("/", os.sep))
    print()
    print(f"----- {arquivo} -----")
    if not os.path.exists(caminho):
        print("  ❌ NÃO EXISTE")
        continue
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read()
        if conteudo.strip() == "":
            print("  (arquivo vazio)")
        else:
            print(conteudo)
    except Exception as e:
        print(f"  ⚠️ Erro ao ler: {e}")

print()

# =========================================================
# 5) TENTA IMPORTAR O DJANGO E AS VIEWS
# =========================================================
print("=" * 70)
print("5) TESTE DE IMPORTAÇÃO DJANGO")
print("=" * 70)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siresp_project.settings')

try:
    import django
    django.setup()
    print(f"  ✅ Django OK — versão {django.get_version()}")

    from django.conf import settings
    print(f"  ✅ settings OK")
    print(f"     DEBUG = {settings.DEBUG}")
    print(f"     ALLOWED_HOSTS = {settings.ALLOWED_HOSTS}")
    print(f"     LOGIN_URL = {settings.LOGIN_URL}")

    from django.urls import reverse, NoReverseMatch
    try:
        url_login = reverse('siresp_app:login')
        print(f"  ✅ reverse('siresp_app:login') = {url_login}")
    except NoReverseMatch as e:
        print(f"  ❌ reverse falhou: {e}")

    from siresp_app.views import auth
    print(f"  ✅ auth importado: {auth.__file__}")
    print(f"     login_view existe: {hasattr(auth, 'login_view')}")
    print(f"     home_view existe: {hasattr(auth, 'home_view')}")
    print(f"     logout_view existe: {hasattr(auth, 'logout_view')}")

    from siresp_app.views import config
    print(f"  ✅ config importado: {config.__file__}")
    print(f"     lista_grupos existe: {hasattr(config, 'lista_grupos')}")

    from siresp_app.models import GrupoValor
    print(f"  ✅ models.GrupoValor OK")
    print(f"     Total de grupos no banco: {GrupoValor.objects.count()}")

except Exception as e:
    print(f"  ❌ ERRO: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 70)
print("FIM DO DIAGNÓSTICO")
print("=" * 70)