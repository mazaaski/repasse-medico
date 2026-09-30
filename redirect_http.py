"""
Redireciona HTTP (porta 80) → HTTPS (porta 8002).
Útil pra quem digita só 'repasse-medico.alsf.org.br' no navegador.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys


class RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(301)
        self.send_header(
            'Location',
            'https://repasse-medico.alsf.org.br:8002' + self.path
        )
        self.end_headers()

    def do_HEAD(self):
        self.send_response(301)
        self.send_header(
            'Location',
            'https://repasse-medico.alsf.org.br:8002' + self.path
        )
        self.end_headers()

    def log_message(self, format, *args):
        # Silencia logs pra não poluir
        pass


if __name__ == '__main__':
    print("=" * 60)
    print("🔄 Redirect HTTP (porta 80) → HTTPS (porta 8002)")
    print("=" * 60)
    try:
        HTTPServer(('0.0.0.0', 80), RedirectHandler).serve_forever()
    except PermissionError:
        print("❌ Precisa rodar como ADMINISTRADOR pra usar a porta 80")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nEncerrado.")