"""The hash-chained audit trail (blueprint §8, BR-10): append-only and tamper-evident."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.audit import (
    AuditAction,
    AuditRecord,
    ChainVerification,
    verify_chain,
)
from app.domain.errors import InvalidUserInputError

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def chain(count: int) -> list[AuditRecord]:
    records: list[AuditRecord] = []
    previous: str | None = None
    for index in range(count):
        record = AuditRecord.chained(
            previous_hash=previous,
            occurred_at=NOW + timedelta(seconds=index),
            action=AuditAction.INCIDENT_CREATED,
            actor_id=index + 1,
            incident_id=f"INC-2026-{index + 1:04d}",
            details={"title": f"number {index}"},
        )
        records.append(record)
        previous = record.hash
    return records


def test_the_first_record_has_no_previous_hash() -> None:
    first = chain(1)[0]
    assert first.previous_hash is None
    assert len(first.hash) == 64
    assert first.hash == first.hash.lower()


def test_each_record_chains_onto_the_one_before_it() -> None:
    records = chain(4)
    assert [r.previous_hash for r in records[1:]] == [r.hash for r in records[:-1]]
    assert len({r.hash for r in records}) == 4


def test_the_same_content_in_the_same_place_hashes_the_same() -> None:
    assert chain(3)[2].hash == chain(3)[2].hash


def test_the_same_content_after_a_different_history_hashes_differently() -> None:
    """h_i = SHA256(h_i-1 || record_i): the position in the chain is part of the hash."""
    standalone = AuditRecord.chained(
        previous_hash=None,
        occurred_at=NOW,
        action=AuditAction.LOGIN_SUCCEEDED,
        actor_id=1,
    )
    after_something = AuditRecord.chained(
        previous_hash="a" * 64,
        occurred_at=NOW,
        action=AuditAction.LOGIN_SUCCEEDED,
        actor_id=1,
    )
    assert standalone.hash != after_something.hash


def test_changing_any_field_changes_the_hash() -> None:
    base = AuditRecord.chained(
        previous_hash=None,
        occurred_at=NOW,
        action=AuditAction.PRIORITY_OVERRIDDEN,
        actor_id=2,
        incident_id="INC-2026-0001",
        details={"reason": "exam tomorrow"},
    )
    changed = [
        AuditRecord.chained(
            previous_hash=None,
            occurred_at=NOW + timedelta(microseconds=1),
            action=AuditAction.PRIORITY_OVERRIDDEN,
            actor_id=2,
            incident_id="INC-2026-0001",
            details={"reason": "exam tomorrow"},
        ),
        AuditRecord.chained(
            previous_hash=None,
            occurred_at=NOW,
            action=AuditAction.CATEGORY_OVERRIDDEN,
            actor_id=2,
            incident_id="INC-2026-0001",
            details={"reason": "exam tomorrow"},
        ),
        AuditRecord.chained(
            previous_hash=None,
            occurred_at=NOW,
            action=AuditAction.PRIORITY_OVERRIDDEN,
            actor_id=3,
            incident_id="INC-2026-0001",
            details={"reason": "exam tomorrow"},
        ),
        AuditRecord.chained(
            previous_hash=None,
            occurred_at=NOW,
            action=AuditAction.PRIORITY_OVERRIDDEN,
            actor_id=2,
            incident_id="INC-2026-0002",
            details={"reason": "exam tomorrow"},
        ),
        AuditRecord.chained(
            previous_hash=None,
            occurred_at=NOW,
            action=AuditAction.PRIORITY_OVERRIDDEN,
            actor_id=2,
            incident_id="INC-2026-0001",
            details={"reason": "exam today"},
        ),
        AuditRecord.chained(
            previous_hash=None,
            occurred_at=NOW,
            action=AuditAction.PRIORITY_OVERRIDDEN,
            actor_id=2,
            incident_id="INC-2026-0001",
            details={},
        ),
    ]
    assert all(record.hash != base.hash for record in changed)
    assert len({record.hash for record in changed}) == len(changed)


def test_details_order_does_not_change_the_hash() -> None:
    first = AuditRecord.chained(
        previous_hash=None,
        occurred_at=NOW,
        action=AuditAction.CONFIGURATION_CHANGED,
        actor_id=4,
        details={"a": 1, "b": 2},
    )
    second = AuditRecord.chained(
        previous_hash=None,
        occurred_at=NOW,
        action=AuditAction.CONFIGURATION_CHANGED,
        actor_id=4,
        details={"b": 2, "a": 1},
    )
    assert first.hash == second.hash


def test_an_untouched_chain_verifies() -> None:
    assert verify_chain(chain(5)) == ChainVerification(True, 5, None)
    assert verify_chain([]) == ChainVerification(True, 0, None)


def test_a_tampered_record_is_found_at_its_position() -> None:
    records = chain(5)
    forged = AuditRecord(
        previous_hash=records[2].previous_hash,
        occurred_at=records[2].occurred_at,
        action=records[2].action,
        actor_id=records[2].actor_id,
        incident_id=records[2].incident_id,
        details={"title": "edited after the fact"},
        hash=records[2].hash,  # the attacker kept the old hash
    )
    records[2] = forged
    result = verify_chain(records)
    assert result.intact is False
    assert result.broken_at == 2


def test_a_deleted_record_breaks_the_chain() -> None:
    records = chain(5)
    del records[2]
    result = verify_chain(records)
    assert result.intact is False
    assert result.broken_at == 2


def test_a_record_with_a_wrong_first_link_is_rejected() -> None:
    records = chain(3)
    records[0] = AuditRecord(
        previous_hash="b" * 64,
        occurred_at=records[0].occurred_at,
        action=records[0].action,
        actor_id=records[0].actor_id,
        incident_id=records[0].incident_id,
        details=dict(records[0].details),
        hash=records[0].hash,
    )
    assert verify_chain(records).broken_at == 0


def test_details_must_be_json_safe() -> None:
    with pytest.raises(InvalidUserInputError):
        AuditRecord.chained(
            previous_hash=None,
            occurred_at=NOW,
            action=AuditAction.LOGIN_FAILED,
            actor_id=None,
            details={"when": NOW},  # a datetime is not JSON
        )


def test_records_are_read_only() -> None:
    record = chain(1)[0]
    with pytest.raises(AttributeError):
        record.action = AuditAction.LOGIN_FAILED  # type: ignore[misc]
    assert record.details["title"] == "number 0"
