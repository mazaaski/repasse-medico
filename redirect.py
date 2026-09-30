from http.server import BaseHTTPRequestHandler, HTTPServer

class RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(301)
        # Força o HTTPS e a porta correta
        self.send_header('Location', 'https://repasse-medico.alsf.org.br:8002' + self.path)
        self.end_headers()

if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 8002), RedirectHandler).serve_forever()