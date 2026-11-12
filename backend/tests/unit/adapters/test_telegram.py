"""The Telegram Bot API adapter (P4.9), against a fake POST: no network, no real token."""

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import SecretStr

from app.adapters.telegram import API, MAX_TEXT, TelegramBotSender
from app.core.config import Settings
from app.domain.errors import InvalidUserInputError, NetworkFailureError
from app.domain.permissions import Role
from app.domain.users import UserFactory
from app.main import chat_sender

TOKEN = "123456:placeholder-token"


class FakePost:
    def __init__(self, status: int = 200, body: Mapping[str, Any] | None = None) -> None:
        self.status = status
        self.body = {"ok": True} if body is None else body
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def __call__(self, url: str, payload: Mapping[str, Any]) -> tuple[int, Mapping[str, Any]]:
        self.calls.append((url, payload))
        return self.status, self.body


def test_a_message_is_sent_to_the_chat_through_send_message() -> None:
    post = FakePost()
    TelegramBotSender(TOKEN, post).send("555", "INC-2026-0042 has been escalated to you")
    url, payload = post.calls[0]
    assert url == f"{API}/bot{TOKEN}/sendMessage"
    assert payload == {
        "chat_id": "555",
        "text": "INC-2026-0042 has been escalated to you",
        "disable_web_page_preview": True,
    }


def test_a_long_message_is_cut_to_telegrams_limit() -> None:
    post = FakePost()
    TelegramBotSender(TOKEN, post).send("555", "x" * (MAX_TEXT + 50))
    assert len(post.calls[0][1]["text"]) == MAX_TEXT


def test_a_refusal_is_a_network_failure_with_telegrams_own_words() -> None:
    post = FakePost(400, {"ok": False, "description": "Bad Request: chat not found"})
    with pytest.raises(NetworkFailureError) as refused:
        TelegramBotSender(TOKEN, post).send("555", "hello")
    assert "chat not found" in refused.value.message


def test_an_outage_never_carries_the_token_into_the_error() -> None:
    def leaky(url: str, payload: Mapping[str, Any]) -> tuple[int, Mapping[str, Any]]:
        raise ConnectionError(f"could not connect to {url}")  # as httpx's errors do

    with pytest.raises(NetworkFailureError) as failed:
        TelegramBotSender(TOKEN, leaky).send("555", "hello")
    assert TOKEN not in str(failed.value)
    assert failed.value.__cause__ is None
    assert failed.value.__suppress_context__  # the URL-bearing error is not shown in a trace


def test_the_bot_is_wired_only_with_a_token(settings: Settings) -> None:
    assert chat_sender(settings) is None
    with_token = settings.model_copy(update={"telegram_bot_token": SecretStr(TOKEN)})
    assert isinstance(chat_sender(with_token), TelegramBotSender)


@pytest.mark.parametrize("chat_id", ["123456789", "-1001234567890", " 42 "])
def test_a_chat_id_is_a_number_and_can_be_unlinked(chat_id: str) -> None:
    user = UserFactory.create(Role.EMPLOYEE, user_id=1, email="a@campus.edu", full_name="A")
    user.link_telegram(chat_id)
    assert user.telegram_chat_id == chat_id.strip()
    user.unlink_telegram()
    assert user.telegram_chat_id is None


@pytest.mark.parametrize("chat_id", ["@someone", "12 34", "", "1" * 25])
def test_anything_else_is_refused(chat_id: str) -> None:
    user = UserFactory.create(Role.EMPLOYEE, user_id=1, email="a@campus.edu", full_name="A")
    with pytest.raises(InvalidUserInputError):
        user.link_telegram(chat_id)
