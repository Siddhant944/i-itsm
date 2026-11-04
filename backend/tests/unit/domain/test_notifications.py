"""The §5.4 routing table and one notification's delivery state."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.errors import InvalidUserInputError
from app.domain.notifications import (
    MAX_SEND_ATTEMPTS,
    ROUTING,
    Audience,
    ChannelName,
    DeliveryStatus,
    Notification,
    NotificationEvent,
    route_for,
)
from app.domain.priority import Priority

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def note(**overrides: object) -> Notification:
    fields: dict[str, object] = {
        "user_id": 1,
        "event": NotificationEvent.CREATED,
        "channel": ChannelName.EMAIL,
        "subject": "INC-2026-0001 was created",
        "body": "We have your report.",
        "created_at": NOW,
        "incident_id": "INC-2026-0001",
    }
    fields.update(overrides)
    return Notification(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------- the table (T-NOTIF)
def test_every_event_has_a_route() -> None:
    assert set(ROUTING) == set(NotificationEvent)
    assert all(route.targets and route.deliveries for route in ROUTING.values())


def test_a_new_incident_tells_the_reporter_and_the_lead_only_when_it_is_urgent() -> None:
    """§5.4 Created: reporter; Team Lead if P1 or P2; in-app and email."""
    route = route_for(NotificationEvent.CREATED)
    assert route.audiences_for(Priority.P3) == (Audience.REPORTER,)
    assert route.audiences_for(Priority.P4) == (Audience.REPORTER,)
    assert route.audiences_for(Priority.P2) == (Audience.REPORTER, Audience.TEAM_LEAD)
    assert route.audiences_for(Priority.P1) == (Audience.REPORTER, Audience.TEAM_LEAD)
    assert route.audiences_for(None) == (Audience.REPORTER,)
    assert route.channels_for(Priority.P1) == (ChannelName.IN_APP, ChannelName.EMAIL)


def test_assignment_adds_telegram_only_for_p1_and_p2() -> None:
    """§5.4 Assigned: reporter and assignee; in-app, email; Telegram if P1 or P2."""
    route = route_for(NotificationEvent.ASSIGNED)
    assert route.audiences_for(Priority.P4) == (Audience.REPORTER, Audience.ASSIGNEE)
    assert route.channels_for(Priority.P3) == (ChannelName.IN_APP, ChannelName.EMAIL)
    assert route.channels_for(Priority.P2) == (
        ChannelName.IN_APP,
        ChannelName.EMAIL,
        ChannelName.TELEGRAM,
    )


@pytest.mark.parametrize(
    ("event", "audiences", "channels"),
    [
        (
            NotificationEvent.PRIORITY_CHANGED,
            (Audience.REPORTER, Audience.ASSIGNEE),
            (ChannelName.IN_APP, ChannelName.EMAIL),
        ),
        (
            NotificationEvent.INFO_REQUESTED,
            (Audience.REPORTER,),
            (ChannelName.IN_APP, ChannelName.EMAIL),
        ),
        (
            NotificationEvent.INFO_PROVIDED,
            (Audience.ASSIGNEE,),
            (ChannelName.IN_APP, ChannelName.EMAIL),
        ),
        (
            NotificationEvent.SLA_APPROACHING,
            (Audience.ASSIGNEE, Audience.TEAM_LEAD),
            (ChannelName.IN_APP, ChannelName.TELEGRAM),
        ),
        (
            NotificationEvent.SLA_VIOLATED,
            (Audience.ASSIGNEE, Audience.TEAM_LEAD, Audience.ADMINS),
            (ChannelName.IN_APP, ChannelName.EMAIL, ChannelName.TELEGRAM),
        ),
        (
            NotificationEvent.ESCALATED,
            (Audience.ASSIGNEE,),
            (ChannelName.IN_APP, ChannelName.TELEGRAM),
        ),
        (
            NotificationEvent.RESOLVED,
            (Audience.REPORTER,),
            (ChannelName.IN_APP, ChannelName.EMAIL),
        ),
        (
            NotificationEvent.CLOSED,
            (Audience.REPORTER, Audience.ASSIGNEE),
            (ChannelName.IN_APP,),
        ),
    ],
)
def test_T_NOTIF_the_table_matches_the_blueprint(
    event: NotificationEvent,
    audiences: tuple[Audience, ...],
    channels: tuple[ChannelName, ...],
) -> None:
    route = route_for(event)
    assert route.audiences_for(Priority.P1) == audiences
    assert route.channels_for(Priority.P1) == channels


def test_closing_an_incident_never_sends_an_email() -> None:
    """§5.4 Closed is in-app only, whatever the priority."""
    route = route_for(NotificationEvent.CLOSED)
    for priority in Priority:
        assert route.channels_for(priority) == (ChannelName.IN_APP,)


# ---------------------------------------------------------------- one notification
def test_a_new_notification_is_pending_unsent_and_unread() -> None:
    created = note()
    assert created.status is DeliveryStatus.PENDING
    assert created.attempts == 0
    assert created.sent_at is None
    assert created.is_read is False
    assert created.can_retry is True
    assert created.id is None


def test_a_notification_needs_a_subject() -> None:
    with pytest.raises(InvalidUserInputError):
        note(subject="   ")


def test_a_sent_notification_records_when_and_stops_retrying() -> None:
    sent = note()
    sent.mark_sent(NOW)
    assert sent.status is DeliveryStatus.SENT
    assert sent.sent_at == NOW
    assert sent.attempts == 1
    assert sent.can_retry is False


def test_three_failures_give_up() -> None:
    """§5.4: a failed send is retried up to three times."""
    failing = note()
    for attempt in range(1, MAX_SEND_ATTEMPTS):
        failing.record_failure()
        assert failing.attempts == attempt
        assert failing.status is DeliveryStatus.PENDING
        assert failing.can_retry is True

    failing.record_failure()
    assert failing.attempts == MAX_SEND_ATTEMPTS
    assert failing.status is DeliveryStatus.FAILED
    assert failing.can_retry is False


def test_a_retry_that_succeeds_counts_the_attempts() -> None:
    flaky = note()
    flaky.record_failure()
    flaky.mark_sent(NOW + timedelta(seconds=1))
    assert (flaky.attempts, flaky.status) == (2, DeliveryStatus.SENT)


def test_reading_a_notification_is_recorded_once() -> None:
    bell = note(channel=ChannelName.IN_APP)
    bell.mark_read(NOW)
    bell.mark_read(NOW + timedelta(hours=1))
    assert bell.read_at == NOW
    assert bell.is_read is True


def test_the_repository_can_give_a_notification_its_id() -> None:
    stored = note()
    stored.identify(42)
    assert stored.id == 42
