"""Who is told what, on which channel (blueprint §5.4).

The routing table is data, not code: adding an event or moving a channel is one entry here,
which is what §7's "a new channel needs one class" and the admin-configurable spirit of §3 ask
for. Nothing in this module sends anything — delivery lives in ``app.services.notifications``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from app.domain.errors import InvalidUserInputError
from app.domain.priority import Priority

#: §5.4: "if P1 or P2" on the Created row and the Assigned row's Telegram channel.
HIGH_PRIORITIES: frozenset[Priority] = frozenset({Priority.P1, Priority.P2})
MAX_SEND_ATTEMPTS = 3  # §5.4: a failed send is retried up to three times


class NotificationEvent(StrEnum):
    """The nine rows of the §5.4 table."""

    CREATED = "created"
    ASSIGNED = "assigned"
    PRIORITY_CHANGED = "priority_changed"
    INFO_REQUESTED = "info_requested"
    INFO_PROVIDED = "info_provided"
    SLA_APPROACHING = "sla_approaching"
    SLA_VIOLATED = "sla_violated"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Audience(StrEnum):
    """Who to tell, relative to the incident rather than by name."""

    REPORTER = "reporter"
    ASSIGNEE = "assignee"
    TEAM_LEAD = "team_lead"
    ADMINS = "admins"


class ChannelName(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    TELEGRAM = "telegram"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Target:
    """One entry on a row of the table, optionally only for a high priority."""

    audience: Audience
    high_priority_only: bool = False


@dataclass(frozen=True, slots=True)
class Delivery:
    channel: ChannelName
    high_priority_only: bool = False


@dataclass(frozen=True, slots=True)
class Route:
    """One row of the §5.4 table: who hears about an event, and how."""

    targets: tuple[Target, ...]
    deliveries: tuple[Delivery, ...]

    def audiences_for(self, priority: Priority | None) -> tuple[Audience, ...]:
        high = priority in HIGH_PRIORITIES
        return tuple(t.audience for t in self.targets if high or not t.high_priority_only)

    def channels_for(self, priority: Priority | None) -> tuple[ChannelName, ...]:
        high = priority in HIGH_PRIORITIES
        return tuple(d.channel for d in self.deliveries if high or not d.high_priority_only)


def _route(targets: tuple[Target, ...], deliveries: tuple[Delivery, ...]) -> Route:
    return Route(targets, deliveries)


_IN_APP_EMAIL = (Delivery(ChannelName.IN_APP), Delivery(ChannelName.EMAIL))

#: Blueprint §5.4, read straight off the table.
ROUTING: Mapping[NotificationEvent, Route] = MappingProxyType(
    {
        NotificationEvent.CREATED: _route(
            (Target(Audience.REPORTER), Target(Audience.TEAM_LEAD, high_priority_only=True)),
            _IN_APP_EMAIL,
        ),
        NotificationEvent.ASSIGNED: _route(
            (Target(Audience.REPORTER), Target(Audience.ASSIGNEE)),
            (
                Delivery(ChannelName.IN_APP),
                Delivery(ChannelName.EMAIL),
                Delivery(ChannelName.TELEGRAM, high_priority_only=True),
            ),
        ),
        NotificationEvent.PRIORITY_CHANGED: _route(
            (Target(Audience.REPORTER), Target(Audience.ASSIGNEE)), _IN_APP_EMAIL
        ),
        NotificationEvent.INFO_REQUESTED: _route((Target(Audience.REPORTER),), _IN_APP_EMAIL),
        NotificationEvent.INFO_PROVIDED: _route((Target(Audience.ASSIGNEE),), _IN_APP_EMAIL),
        NotificationEvent.SLA_APPROACHING: _route(
            (Target(Audience.ASSIGNEE), Target(Audience.TEAM_LEAD)),
            (Delivery(ChannelName.IN_APP), Delivery(ChannelName.TELEGRAM)),
        ),
        NotificationEvent.SLA_VIOLATED: _route(
            (Target(Audience.ASSIGNEE), Target(Audience.TEAM_LEAD), Target(Audience.ADMINS)),
            (
                Delivery(ChannelName.IN_APP),
                Delivery(ChannelName.EMAIL),
                Delivery(ChannelName.TELEGRAM),
            ),
        ),
        NotificationEvent.ESCALATED: _route(
            (Target(Audience.ASSIGNEE),),  # escalation has already moved the incident over
            (Delivery(ChannelName.IN_APP), Delivery(ChannelName.TELEGRAM)),
        ),
        NotificationEvent.RESOLVED: _route((Target(Audience.REPORTER),), _IN_APP_EMAIL),
        NotificationEvent.CLOSED: _route(
            (Target(Audience.REPORTER), Target(Audience.ASSIGNEE)),
            (Delivery(ChannelName.IN_APP),),
        ),
    }
)


def route_for(event: NotificationEvent) -> Route:
    return ROUTING[event]


class Notification:
    """One message for one person on one channel, and how its delivery went."""

    def __init__(
        self,
        *,
        user_id: int,
        event: NotificationEvent,
        channel: ChannelName,
        subject: str,
        body: str,
        created_at: datetime,
        incident_id: str | None = None,
        notification_id: int | None = None,
        status: DeliveryStatus = DeliveryStatus.PENDING,
        attempts: int = 0,
        sent_at: datetime | None = None,
        read_at: datetime | None = None,
    ) -> None:
        if not subject.strip():
            raise InvalidUserInputError({"subject": "Must not be empty."})
        self.__id = notification_id
        self.__user_id = user_id
        self.__event = event
        self.__channel = channel
        self.__subject = subject.strip()
        self.__body = body
        self.__created_at = created_at
        self.__incident_id = incident_id
        self.__status = status
        self.__attempts = attempts
        self.__sent_at = sent_at
        self.__read_at = read_at

    @property
    def id(self) -> int | None:
        return self.__id

    @property
    def user_id(self) -> int:
        return self.__user_id

    @property
    def event(self) -> NotificationEvent:
        return self.__event

    @property
    def channel(self) -> ChannelName:
        return self.__channel

    @property
    def subject(self) -> str:
        return self.__subject

    @property
    def body(self) -> str:
        return self.__body

    @property
    def created_at(self) -> datetime:
        return self.__created_at

    @property
    def incident_id(self) -> str | None:
        return self.__incident_id

    @property
    def status(self) -> DeliveryStatus:
        return self.__status

    @property
    def attempts(self) -> int:
        return self.__attempts

    @property
    def sent_at(self) -> datetime | None:
        return self.__sent_at

    @property
    def read_at(self) -> datetime | None:
        return self.__read_at

    @property
    def is_read(self) -> bool:
        return self.__read_at is not None

    @property
    def can_retry(self) -> bool:
        """§5.4: up to three attempts, then the failure stands and is logged."""
        return self.__status is not DeliveryStatus.SENT and self.__attempts < MAX_SEND_ATTEMPTS

    def identify(self, notification_id: int) -> None:
        """Record the id the repository gave this notification."""
        self.__id = notification_id

    def mark_sent(self, at: datetime) -> None:
        self.__attempts += 1
        self.__status = DeliveryStatus.SENT
        self.__sent_at = at

    def record_failure(self) -> None:
        self.__attempts += 1
        if self.__attempts >= MAX_SEND_ATTEMPTS:
            self.__status = DeliveryStatus.FAILED

    def mark_unroutable(self) -> None:
        """No channel exists for this notification, so there is nothing to retry."""
        self.__status = DeliveryStatus.FAILED

    def mark_read(self, at: datetime) -> None:
        if self.__read_at is None:
            self.__read_at = at

    def __repr__(self) -> str:
        return f"Notification(user={self.__user_id}, {self.__event}, {self.__channel})"


@dataclass(frozen=True, slots=True)
class NotificationSummary:
    """What the bell shows (blueprint §5.4, in-app channel)."""

    unread: int
    latest: tuple[Notification, ...] = field(default_factory=tuple)
