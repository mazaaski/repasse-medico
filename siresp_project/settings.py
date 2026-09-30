"""
Configurações Django para o projeto SIRESP Web.
"""
from pathlib import Path
import os
import sys

# Console do Windows (cp1252) não imprime os emojis dos logs; sem isso o
# print() levanta UnicodeEncodeError e derruba o login no SIRESP.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent

# =========================================================
# SEGURANÇA
# =========================================================
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-fallback-apenas-para-dev-nao-usar-em-producao'
)

# DEBUG=True por padrão para facilitar testes em localhost.
# Em produção defina a variável de ambiente DJANGO_DEBUG=0.
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    '172.16.0.20',
    'repasse-medico.alsf.org.br',
]


# =========================================================
# APPS
# =========================================================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'django_extensions',

    'siresp_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'siresp_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'siresp_app.context_processors.papel',
            ],
        },
    },
]

WSGI_APPLICATION = 'siresp_project.wsgi.application'


# =========================================================
# BANCO DE DADOS
# =========================================================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# =========================================================
# INTERNACIONALIZAÇÃO
# =========================================================
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True


# =========================================================
# ARQUIVOS ESTÁTICOS E MÍDIA
# =========================================================
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# =========================================================
# AUTENTICAÇÃO
# =========================================================
LOGIN_URL = 'siresp_app:login'
LOGIN_REDIRECT_URL = 'siresp_app:home'
LOGOUT_REDIRECT_URL = 'siresp_app:login'


# Bootstrap usa "danger" (o Django usa "error")
from django.contrib.messages import constants as _msg
MESSAGE_TAGS = {_msg.ERROR: 'danger'}


# =========================================================
# SESSÃO — expira em 8h
# =========================================================
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_EXPIRE_AT_BROWSER_CLOSE = False


# =========================================================
# CSRF / HTTPS
# =========================================================
CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:8000',
    'http://localhost:8000',
    'http://127.0.0.1:8002',
    'http://localhost:8002',
    'http://172.16.0.20:8002',
    'https://repasse-medico.alsf.org.br:8002',
    'https://172.16.0.20:8002',
    'https://127.0.0.1:8002',
]

# Aceita cookies via HTTP e HTTPS (durante transição)
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False


# =========================================================
# LOGGING
# =========================================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} - {levelname} - {name} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'django.log',
            'encoding': 'utf-8',
            'formatter': 'verbose',
        },
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
}