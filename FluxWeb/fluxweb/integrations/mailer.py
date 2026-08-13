"""Outbound email.

The application previously had no email capability at all, which is why there
was no verification and no password reset (audit C-8, H-13).

Two backends:

* :class:`SMTPMailer`  - used whenever ``SMTP_HOST`` is configured.
* :class:`ConsoleMailer` - development fallback that logs the message instead
  of sending it, so local signup flows still complete.

Swapping in a provider API (Resend/SendGrid) means adding one subclass and a
branch in :func:`get_mailer`; nothing else changes.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


class Mailer:
    """Mailer interface."""

    def send(self, *, to: str, subject: str, body: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleMailer(Mailer):
    """Log emails rather than sending them. Development only."""

    def __init__(self, sender: str) -> None:
        self.sender = sender

    def send(self, *, to: str, subject: str, body: str) -> None:
        log.warning(
            "[ConsoleMailer] email not sent (SMTP not configured)\n"
            "  From:    %s\n  To:      %s\n  Subject: %s\n%s",
            self.sender,
            to,
            subject,
            body,
        )


class SMTPMailer(Mailer):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        sender: str,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.sender = sender

    def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            # Never fail a signup because mail delivery hiccuped; the user can
            # request another verification link.
            log.error("Failed to send email to %s: %s", to, exc)


def get_mailer() -> Mailer:
    from flask import current_app

    config = current_app.extensions["flux_config"]
    if config.smtp_host:
        return SMTPMailer(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_user,
            password=config.smtp_password,
            use_tls=config.smtp_use_tls,
            sender=config.mail_from,
        )
    return ConsoleMailer(config.mail_from)
