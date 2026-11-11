"""Column types shared by the schema.

SQLite has no native timestamp type and drops the time zone, so every timestamp goes through
``UtcDateTime``: it refuses naive values on the way in and hands back aware UTC on the way out
(blueprint §9: timestamps are stored as timezone-aware UTC and displayed in IST).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import BigInteger, DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """A timestamp that is always timezone-aware UTC in Python, on SQLite and PostgreSQL."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            msg = "Timestamps must be timezone-aware (inject a Clock; see AGENTS.md: Time)."
            raise ValueError(msg)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Seconds(TypeDecorator[timedelta]):
    """A duration stored as whole seconds, so SLA targets read the same on both databases."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: timedelta | None, dialect: Dialect) -> int | None:
        return None if value is None else int(value.total_seconds())

    def process_result_value(self, value: Any, dialect: Dialect) -> timedelta | None:
        return None if value is None else timedelta(seconds=int(value))
