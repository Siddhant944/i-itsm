"""The email adapter and its console fallback (blueprint §5.4, §7 graceful degradation)."""

import logging
import smtplib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.adapters.smtp_email import (
    ConsoleEmailSender,
    EmailSettings,
    SmtpEmailSender,
    email_sender_for,
)
from app.domain.errors import NetworkFailureError

CONFIGURED = EmailSettings(
    host="smtp.example.edu",
    port=587,
    username="itsm@example.edu",
    password="an-app-password",
    sender="I-ITSM <itsm@example.edu>",
)


class FakeSmtp:
    """Stands in for smtplib.SMTP and records what the adapter did with it."""

    last: "FakeSmtp | None" = None

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.logged_in_as: str | None = None
        self.messages: list[Any] = []
        FakeSmtp.last = self

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: object) -> None:
        return

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in_as = username

    def send_message(self, message: Any) -> None:
        self.messages.append(message)


def test_an_unconfigured_deployment_falls_back_to_the_console() -> None:
    """A fresh clone has no SMTP_HOST, and everything else must still work."""
    sender = email_sender_for(EmailSettings())
    assert isinstance(sender, ConsoleEmailSender)
    assert sender.name == "console"

    with captured_logs("app.adapters.smtp_email") as written:
        sender.send("devika@campus.edu", "INC-2026-0001 is resolved", "Please confirm.")
    printed = "\n".join(written)
    assert "devika@campus.edu" in printed
    assert "Please confirm." in printed


@contextmanager
def captured_logs(logger_name: str) -> Iterator[list[str]]:
    """Capture one logger's messages without depending on the global logging setup."""
    written: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            written.append(record.getMessage())

    logger = logging.getLogger(logger_name)
    handler = Collector()
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        yield written
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def test_a_configured_deployment_gets_the_real_sender() -> None:
    assert isinstance(email_sender_for(CONFIGURED), SmtpEmailSender)
    assert email_sender_for(CONFIGURED).name == "smtp"


def test_the_real_sender_refuses_to_be_built_without_a_host() -> None:
    with pytest.raises(ValueError, match="SMTP_HOST"):
        SmtpEmailSender(EmailSettings())


def test_a_message_is_sent_over_starttls_with_the_right_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    SmtpEmailSender(CONFIGURED).send(
        "devika@campus.edu", "INC-2026-0001 is resolved", "Please confirm."
    )
    server = FakeSmtp.last
    assert server is not None
    assert (server.host, server.port) == ("smtp.example.edu", 587)
    assert server.timeout > 0
    assert server.started_tls is True
    assert server.logged_in_as == "itsm@example.edu"

    [message] = server.messages
    assert message["To"] == "devika@campus.edu"
    assert message["From"] == "I-ITSM <itsm@example.edu>"
    assert message["Subject"] == "INC-2026-0001 is resolved"
    assert "Please confirm." in message.get_content()


def test_starttls_and_login_are_skipped_when_not_wanted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    plain = EmailSettings(host="localhost", port=1025, starttls=False)
    SmtpEmailSender(plain).send("devika@campus.edu", "Subject", "Body")
    server = FakeSmtp.last
    assert server is not None
    assert server.started_tls is False
    assert server.logged_in_as is None


@pytest.mark.parametrize(
    "error", [OSError("connection refused"), smtplib.SMTPException("mailbox unavailable")]
)
def test_a_transport_failure_becomes_a_network_failure_the_caller_can_retry(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def explode(*_: object, **__: object) -> FakeSmtp:
        raise error

    monkeypatch.setattr(smtplib, "SMTP", explode)
    with pytest.raises(NetworkFailureError):
        SmtpEmailSender(CONFIGURED).send("devika@campus.edu", "Subject", "Body")
