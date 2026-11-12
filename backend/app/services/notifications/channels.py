"""The delivery channels and the factory that builds them (blueprint §5.4).

Pattern: Factory + Strategy. Problem solved: §7 asks that "a new channel needs one class". Each
channel implements the same ``NotificationChannel`` port, the factory decides which ones exist
for this deployment, and the notification service asks for a channel by name without knowing
whether it writes a row, opens an SMTP connection or calls a Bot API.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime

from app.core.clock import in_ist
from app.domain.notifications import ChannelName
from app.domain.ports import ChatSender, EmailSender, NotificationChannel, OutgoingMessage

logger = logging.getLogger(__name__)
#: How the campus reads a timestamp (blueprint §9: stored UTC, shown IST).
DISPLAY_FORMAT = "%d %b %Y, %H:%M IST"


class InAppChannel(NotificationChannel):
    """The bell in the UI. The row is already written, so there is nothing more to deliver.

    The notification service stores every notification before delivery, which is what the
    in-app channel *is*; this class exists so in-app is a channel like the others and the
    routing table needs no special case.
    """

    name = ChannelName.IN_APP.value

    def send(self, message: OutgoingMessage) -> None:
        return


class EmailChannel(NotificationChannel):
    """Email through whatever sender the deployment configured (SMTP, or the console)."""

    name = ChannelName.EMAIL.value

    def __init__(self, sender: EmailSender, address_of: Callable[[int], str | None]) -> None:
        self.__sender = sender
        self.__address_of = address_of

    @property
    def transport(self) -> str:
        """Which sender is behind the channel ("smtp" or "console"), for /health and the demo."""
        return self.__sender.name

    def send(self, message: OutgoingMessage) -> None:
        address = self.__address_of(message.recipient_id)
        if address is None:
            logger.warning("no email address for user %s; skipping", message.recipient_id)
            return
        self.__sender.send(address, message.subject, message.body)


class TelegramChannel(NotificationChannel):
    """P1/P2 alerts on Telegram (§5.4) for users who linked a chat; others are skipped."""

    name = ChannelName.TELEGRAM.value

    def __init__(self, sender: ChatSender, chat_of: Callable[[int], str | None]) -> None:
        self.__sender = sender
        self.__chat_of = chat_of

    def send(self, message: OutgoingMessage) -> None:
        chat_id = self.__chat_of(message.recipient_id)
        if chat_id is None:
            logger.info("user %s has not linked Telegram; skipping", message.recipient_id)
            return
        self.__sender.send(chat_id, f"{message.subject}\n\n{message.body}")


class ChannelFactory:
    """Builds the channels this deployment has, by name."""

    def __init__(self, channels: Mapping[ChannelName, NotificationChannel]) -> None:
        self.__channels = dict(channels)

    @property
    def available(self) -> tuple[ChannelName, ...]:
        return tuple(sorted(self.__channels, key=lambda name: name.value))

    def get(self, name: ChannelName) -> NotificationChannel | None:
        """The channel, or None when this deployment has no way to use it."""
        return self.__channels.get(name)


def default_factory(
    email: NotificationChannel | None = None, telegram: NotificationChannel | None = None
) -> ChannelFactory:
    """In-app always; email and Telegram only when the deployment can send them."""
    channels: dict[ChannelName, NotificationChannel] = {ChannelName.IN_APP: InAppChannel()}
    if email is not None:
        channels[ChannelName.EMAIL] = email
    if telegram is not None:
        channels[ChannelName.TELEGRAM] = telegram
    return ChannelFactory(channels)


def shown_at(moment: datetime) -> str:
    """Format a stored UTC timestamp the way a reader on campus expects."""
    return in_ist(moment).strftime(DISPLAY_FORMAT)
