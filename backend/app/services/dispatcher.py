"""Delivering what happens after a transaction commits (blueprint §5.4).

Audit records go in with the change; notifications and real-time pushes go out afterwards, and
a failed send must never roll the change back. This collects the work during the transaction and
runs it after the commit, swallowing and logging each failure on its own.
"""

import logging
from collections.abc import Callable, Iterable, Sequence

from app.domain.events import DomainEvent

logger = logging.getLogger(__name__)

Subscriber = Callable[[DomainEvent], None]


class PostCommitDispatcher:
    """Queue events during a transaction, deliver them once it has committed.

    Pattern: Observer, deferred. Problem solved: notifications must see committed data and must
    not be able to undo it, so nothing is delivered until ``dispatch`` is called after commit,
    and one subscriber raising never stops the others or reaches the caller.
    """

    def __init__(self, subscribers: Iterable[Subscriber] = ()) -> None:
        self.__subscribers: list[Subscriber] = list(subscribers)
        self.__pending: list[DomainEvent] = []

    def subscribe(self, subscriber: Subscriber) -> None:
        self.__subscribers.append(subscriber)

    def enqueue(self, events: Iterable[DomainEvent]) -> None:
        self.__pending.extend(events)

    @property
    def pending(self) -> Sequence[DomainEvent]:
        return tuple(self.__pending)

    def discard(self) -> None:
        """Forget the queue: the transaction rolled back, so nothing happened."""
        self.__pending.clear()

    def dispatch(self) -> int:
        """Deliver everything queued. Returns how many events were delivered."""
        events, self.__pending = list(self.__pending), []
        for event in events:
            for subscriber in tuple(self.__subscribers):
                try:
                    subscriber(event)
                except Exception:
                    logger.exception(
                        "notification subscriber failed for %s on %s",
                        type(event).__name__,
                        event.incident_id,
                    )
        return len(events)
