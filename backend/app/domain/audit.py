"""The audit trail (blueprint §8, BR-10).

Records are append-only and hash-chained: h_i = SHA256(h_(i-1) || record_i). Each record's hash
covers the one before it, so editing or deleting an entry breaks every link after it and
``verify_chain`` says exactly where. The chain is computed here, in the domain, with no
database and no clock of its own, which is what makes it testable and portable.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from app.domain.errors import InvalidUserInputError

HASH_LENGTH = 64  # SHA-256 as hex


class AuditAction(StrEnum):
    """What happened. Every state change and every sensitive action gets one (blueprint §8)."""

    # --- authentication
    USER_REGISTERED = "user.registered"
    LOGIN_SUCCEEDED = "login.succeeded"
    LOGIN_FAILED = "login.failed"
    ACCOUNT_LOCKED = "account.locked"
    PASSWORD_CHANGED = "password.changed"  # noqa: S105 - an action name, not a credential
    UNAUTHORIZED_ATTEMPT = "authorization.refused"
    # --- incidents
    INCIDENT_CREATED = "incident.created"
    INCIDENT_STATE_CHANGED = "incident.state_changed"
    INCIDENT_NOTE_ADDED = "incident.note_added"
    PRIORITY_ASSESSED = "incident.priority_assessed"
    PRIORITY_OVERRIDDEN = "incident.priority_overridden"
    CATEGORY_OVERRIDDEN = "incident.category_overridden"
    INCIDENT_ESCALATED = "incident.escalated"
    SLA_VIOLATED = "sla.violated"
    # --- administration
    CONFIGURATION_CHANGED = "configuration.changed"
    USER_MANAGED = "user.managed"


def _canonical_details(details: Mapping[str, object] | None) -> str:
    """JSON with sorted keys, so two equal payloads always hash alike."""
    try:
        return json.dumps(dict(details or {}), sort_keys=True, separators=(",", ":"))
    except TypeError as error:
        raise InvalidUserInputError(
            {"details": "Audit details must be JSON-serialisable."}
        ) from error


def chain_hash(
    previous_hash: str | None,
    occurred_at: datetime,
    action: str,
    actor_id: int | None,
    incident_id: str | None,
    details: Mapping[str, object] | None,
) -> str:
    """h_i = SHA256(h_(i-1) || record_i), over a canonical rendering of the record."""
    payload = "|".join(
        (
            previous_hash or "",
            occurred_at.isoformat(),
            str(action),
            "" if actor_id is None else str(actor_id),
            incident_id or "",
            _canonical_details(details),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One entry in the chain. Frozen: an audit record is never edited, only appended."""

    previous_hash: str | None
    occurred_at: datetime
    action: AuditAction
    actor_id: int | None
    hash: str
    incident_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    @classmethod
    def chained(
        cls,
        *,
        previous_hash: str | None,
        occurred_at: datetime,
        action: AuditAction,
        actor_id: int | None,
        incident_id: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> "AuditRecord":
        """Build the next record after ``previous_hash`` and compute its hash."""
        return cls(
            previous_hash=previous_hash,
            occurred_at=occurred_at,
            action=action,
            actor_id=actor_id,
            incident_id=incident_id,
            details=dict(details or {}),
            hash=chain_hash(previous_hash, occurred_at, action, actor_id, incident_id, details),
        )

    @property
    def expected_hash(self) -> str:
        """What this record's hash should be, given its contents and its predecessor."""
        return chain_hash(
            self.previous_hash,
            self.occurred_at,
            self.action,
            self.actor_id,
            self.incident_id,
            self.details,
        )


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """The result an admin sees from "verify integrity"."""

    intact: bool
    checked: int
    broken_at: int | None

    @property
    def summary(self) -> str:
        if self.intact:
            return f"{self.checked} audit records verified; the chain is intact."
        return f"The audit chain breaks at record {self.broken_at} of {self.checked}."


def verify_chain(
    records: Sequence[AuditRecord], first_previous: str | None = None
) -> ChainVerification:
    """Recompute every hash and check that each record points at the one before it.

    ``first_previous`` is the hash the chain is expected to start after, which lets a page of
    records be verified against the record just before the page.
    """
    expected_previous = first_previous
    for index, record in enumerate(records):
        if record.previous_hash != expected_previous or record.hash != record.expected_hash:
            return ChainVerification(False, len(records), index)
        expected_previous = record.hash
    return ChainVerification(True, len(records), None)
