#!/usr/bin/env python
"""Utilitário de linha de comando do Django."""
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siresp_project.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Não consegui importar Django. Verifique se está instalado e "
            "se o ambiente virtual está ativado."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()