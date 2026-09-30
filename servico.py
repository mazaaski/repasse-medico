#!/usr/bin/env python
"""Script de inicialização do sistema SIRESP como serviço Windows (NSSM)"""
import os
import sys
import django
import logging
from datetime import datetime

# Configurar logging para arquivo
log_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(log_dir, 'servico.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)


def setup_environment():
    """Configura o ambiente para o serviço"""
    base_path = os.path.dirname(os.path.abspath(__file__))

    if base_path not in sys.path:
        sys.path.insert(0, base_path)

    project_path = os.path.join(base_path, 'siresp_project')
    if os.path.exists(project_path) and project_path not in sys.path:
        sys.path.insert(0, project_path)

    app_path = os.path.join(base_path, 'siresp_app')
    if os.path.exists(app_path) and app_path not in sys.path:
        sys.path.insert(0, app_path)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siresp_project.settings')
    django.setup()

    logging.info(f"Ambiente configurado - Diretório: {base_path}")
    return base_path


def run_server():
    """Inicia o servidor Django"""
    from django.core.management import execute_from_command_line

    PORTA_FIXA = 8002

    # Caminhos dos certificados SSL
    CERT_FILE = r'C:\ProjetoSiresp\cert.pem'
    KEY_FILE = r'C:\ProjetoSiresp\key.pem'

    tem_cert = os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)

    logging.info("=" * 60)
    logging.info("🏥 REPASSE MÉDICO - PRODUÇÃO X PROFISSIONAL - SERVIÇO")
    logging.info("=" * 60)

    if tem_cert:
        logging.info(f"📡 Servidor HTTPS iniciando na porta {PORTA_FIXA}")
        logging.info(f"📍 Acesso LOCAL: https://127.0.0.1:{PORTA_FIXA}")
        logging.info(f"🌐 Acesso NA REDE: https://172.16.0.20:{PORTA_FIXA}")
        logging.info(f"🌍 Acesso EXTERNO: https://repasse-medico.alsf.org.br:{PORTA_FIXA}")
        logging.info(f"🔐 Certificado: {CERT_FILE}")

        sys.argv = [
            'manage.py',
            'runserver_plus',
            f'0.0.0.0:{PORTA_FIXA}',
            '--cert-file', CERT_FILE,
            '--key-file', KEY_FILE,
            '--noreload',
            '--keep-meta-shutdown',
        ]
    else:
        logging.info(f"📡 Servidor HTTP iniciando na porta {PORTA_FIXA}")
        logging.info(f"📍 Acesso LOCAL: http://127.0.0.1:{PORTA_FIXA}")
        logging.info(f"🌐 Acesso NA REDE: http://172.16.0.20:{PORTA_FIXA}")
        logging.warning("⚠️  Certificados .pem não encontrados — rodando em HTTP")
        logging.warning(f"    Esperado: {CERT_FILE}")
        logging.warning(f"    Esperado: {KEY_FILE}")

        sys.argv = [
            'manage.py',
            'runserver',
            f'0.0.0.0:{PORTA_FIXA}',
            '--noreload',
        ]

    logging.info("=" * 60)
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    try:
        setup_environment()
        run_server()
    except Exception as e:
        logging.error(f"Erro ao iniciar serviço: {str(e)}")
        import traceback
        with open(os.path.join(log_dir, 'erro_servico.log'), 'w') as f:
            traceback.print_exc(file=f)
        raise