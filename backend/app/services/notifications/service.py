"""Turning what happened into messages people receive (blueprint §5.4).

The IncidentService hands its domain events to the post-commit dispatcher; this subscribes to
that dispatcher. So by the time anything is sent, the change is committed: a notification can
never roll one back, and a dead mail server costs a log line, not the incident.

Each notification is stored before it is sent, which is what the in-app bell reads and what
makes the retry visible: the row counts its attempts and ends up ``sent`` or ``failed``.
"""

import logging
from collections.abc import Iterable, Sequence

from app.core.clock import Clock
from app.domain.catalogue import fallback_lead
from app.domain.errors import (
    IncidentNotFoundError,
    InvalidUserInputError,
    ITSMError,
    NetworkFailureError,
    UnauthorizedOperationError,
)
from app.domain.events import (
    CategoryChanged,
    DomainEvent,
    IncidentCreated,
    IncidentStateChanged,
    PriorityChanged,
    WorkNoteAdded,
)
from app.domain.incident import CancelReason, Incident, NoteKind
from app.domain.notifications import (
    Audience,
    ChannelName,
    Notification,
    NotificationEvent,
    NotificationSummary,
    route_for,
)
from app.domain.permissions import Permission
from app.domain.ports import OutgoingMessage
from app.domain.repositories import UnitOfWork
from app.domain.states import IncidentStatus
from app.domain.users import Technician, User
from app.services.notifications.channels import ChannelFactory, default_factory
from app.services.notifications.messages import (
    Message,
    compose,
    compose_for_follower,
    compose_linked,
)

logger = logging.getLogger(__name__)

#: Which status change is worth telling someone about (blueprint §5.4).
_EVENT_FOR_STATUS = {
    IncidentStatus.ASSIGNED: NotificationEvent.ASSIGNED,
    IncidentStatus.ON_HOLD: NotificationEvent.INFO_REQUESTED,
    IncidentStatus.RESOLVED: NotificationEvent.RESOLVED,
    IncidentStatus.CLOSED: NotificationEvent.CLOSED,
}


