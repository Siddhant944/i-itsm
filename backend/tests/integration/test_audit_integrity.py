"""The admin's "verify integrity" action must notice a row edited behind the API's back.

The chain is only worth having if tampering is detectable in the real table, so these tests
change ``audit_log`` with raw SQL — the one thing the application itself never does (BR-10).
"""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete, select, update

from app.core.clock import FakeClock
from app.domain.audit import AuditAction, verify_chain
from app.repositories.database import make_engine
from app.repositories.sqlalchemy.models import AuditRecordRow, Base
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)
from app.services.audit import VERIFY_PAGE, AuditService

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    made = make_engine(database_url)
    Base.metadata.drop_all(made)
    create_schema(made)
    yield made
    Base.metadata.drop_all(made)
    made.dispose()


@pytest.fixture
def uow(engine: Engine) -> Iterator[SqlAlchemyUnitOfWork]:
    unit = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    yield unit
    unit.close()


def chain_of(uow: SqlAlchemyUnitOfWork, count: int) -> AuditService:
    clock = FakeClock(NOW)
    audit = AuditService(uow.audit, clock)
    for index in range(count):
        clock.advance(timedelta(seconds=1))
        audit.record(AuditAction.CONFIGURATION_CHANGED, details={"step": index})
    uow.commit()
    return audit


def test_an_untouched_chain_verifies_in_the_database(uow: SqlAlchemyUnitOfWork) -> None:
    audit = chain_of(uow, 12)
    result = audit.verify()
    assert result.intact is True
    assert result.checked == 12
    assert "intact" in result.summary


def test_editing_a_row_is_detected_at_that_row(uow: SqlAlchemyUnitOfWork) -> None:
    audit = chain_of(uow, 10)
    target = uow.session.scalars(
        select(AuditRecordRow).order_by(AuditRecordRow.id).limit(1).offset(4)
    ).one()
    uow.session.execute(
        update(AuditRecordRow)
        .where(AuditRecordRow.id == target.id)
        .values(details={"step": "edited after the fact"})
    )
    uow.commit()
    uow.session.expire_all()

    result = audit.verify()
    assert result.intact is False
    assert result.broken_at == 4
    assert "breaks at record 4" in result.summary


def test_deleting_a_row_is_detected(uow: SqlAlchemyUnitOfWork) -> None:
    audit = chain_of(uow, 8)
    target = uow.session.scalars(
        select(AuditRecordRow).order_by(AuditRecordRow.id).limit(1).offset(3)
    ).one()
    uow.session.execute(delete(AuditRecordRow).where(AuditRecordRow.id == target.id))
    uow.commit()
    uow.session.expire_all()

    result = audit.verify()
    assert result.intact is False
    assert result.broken_at == 3


def test_verification_crosses_page_boundaries(uow: SqlAlchemyUnitOfWork) -> None:
    """A break must still be found when it falls on the first record of a later page."""
    size = VERIFY_PAGE + 5
    audit = chain_of(uow, size)
    assert audit.verify().intact is True

    target = uow.session.scalars(
        select(AuditRecordRow).order_by(AuditRecordRow.id).limit(1).offset(VERIFY_PAGE)
    ).one()
    uow.session.execute(
        update(AuditRecordRow).where(AuditRecordRow.id == target.id).values(previous_hash="0" * 64)
    )
    uow.commit()
    uow.session.expire_all()

    result = audit.verify()
    assert result.intact is False
    assert result.broken_at == VERIFY_PAGE


def test_the_same_hash_cannot_be_inserted_twice(uow: SqlAlchemyUnitOfWork) -> None:
    """``audit_log.hash`` is unique, so a replayed record cannot be slipped in.

    The unique key surfaces as a 409 conflict rather than a 500, because the realistic cause is
    two writers racing for the same place in the chain.
    """
    from app.api.errors import status_for
    from app.domain.errors import ConcurrentModificationError

    chain_of(uow, 3)
    existing = uow.session.scalars(select(AuditRecordRow).order_by(AuditRecordRow.id)).first()
    assert existing is not None
    uow.session.add(
        AuditRecordRow(
            incident_id=None,
            actor_id=None,
            action=existing.action,
            details=dict(existing.details),
            created_at=existing.created_at,
            previous_hash=existing.previous_hash,
            hash=existing.hash,
        )
    )
    with pytest.raises(ConcurrentModificationError) as caught:
        uow.commit()
    assert status_for(caught.value) == 409
    uow.rollback()


