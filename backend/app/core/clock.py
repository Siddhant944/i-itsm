"""Injectable time source (blueprint §5.2). Nothing else in the code reads the wall clock.

Pattern: Strategy (with a Null-Object-like FakeClock for tests). Problem solved: SLA deadlines,
escalation and auto-close depend on "now"; injecting the clock makes them deterministic in tests
(FakeClock) and watchable in the demo (AcceleratedClock x10), with no change to business code.
All clocks return timezone-aware UTC datetimes; display code converts to IST.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime, timedelta


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "clock datetimes must be timezone-aware"
        raise ValueError(msg)
    return value.astimezone(UTC)


class Clock(ABC):
    """Interface: the current time, and how long a clock interval lasts in real seconds."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current time as an aware UTC datetime."""

    def real_seconds(self, interval: timedelta) -> float:
        """Real (wall) seconds that pass while this clock advances by ``interval``."""
        return interval.total_seconds()


class SystemClock(Clock):
    """Production clock: the real current time."""

    def now(self) -> datetime:
        return datetime.now(UTC)  # noqa: TID251 - the one sanctioned wall-clock read


class FakeClock(Clock):
    """Test clock: stands still until advanced; never moves backwards."""

    def __init__(self, start: datetime) -> None:
        self.__now = _require_aware_utc(start)

    def now(self) -> datetime:
        return self.__now

    def advance(self, delta: timedelta) -> None:
        """Move time forward by ``delta``."""
        self.set(self.__now + delta)

    def set(self, moment: datetime) -> None:
        """Jump to ``moment``, which must not be earlier than the current time."""
        moment = _require_aware_utc(moment)
        if moment < self.__now:
            msg = "a clock cannot move backwards"
            raise ValueError(msg)
        self.__now = moment


class AcceleratedClock(Clock):
    """Demo clock: time runs ``factor`` times faster than real time from ``start``.

    With factor 10, the 5-minute P1 response window passes in 30 real seconds (blueprint §14).
    """

    def __init__(
        self,
        factor: float,
        start: datetime | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if factor <= 0:
            msg = "acceleration factor must be positive"
            raise ValueError(msg)
        self.__factor = factor
        self.__start = _require_aware_utc(start) if start is not None else SystemClock().now()
        self.__monotonic = monotonic
        self.__origin = monotonic()

    @property
    def factor(self) -> float:
        """How many clock seconds pass per real second."""
        return self.__factor

    def now(self) -> datetime:
        elapsed = self.__monotonic() - self.__origin
        return self.__start + timedelta(seconds=elapsed * self.__factor)

    def real_seconds(self, interval: timedelta) -> float:
        return interval.total_seconds() / self.__factor