class NotificationService:
    """Resolves the audience, writes the rows and sends them (with up to three attempts)."""

    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        channels: ChannelFactory | None = None,
    ) -> None:
        self.__uow = uow
        self.__clock = clock
        self.__channels = channels or default_factory()

    # ------------------------------------------------------------ the dispatcher's entry point
    def on_event(self, event: DomainEvent) -> None:
        """Deliver whatever ``event`` calls for. Never raises: §5.4 forbids blocking."""
        try:
            self.__handle(event)
        except Exception:
            logger.exception(
                "could not notify for %s on %s", type(event).__name__, event.incident_id
            )

    # ------------------------------------------------------------ sending
    def notify(
        self, event: NotificationEvent, incident: Incident, detail: str = ""
    ) -> tuple[Notification, ...]:
        """Send ``event`` about ``incident`` to everyone the §5.4 table names."""
        route = route_for(event)
        recipients = self.__recipients(route.audiences_for(incident.priority), incident)
        channels = route.channels_for(incident.priority)
        message = compose(event, incident, detail)

        sent: list[Notification] = []
        for user_id in recipients:
            for channel_name in channels:
                notification = self.__store(event, channel_name, user_id, incident, message)
                self.__deliver(notification, incident)
                sent.append(notification)
        self.__uow.commit()
        return tuple(sent)

    def __store(
        self,
        event: NotificationEvent,
        channel: ChannelName,
        user_id: int,
        incident: Incident,
        message: Message,
    ) -> Notification:
        return self.__uow.notifications.add(
            Notification(
                user_id=user_id,
                event=event,
                channel=channel,
                subject=message.subject,
                body=message.body,
                created_at=self.__clock.now(),
                incident_id=incident.id,
            )
        )

    def __deliver(self, notification: Notification, incident: Incident) -> None:
        """Try the channel up to three times; a channel the deployment lacks is skipped."""
        channel = self.__channels.get(notification.channel)
        if channel is None:
            notification.mark_unroutable()
            logger.info(
                "channel %s is not configured; %s stays undelivered",
                notification.channel.value,
                incident.id,
            )
            self.__uow.notifications.save(notification)
            return

        outgoing = OutgoingMessage(
            recipient_id=notification.user_id,
            subject=notification.subject,
            body=notification.body,
            incident_id=incident.id,
        )
        while notification.can_retry:
            try:
                channel.send(outgoing)
            except (ITSMError, OSError) as error:
                notification.record_failure()
                logger.warning(
                    "attempt %s to send %s by %s failed: %s",
                    notification.attempts,
                    incident.id,
                    notification.channel.value,
                    error,
                )
            else:
                notification.mark_sent(self.__clock.now())
        self.__uow.notifications.save(notification)

    # ------------------------------------------------------------ the bell
    def summary(self, user: User, limit: int = 20) -> NotificationSummary:
        latest = self.__uow.notifications.in_app_for(user.id, limit=limit)
        titles: dict[str, str] = {}
        for incident_id in {n.incident_id for n in latest if n.incident_id is not None}:
            try:
                titles[incident_id] = self.__uow.incidents.get(incident_id).title
            except IncidentNotFoundError:
                continue
        return NotificationSummary(
            unread=self.__uow.notifications.count_unread(user.id),
            latest=latest,
            titles=titles,
        )

    def mark_read(self, user: User, notification_id: int) -> Notification:
        notification = self.__uow.notifications.get(notification_id)
        if notification.user_id != user.id:
            raise UnauthorizedOperationError("That notification is not yours.")
        notification.mark_read(self.__clock.now())
        self.__uow.notifications.save(notification)
        self.__uow.commit()
        return notification

    def send_test(self, user: User, channel_name: ChannelName) -> None:
        """Send ``user`` a test message now, so they can see a linked channel works (P4.9).

        Unlike an alert this does raise: the person pressing "send a test" wants to know.
        """
        channel = self.__channels.get(channel_name)
        if channel is None:
            raise NetworkFailureError(f"{channel_name.value} is not set up on this deployment.")
        if channel_name is ChannelName.TELEGRAM and user.telegram_chat_id is None:
            raise InvalidUserInputError({"chat_id": "Link a Telegram chat first."})
        channel.send(
            OutgoingMessage(
                recipient_id=user.id,
                subject="I-ITSM test message",
                body="Your alerts for critical and high-priority incidents will arrive here.",
            )
        )

    # ------------------------------------------------------------ internals
    def __handle(self, event: DomainEvent) -> None:
        incident = self.__uow.incidents.get(event.incident_id)
        if isinstance(event, IncidentCreated):
            self.notify(NotificationEvent.CREATED, incident)
        elif isinstance(event, IncidentStateChanged):
            self.__state_changed(event, incident)
        elif isinstance(event, PriorityChanged) and event.actor_id is not None:
            # An override is news; the engine's first assessment is not.
            self.notify(NotificationEvent.PRIORITY_CHANGED, incident, event.reason)
        elif isinstance(event, WorkNoteAdded) and event.kind == NoteKind.INFO_RESPONSE.value:
            self.notify(NotificationEvent.INFO_PROVIDED, incident, self.__last_note(incident))
        elif isinstance(event, CategoryChanged):
            return  # a correction the reporter does not need to hear about

    def __state_changed(self, event: IncidentStateChanged, incident: Incident) -> None:
        if event.to_status is IncidentStatus.ASSIGNED and "Escalated" in event.description:
            self.notify(NotificationEvent.ESCALATED, incident, event.description)
            return
        if event.to_status is IncidentStatus.CANCELLED:
            self.__linked_as_duplicate(event, incident)
            return
        notification_event = _EVENT_FOR_STATUS.get(event.to_status)
        if notification_event is None:
            return
        detail = self.__detail_for(notification_event, incident)
        self.notify(notification_event, incident, detail)
        if notification_event is NotificationEvent.RESOLVED:
            self.__tell_followers(incident, detail)

    def __linked_as_duplicate(self, event: IncidentStateChanged, incident: Incident) -> None:
        """Tell a reporter whose incident someone else linked to another one (§6.2)."""
        if (
            incident.cancel_reason is not CancelReason.DUPLICATE
            or incident.parent_id is None
            or event.actor_id == incident.reporter_id  # they chose to follow it themselves
        ):
            return
        parent = self.__uow.incidents.get(incident.parent_id)
        self.__send(
            NotificationEvent.CLOSED,
            (incident.reporter_id,),
            incident,
            compose_linked(incident, parent),
        )

    def __tell_followers(self, parent: Incident, detail: str) -> None:
        """D-005: the reporters of confirmed duplicates hear when the parent is fixed.

        The notification is filed under their own incident, which is the one they may open.
        """
        told = {parent.reporter_id}
        for duplicate in self.__uow.incidents.duplicates_of(parent.id):
            if duplicate.cancel_reason is not CancelReason.DUPLICATE:
                continue
            if duplicate.reporter_id in told:
                continue
            told.add(duplicate.reporter_id)
            self.__send(
                NotificationEvent.RESOLVED,
                (duplicate.reporter_id,),
                duplicate,
                compose_for_follower(duplicate, parent, detail),
            )

    def __send(
        self,
        event: NotificationEvent,
        recipients: Iterable[int],
        incident: Incident,
        message: Message,
    ) -> None:
        """Store and deliver one composed message on the channels the event's row names."""
        for user_id in recipients:
            for channel_name in route_for(event).channels_for(incident.priority):
                notification = self.__store(event, channel_name, user_id, incident, message)
                self.__deliver(notification, incident)
        self.__uow.commit()

    def __detail_for(self, event: NotificationEvent, incident: Incident) -> str:
        if event is NotificationEvent.INFO_REQUESTED:
            return self.__last_note(incident, NoteKind.INFO_REQUEST)
        if event is NotificationEvent.RESOLVED and incident.resolution is not None:
            return incident.resolution.summary
        return ""

    @staticmethod
    def __last_note(incident: Incident, kind: NoteKind | None = None) -> str:
        for note in reversed(incident.notes):
            if kind is None or note.kind is kind:
                return note.text
        return ""

    def __recipients(self, audiences: Iterable[Audience], incident: Incident) -> tuple[int, ...]:
        """Turn "reporter, Team Lead" into user ids, without repeating anyone."""
        found: list[int] = []
        for audience in audiences:
            for user_id in self.__for_audience(audience, incident):
                if user_id not in found:
                    found.append(user_id)
        return tuple(found)

    def __for_audience(self, audience: Audience, incident: Incident) -> Sequence[int]:
        if audience is Audience.REPORTER:
            return (incident.reporter_id,)
        if audience is Audience.ASSIGNEE:
            return () if incident.assignee_id is None else (incident.assignee_id,)
        if audience is Audience.TEAM_LEAD:
            lead = self.__team_lead(incident)
            return () if lead is None else (lead,)
        return self.__admins()

    def __team_lead(self, incident: Incident) -> int | None:
        """D-004: the lead of the assignee's team, else the Service Desk's lead."""
        if incident.assignee_id is not None:
            assignee = self.__uow.users.get(incident.assignee_id)
            if isinstance(assignee, Technician) and assignee.team_id is not None:
                lead = self.__uow.catalogue.get_team(assignee.team_id).lead_id
                if lead is not None:
                    return lead
        return fallback_lead(self.__uow.catalogue.teams())

    def __admins(self) -> tuple[int, ...]:
        return tuple(
            user.id
            for user in self.__uow.users.administrators()
            if user.can(Permission.SLA_VIOLATIONS_VIEW)
        )
