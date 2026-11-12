"""Telegram alerts through the Bot API (blueprint §5.4, P4.9, D-013).

Pattern: Adapter. Problem solved: the notification service sends "a message to user 7" and
must not know Telegram's URL scheme, its JSON or its error shapes. Every failure leaves as
``NetworkFailureError`` so the service's three attempts and the "never block" rule apply.

The bot token is part of every request URL, so nothing raised or logged here may contain the
URL or the underlying exception's text: only Telegram's own description of a refusal.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Any

from app.domain.errors import NetworkFailureError
from app.domain.ports import ChatSender

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT_SECONDS = 5.0
#: Telegram refuses longer messages; ours are a few lines, so this only guards the edge.
MAX_TEXT = 4096

#: POSTs JSON and returns the status and the decoded body. The real one uses httpx.
PostJson = Callable[[str, Mapping[str, Any]], tuple[int, Mapping[str, Any]]]


class TelegramBotSender(ChatSender):
    """``sendMessage`` through one bot."""

    name = "telegram"

    def __init__(self, token: str, post: PostJson | None = None) -> None:
        self.__url = f"{API}/bot{token}/sendMessage"
        self.__post = post or httpx_post

    def send(self, chat_id: str, text: str) -> None:
        payload = {"chat_id": chat_id, "text": text[:MAX_TEXT], "disable_web_page_preview": True}
        try:
            status, body = self.__post(self.__url, payload)
        except Exception as error:
            logger.warning("Telegram unreachable: %s", type(error).__name__)
            raise NetworkFailureError("Telegram could not be reached.") from None
        if status != 200 or body.get("ok") is not True:
            described = str(body.get("description", f"HTTP {status}"))[:200]
            raise NetworkFailureError(f"Telegram refused the message: {described}")


def httpx_post(url: str, payload: Mapping[str, Any]) -> tuple[int, Mapping[str, Any]]:
    import httpx

    response = httpx.post(url, json=dict(payload), timeout=TIMEOUT_SECONDS)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


def telegram_sender(token: str) -> TelegramBotSender:
    """The sender the composition root wires when TELEGRAM_BOT_TOKEN is set."""
    return TelegramBotSender(token)
