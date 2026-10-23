"""Alertas analíticos. Telegram opt-in, sem envio de imagens nem credenciais em logs."""
import logging
import os
import queue
import threading

import requests

LOG = logging.getLogger(__name__)


class NotificationEngine:
    def __init__(self):
        self.messages = queue.Queue(maxsize=20)
        self.enabled = False
        self.thread = threading.Thread(target=self._run, daemon=True, name="telegram-alerts")
        self.thread.start()

    def notify(self, message: str):
        LOG.info("alert %s", message)
        if self.enabled:
            try:
                self.messages.put_nowait(message)
            except queue.Full:
                LOG.warning("Fila de notificações cheia; alerta externo descartado")

    def _run(self):
        with requests.Session() as session:
            while True:
                message = self.messages.get()
                if message is None:
                    return
                token = os.environ.get("TELEGRAM_BOT_TOKEN")
                chat = os.environ.get("TELEGRAM_CHAT_ID")
                if not token or not chat:
                    LOG.warning("Telegram habilitado sem credenciais; configure variáveis de ambiente")
                    continue
                try:
                    response = session.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                            json={"chat_id": chat, "text": message},
                                            timeout=(3, 5), allow_redirects=False)
                    if response.status_code != 200 or response.json().get("ok") is not True:
                        LOG.warning("Telegram não confirmou alerta")
                except (requests.RequestException, ValueError, AttributeError):
                    LOG.warning("Falha de envio Telegram (detalhes sensíveis omitidos)")

    def close(self):
        self.enabled = False
        # Descarta pendências no fechamento; não bloquear a interface por rede.
        while True:
            try:
                self.messages.get_nowait()
            except queue.Empty:
                break
        self.messages.put_nowait(None)
