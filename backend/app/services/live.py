"""Live updates over WebSockets (blueprint §6.4, P4.8).

Pattern: Observer (publish-subscribe). Problem solved: a technician's queue, a reporter's
incident page and the admin's dashboard should change the moment something happens, without
every open screen asking the server every few seconds.

What is pushed is deliberately thin: "incident INC-… changed". The browser then refetches
through the normal API, so BR-01 keeps deciding what anyone may see, and a push can never leak
an incident's content. Pushes go out only after the commit (the dispatcher's guarantee), to
the reporter, the assignee, and the people who watch everything or a team (leads, admins).

Route handlers run in a thread pool while sockets live on the event loop, so the hub hands
each message to its connection's loop with ``call_soon_threadsafe``.
"""

import asyncio
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from app.domain.errors import ITSMError
from app.domain.events import DomainEvent
from app.domain.repositories import UnitOfWork

logger = logging.getLogger(__name__)

Message = dict[str, Any]
#: A slow or vanished browser is dropped rather than allowed to queue without limit.
MAX_QUEUED = 100


@dataclass(eq=False)
class Subscription:
    """One open socket: who it belongs to, and the queue its sender drains."""

    user_id: int
    #: Leads and admins see every incident change, for queues and dashboards.
    watches_all: bool
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[Message] = field(default_factory=lambda: asyncio.Queue(MAX_QUEUED))
    key: int = field(default_factory=count().__next__)


class LiveHub:
    """The open sockets, and a thread-safe way to put a message on some of them."""

    def __init__(self) -> None:
        self.__lock = threading.Lock()
        self.__subscriptions: dict[int, Subscription] = {}

    def subscribe(self, user_id: int, *, watches_all: bool) -> Subscription:
        subscription = Subscription(user_id, watches_all, asyncio.get_running_loop())
        with self.__lock:
            self.__subscriptions[subscription.key] = subscription
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self.__lock:
            self.__subscriptions.pop(subscription.key, None)

    @property
    def connections(self) -> int:
        with self.__lock:
            return len(self.__subscriptions)

    def publish(self, user_ids: Iterable[int], message: Message) -> int:
        """Send ``message`` to these users and to everyone who watches all; returns how many."""
        wanted = set(user_ids)
        with self.__lock:
            targets = [
                s for s in self.__subscriptions.values() if s.watches_all or s.user_id in wanted
            ]
        for subscription in targets:
            try:
                subscription.loop.call_soon_threadsafe(_offer, subscription.queue, message)
            except RuntimeError:  # the loop has closed: the socket is gone
                self.unsubscribe(subscription)
        return len(targets)


def _offer(queue: asyncio.Queue[Message], message: Message) -> None:
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        logger.warning("live update dropped: a client is not reading")


class LivePublisher:
    """Turns committed incident events into pushes. Never raises: §5.4 forbids blocking."""

    def __init__(self, uow: UnitOfWork, hub: LiveHub) -> None:
        self.__uow = uow
        self.__hub = hub
        self.__sent: set[str] = set()

    def on_event(self, event: DomainEvent) -> None:
        """The dispatcher's subscriber: one push per incident per request, however many events."""
        if event.incident_id in self.__sent:
            return
        self.__sent.add(event.incident_id)
        self.incident_changed(event.incident_id)

    def incident_changed(self, incident_id: str) -> None:
        try:
            incident = self.__uow.incidents.get(incident_id)
            people = {incident.reporter_id}
            if incident.assignee_id is not None:
                people.add(incident.assignee_id)
            followers = self.__uow.incidents.duplicates_of(incident.id)
            self.__hub.publish(
                people,
                {"type": "incident", "incident_id": incident.id, "status": incident.status.value},
            )
            for duplicate in followers:
                # A follower's own page shows the parent's status (D-005): refresh it, named
                # by their own incident's id, which is the one they may open (BR-01).
                self.__hub.publish(
                    {duplicate.reporter_id},
                    {
                        "type": "incident",
                        "incident_id": duplicate.id,
                        "status": duplicate.status.value,
                    },
                )
        except ITSMError:
            logger.exception("could not push a live update for %s", incident_id)

    def incidents_changed(self, incident_ids: Iterable[str]) -> None:
        for incident_id in dict.fromkeys(incident_ids):
            self.incident_changed(incident_id)
