"""Writing the audit trail (blueprint §5.4, §8, BR-10).

Every append reads the head of the chain under a lock, builds the next record from it and
inserts it. The service never commits: it writes through the caller's Unit of Work, so an
audit record and the change it describes land in the same transaction and a rolled-back change
leaves no audit entry behind.
"""

from collections.abc import Mapping

from app.core.clock import Clock
from app.domain.audit import AuditAction, AuditRecord, ChainVerification, verify_chain
from app.domain.repositories import AuditRepository

VERIFY_PAGE = 500


class AuditService:
    """Appends to the chain and recomputes it for the admin's "verify integrity" action."""

    def __init__(self, repository: AuditRepository, clock: Clock) -> None:
        self.__repository = repository
        self.__clock = clock

    def record(
        self,
        action: AuditAction,
        *,
        actor_id: int | None = None,
        incident_id: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> AuditRecord:
        """Append one record, chained onto the current head."""
        head = self.__repository.head_for_append()
        record = AuditRecord.chained(
            previous_hash=head.hash if head else None,
            occurred_at=self.__clock.now(),
            action=action,
            actor_id=actor_id,
            incident_id=incident_id,
            details=details,
        )
        self.__repository.append(record)
        return record

    def history(
        self, *, incident_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[AuditRecord, ...]:
        return self.__repository.records(incident_id=incident_id, limit=limit, offset=offset)

    def count(self, *, incident_id: str | None = None) -> int:
        return self.__repository.count(incident_id=incident_id)

    def verify(self) -> ChainVerification:
        """Recompute the whole chain, a page at a time, and report the first break.

        Recomputing alone cannot detect a truncated tail — delete the newest records and every
        remaining link still verifies — so the result is also checked against the head and
        length recorded as the records were appended (blueprint §8).
        """
        total = self.__repository.count()
        checked = 0
        last: str | None = None
        while checked < total:
            page = self.__repository.records(limit=VERIFY_PAGE, offset=checked)
            if not page:
                break
            result = verify_chain(page, self.__repository.hash_before(checked))
            if not result.intact:
                broken = checked + (result.broken_at or 0)
                return ChainVerification(False, total, broken)
            checked += len(page)
            last = page[-1].hash

        expected_hash, expected_length = self.__repository.expected_head()
        if expected_length > total or (expected_hash is not None and expected_hash != last):
            # The links that remain are sound, so the break is at the end: records are missing.
            return ChainVerification(False, total, total, truncated_from=expected_length)
        return ChainVerification(True, total, None)
