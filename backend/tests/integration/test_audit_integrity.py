"""The admin's "verify integrity" action must notice a row edited behind the API's back.

The chain is only worth having if tampering is detectable in the real table, so these tests
change ``audit_log`` with raw SQL — the one thing the application itself never does (BR-10).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete, select, update

from app.core.clock import FakeClock
from app.domain.audit import AuditAction
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
    """``audit_log.hash`` is unique, so a replayed record cannot be slipped in."""
    from sqlalchemy.exc import IntegrityError

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
    with pytest.raises(IntegrityError):
        uow.commit()
    uow.rollback()
