"""Notifications (blueprint §5.4): the channels, the words and the service that sends them."""

from app.services.notifications.channels import (
    ChannelFactory,
    EmailChannel,
    InAppChannel,
    TelegramChannel,
    default_factory,
)
from app.services.notifications.messages import Message, compose
from app.services.notifications.service import NotificationService

__all__ = [
    "ChannelFactory",
    "EmailChannel",
    "InAppChannel",
    "Message",
    "NotificationService",
    "TelegramChannel",
    "compose",
    "default_factory",
]
