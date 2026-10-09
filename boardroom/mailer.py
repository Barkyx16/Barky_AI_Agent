"""Outgoing email over SMTP (standard library only). Enabled when SMTP_HOST is set."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage


class Mailer:
    def __init__(self, host: str, port: int, username: str, password: str, sender: str):
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.sender = sender

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        context = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=20) as smtp:
                self._deliver(smtp, msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
                smtp.starttls(context=context)
                self._deliver(smtp, msg)

    def _deliver(self, smtp: smtplib.SMTP, msg: EmailMessage) -> None:
        if self.username:
            smtp.login(self.username, self.password)
        smtp.send_message(msg)
