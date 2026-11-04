"""Sending email over SMTP, with a console fallback (blueprint §5.4, §12).

When SMTP_HOST is empty — a fresh clone, a marker's laptop, CI — the fallback prints the message
instead of failing, so every other feature still works. That is the §7 target "the system
degrades gracefully when external services fail", made true by default rather than by luck.
"""

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.domain.errors import NetworkFailureError
from app.domain.ports import EmailSender

logger = logging.getLogger(__name__)
SMTP_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class EmailSettings:
    """Just the SMTP fields, passed in so the adapter never reads configuration itself."""

    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = "I-ITSM <no-reply@localhost>"
    starttls: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.host)


class ConsoleEmailSender(EmailSender):
    """The fallback: log the message so a developer can read it and nothing breaks."""

    name = "console"

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("email (console fallback) to=%s subject=%s\n%s", to, subject, body)


class SmtpEmailSender(EmailSender):
    """Real delivery through an SMTP server (a Gmail app password works)."""

    name = "smtp"

    def __init__(self, settings: EmailSettings) -> None:
        if not settings.configured:
            msg = "SMTP_HOST is empty; use ConsoleEmailSender instead."
            raise ValueError(msg)
        self.__settings = settings

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.__settings.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(
                self.__settings.host, self.__settings.port, timeout=SMTP_TIMEOUT_SECONDS
            ) as server:
                if self.__settings.starttls:
                    server.starttls()
                if self.__settings.username:
                    server.login(self.__settings.username, self.__settings.password)
                server.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise NetworkFailureError(f"Could not send email to {to}.") from error


def email_sender_for(settings: EmailSettings) -> EmailSender:
    """The real sender when SMTP is configured, the console fallback when it is not."""
    if settings.configured:
        return SmtpEmailSender(settings)
    logger.info("SMTP_HOST is not set; email falls back to the console")
    return ConsoleEmailSender()
