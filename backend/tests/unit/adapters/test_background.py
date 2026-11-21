"""D-043: email and Telegram are delivered off the request, in order, and failures are logged."""

import threading
import time

import pytest

from app.adapters.background import BackgroundChatSender, BackgroundEmailSender, DeliveryWorker
from app.adapters.smtp_email import ConsoleEmailSender
from app.domain.errors import NetworkFailureError
from app.domain.ports import ChatSender, EmailSender
from app.main import chat_in_background, in_background


class SlowEmail(EmailSender):
    name = "email"

    def __init__(self, release: threading.Event) -> None:
        self.release = release
        self.sent: list[str] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.release.wait(5)
        if to == "broken@campus.edu":
            raise NetworkFailureError("smtp connection refused")
        self.sent.append(to)


class RecordingChat(ChatSender):
    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


def test_send_returns_before_a_slow_delivery_finishes() -> None:
    release = threading.Event()
    inner = SlowEmail(release)
    worker = DeliveryWorker()
    sender = BackgroundEmailSender(inner, worker)

    started = time.monotonic()
    sender.send("meera@campus.edu", "INC-1 is with a technician", "body")
    assert time.monotonic() - started < 0.5
    assert inner.sent == []

    release.set()
    assert worker.drain()
    assert inner.sent == ["meera@campus.edu"]


def test_deliveries_run_in_order_and_a_failure_does_not_stop_the_rest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    release = threading.Event()
    release.set()
    inner = SlowEmail(release)
    worker = DeliveryWorker()
    sender = BackgroundEmailSender(inner, worker)

    for to in ("a@campus.edu", "broken@campus.edu", "b@campus.edu"):
        sender.send(to, "subject", "body")

    assert worker.drain()
    assert inner.sent == ["a@campus.edu", "b@campus.edu"]
    assert "background email delivery to broken@campus.edu failed" in caplog.text


def test_chat_messages_are_delivered_in_the_background_too() -> None:
    inner = RecordingChat()
    worker = DeliveryWorker()
    BackgroundChatSender(inner, worker).send("42", "INC-1 has breached its SLA")
    assert worker.drain()
    assert inner.sent == [("42", "INC-1 has breached its SLA")]


def test_the_console_fallback_stays_synchronous_and_no_telegram_stays_none() -> None:
    console = ConsoleEmailSender()
    worker = DeliveryWorker()
    assert in_background(console, worker) is console
    assert chat_in_background(None, worker) is None
    assert isinstance(chat_in_background(RecordingChat(), worker), BackgroundChatSender)


def test_draining_an_idle_worker_returns_at_once() -> None:
    assert DeliveryWorker().drain(timeout=0.1)
