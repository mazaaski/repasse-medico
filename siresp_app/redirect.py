from http.server import BaseHTTPRequestHandler, HTTPServer

class RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(301)
        # Redireciona o tráfego HTTP para a porta HTTPS do Django
        self.send_header('Location', 'https://repasse-medico.alsf.org.br:8002' + self.path)
        self.end_headers()

if __name__ == '__main__':
    # ATENÇÃO: Aqui deve ser 80
    HTTPServer(('0.0.0.0', ), RedirectHandler).serve_forever()