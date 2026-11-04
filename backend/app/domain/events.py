"""Domain events and the in-process event bus.

Pattern: Observer. Problem solved: audit, notifications and real-time pushes must react to
incident changes without the Incident knowing about them; subscribers register per event type.
The incident records events; the service layer publishes them (audit inside the transaction,
notifications after commit; blueprint §5.4).
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.priority import Priority
from app.domain.states import IncidentStatus


@dataclass(frozen=True, slots=True)
class DomainEvent:
    occurred_at: datetime
    incident_id: str
    actor_id: int | None


@dataclass(frozen=True, slots=True)
class IncidentCreated(DomainEvent):
    title: str


@dataclass(frozen=True, slots=True)
class IncidentStateChanged(DomainEvent):
    from_status: IncidentStatus
    to_status: IncidentStatus
    description: str


@dataclass(frozen=True, slots=True)
class PriorityChanged(DomainEvent):
    old_priority: Priority | None
    new_priority: Priority
    reason: str


@dataclass(frozen=True, slots=True)
class CategoryChanged(DomainEvent):
    """The category was corrected after classification; the status does not change."""

    old_category_id: int | None
    new_category_id: int


@dataclass(frozen=True, slots=True)
class WorkNoteAdded(DomainEvent):
    kind: str


Handler = Callable[[Any], None]


class EventBus:
    """Synchronous publish/subscribe keyed by event class (subclasses reach base handlers)."""

    def __init__(self) -> None:
        self.__handlers: defaultdict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Handler) -> None:
        self.__handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        for event_type in type(event).__mro__:
            for handler in tuple(self.__handlers.get(event_type, ())):
                handler(event)
