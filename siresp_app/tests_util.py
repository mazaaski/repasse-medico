"""Utilidades de teste."""
import threading
import time


class AguardaThreads:
    """
    Misture em TransactionTestCase que dispara threads de fundo (login, lote).

    No SQLite em memória, uma thread ainda gravando quando o teste seguinte limpa o
    banco causa erros intermitentes. Ao fim de cada teste esperamos as threads
    criadas durante ele terminarem.
    """

    def setUp(self):
        super().setUp()
        self._threads_antes = set(threading.enumerate())
        self.addCleanup(self._aguardar_threads)

    def _aguardar_threads(self, limite=5):
        """Espera terminarem as threads iniciadas durante o teste (login/lote em segundo plano)."""
        fim = time.time() + limite
        while time.time() < fim:
            ativas = [t for t in threading.enumerate()
                      if t not in self._threads_antes and t.is_alive()]
            if not ativas:
                return
            time.sleep(0.05)