def test_deleting_the_newest_records_is_detected(uow: SqlAlchemyUnitOfWork) -> None:
    """Recomputing hashes alone cannot see a truncated tail: every remaining link verifies.

    This is the attack that matters — someone with database access removing the rows that
    record what they just did — so the chain's expected head and length are kept as records are
    appended, and verify checks the recomputed chain against them (§8).
    """
    audit = chain_of(uow, 10)
    assert audit.verify().intact is True

    newest = uow.session.scalars(
        select(AuditRecordRow).order_by(AuditRecordRow.id.desc()).limit(3)
    ).all()
    for row in newest:
        uow.session.delete(row)
    uow.commit()
    uow.session.expire_all()

    result = audit.verify()
    assert result.intact is False
    assert result.checked == 7
    assert result.truncated_from == 10
    assert "missing its 3 most recent record(s)" in result.summary


def test_deleting_the_whole_chain_is_detected(uow: SqlAlchemyUnitOfWork) -> None:
    audit = chain_of(uow, 5)
    uow.session.execute(delete(AuditRecordRow))
    uow.commit()
    uow.session.expire_all()

    result = audit.verify()
    assert result.intact is False
    assert result.checked == 0
    assert result.truncated_from == 5


def test_a_tampered_tail_record_is_still_caught_as_a_broken_link(
    uow: SqlAlchemyUnitOfWork,
) -> None:
    """Editing the newest record breaks its own hash, which is a break, not a truncation."""
    audit = chain_of(uow, 6)
    newest = uow.session.scalars(
        select(AuditRecordRow).order_by(AuditRecordRow.id.desc()).limit(1)
    ).one()
    uow.session.execute(
        update(AuditRecordRow)
        .where(AuditRecordRow.id == newest.id)
        .values(details={"step": "rewritten"})
    )
    uow.commit()
    uow.session.expire_all()

    result = audit.verify()
    assert result.intact is False
    assert result.broken_at == 5
    assert result.truncated_from is None


def test_two_transactions_appending_at_once_do_not_break_the_chain(
    engine: Engine, database_url: str
) -> None:
    """§8: "appends are serialised by locking the head of the chain".

    A ``FOR UPDATE`` on the newest audit row would not do it — a concurrent INSERT takes no
    lock on that row, so both writers could read record N as the head and both claim to follow
    it. The lock is on a marker row every appender must update instead. This only has anything
    to prove on PostgreSQL; SQLite's single-writer lock serialises everything anyway.
    """
    if not database_url.startswith("postgresql"):
        pytest.skip("concurrent writers need a database that allows them")

    sessions = make_session_factory(engine)
    start = threading.Barrier(2)
    failures: list[Exception] = []

    def append(writer: int) -> None:
        clock = FakeClock(NOW + timedelta(seconds=writer))
        uow = SqlAlchemyUnitOfWork(sessions, clock)
        try:
            audit = AuditService(uow.audit, clock)
            start.wait(timeout=30)
            for step in range(5):
                audit.record(
                    AuditAction.CONFIGURATION_CHANGED, details={"writer": writer, "step": step}
                )
            uow.commit()
        except Exception as error:
            failures.append(error)
            uow.rollback()
        finally:
            uow.close()

    threads = [threading.Thread(target=append, args=(writer,)) for writer in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert failures == [], f"an appender failed: {failures}"

    check = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    try:
        records = check.audit.records(limit=1000)
        assert len(records) == 10
        assert verify_chain(records).intact is True
        assert AuditService(check.audit, FakeClock(NOW)).verify().intact is True
    finally:
        check.close()
