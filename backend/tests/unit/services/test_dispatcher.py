"""The post-commit dispatcher (blueprint §5.4): nothing blocks or undoes the change."""

from datetime import UTC, datetime

from app.domain.events import DomainEvent, IncidentCreated, WorkNoteAdded
from app.services.dispatcher import PostCommitDispatcher

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
CREATED = IncidentCreated(NOW, "INC-2026-0001", 1, "Wi-Fi down")
NOTED = WorkNoteAdded(NOW, "INC-2026-0001", 2, "note")


def test_nothing_is_delivered_until_dispatch_is_called() -> None:
    seen: list[DomainEvent] = []
    dispatcher = PostCommitDispatcher([seen.append])
    dispatcher.enqueue([CREATED, NOTED])
    assert seen == []
    assert list(dispatcher.pending) == [CREATED, NOTED]

    assert dispatcher.dispatch() == 2
    assert seen == [CREATED, NOTED]
    assert dispatcher.pending == ()


def test_discarding_the_queue_delivers_nothing() -> None:
    seen: list[DomainEvent] = []
    dispatcher = PostCommitDispatcher([seen.append])
    dispatcher.enqueue([CREATED])
    dispatcher.discard()
    assert dispatcher.dispatch() == 0
    assert seen == []


def test_one_failing_subscriber_does_not_stop_the_others() -> None:
    """A dead mail server must not cost us the in-app notification (§5.4)."""
    seen: list[DomainEvent] = []

    def explode(_: DomainEvent) -> None:
        msg = "the mail server is down"
        raise RuntimeError(msg)

    dispatcher = PostCommitDispatcher([explode, seen.append])
    dispatcher.enqueue([CREATED, NOTED])
    assert dispatcher.dispatch() == 2
    assert seen == [CREATED, NOTED]


def test_subscribers_can_be_added_later() -> None:
    seen: list[DomainEvent] = []
    dispatcher = PostCommitDispatcher()
    dispatcher.enqueue([CREATED])
    dispatcher.subscribe(seen.append)
    dispatcher.dispatch()
    assert seen == [CREATED]


def test_dispatching_twice_delivers_once() -> None:
    seen: list[DomainEvent] = []
    dispatcher = PostCommitDispatcher([seen.append])
    dispatcher.enqueue([CREATED])
    dispatcher.dispatch()
    dispatcher.dispatch()
    assert seen == [CREATED]
