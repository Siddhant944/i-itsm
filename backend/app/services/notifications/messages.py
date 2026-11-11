"""The words each notification uses (blueprint §5.4, and §1's plain-language requirement).

Templates are data, so a wording change is one line here and the same text goes to every
channel. Times are rendered in IST, because that is what a reader on campus expects (§9).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.domain.incident import Incident
from app.domain.notifications import NotificationEvent
from app.services.notifications.channels import shown_at


@dataclass(frozen=True, slots=True)
class Message:
    subject: str
    body: str


_SUBJECTS: Mapping[NotificationEvent, str] = MappingProxyType(
    {
        NotificationEvent.CREATED: "{id}: we have your report",
        NotificationEvent.ASSIGNED: "{id} is with a technician",
        NotificationEvent.PRIORITY_CHANGED: "{id} is now {priority}",
        NotificationEvent.INFO_REQUESTED: "{id}: the technician has a question",
        NotificationEvent.INFO_PROVIDED: "{id}: the reporter has answered",
        NotificationEvent.SLA_APPROACHING: "{id} is close to its SLA deadline",
        NotificationEvent.SLA_VIOLATED: "{id} has breached its SLA",
        NotificationEvent.ESCALATED: "{id} has been escalated to you",
        NotificationEvent.RESOLVED: "{id} is resolved: please confirm",
        NotificationEvent.CLOSED: "{id} is closed",
    }
)

_BODIES: Mapping[NotificationEvent, str] = MappingProxyType(
    {
        NotificationEvent.CREATED: (
            "Thanks for telling us about '{title}'.\n"
            "We logged it as {id} at {created_at} and set it to {priority}.\n"
            "You can follow it in the I-ITSM portal."
        ),
        NotificationEvent.ASSIGNED: (
            "{id} ('{title}') is now with a technician.\n"
            "Priority {priority}. We will come back to you as soon as there is news."
        ),
        NotificationEvent.PRIORITY_CHANGED: (
            "The priority of {id} ('{title}') is now {priority}.\n{detail}"
        ),
        NotificationEvent.INFO_REQUESTED: (
            "The technician working on {id} ('{title}') needs something from you:\n\n"
            "{detail}\n\nPlease reply in the portal; the clock is paused until you do."
        ),
        NotificationEvent.INFO_PROVIDED: (
            "The person who reported {id} ('{title}') has answered your question:\n\n{detail}"
        ),
        NotificationEvent.SLA_APPROACHING: (
            "{id} ('{title}', {priority}) is close to its SLA deadline.\n{detail}"
        ),
        NotificationEvent.SLA_VIOLATED: (
            "{id} ('{title}', {priority}) has passed its SLA deadline.\n{detail}"
        ),
        NotificationEvent.ESCALATED: (
            "{id} ('{title}', {priority}) has been escalated to you.\n{detail}"
        ),
        NotificationEvent.RESOLVED: (
            "A technician believes {id} ('{title}') is fixed:\n\n{detail}\n\n"
            "Please confirm in the portal, or tell us it is still broken. "
            "If we hear nothing, it closes itself in 72 hours."
        ),
        NotificationEvent.CLOSED: "{id} ('{title}') is now closed. {detail}Thank you.",
    }
)


def compose(event: NotificationEvent, incident: Incident, detail: str = "") -> Message:
    """The subject and body for ``event`` about ``incident``."""
    fields = {
        "id": incident.id,
        "title": incident.title,
        "priority": incident.priority.label if incident.priority else "not yet set",
        "created_at": shown_at(incident.created_at),
        "detail": detail,
    }
    return Message(
        subject=_SUBJECTS[event].format(**fields),
        body=_BODIES[event].format(**fields).strip(),
    )
