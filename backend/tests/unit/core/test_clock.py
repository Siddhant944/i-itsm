from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.clock import AcceleratedClock, Clock, FakeClock, SystemClock

START = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


def test_every_clock_is_a_clock() -> None:
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FakeClock(START), Clock)
    assert isinstance(AcceleratedClock(10, start=START), Clock)


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC


def test_fake_clock_stands_still_until_advanced() -> None:
    clock = FakeClock(START)
    assert clock.now() == START
    clock.advance(timedelta(minutes=5))
    assert clock.now() == START + timedelta(minutes=5)


def test_fake_clock_can_be_set_but_never_moves_backwards() -> None:
    clock = FakeClock(START)
    clock.set(START + timedelta(hours=1))
    assert clock.now() == START + timedelta(hours=1)
    with pytest.raises(ValueError, match="backwards"):
        clock.set(START)
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(timedelta(seconds=-1))


def test_fake_clock_normalises_other_timezones_to_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    clock = FakeClock(datetime(2026, 11, 5, 15, 30, tzinfo=ist))
    assert clock.now() == START
    assert clock.now().tzinfo is UTC


def test_clocks_reject_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 11, 5, 10, 0))  # noqa: DTZ001 - deliberately naive
    with pytest.raises(ValueError, match="timezone-aware"):
        AcceleratedClock(10, start=datetime(2026, 11, 5, 10, 0))  # noqa: DTZ001


class _Ticker:
    """A controllable monotonic source (seconds)."""

    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def test_accelerated_clock_runs_factor_times_faster() -> None:
    ticker = _Ticker()
    clock = AcceleratedClock(10, start=START, monotonic=ticker)

    assert clock.now() == START
    ticker.value += 30  # 30 real seconds ...
    assert clock.now() == START + timedelta(minutes=5)  # ... are 5 clock minutes (§5.2)
    assert clock.factor == 10


def test_accelerated_clock_converts_clock_intervals_to_real_seconds() -> None:
    clock = AcceleratedClock(10, start=START)
    assert clock.real_seconds(timedelta(seconds=30)) == pytest.approx(3.0)  # D-003


@pytest.mark.parametrize("factor", [0, -1])
def test_accelerated_clock_rejects_non_positive_factor(factor: float) -> None:
    with pytest.raises(ValueError, match="factor"):
        AcceleratedClock(factor, start=START)


def test_system_and_fake_clocks_run_at_real_speed() -> None:
    assert SystemClock().real_seconds(timedelta(seconds=30)) == 30
    assert FakeClock(START).real_seconds(timedelta(seconds=30)) == 30


def test_utc_is_displayed_in_ist() -> None:
    """Blueprint §9: timestamps are stored as UTC and shown in IST (+5:30, no DST)."""
    from datetime import UTC, datetime

    from app.core.clock import in_ist

    shown = in_ist(datetime(2026, 11, 6, 9, 0, tzinfo=UTC))
    assert (shown.hour, shown.minute) == (14, 30)
    assert shown.strftime("%d %b %Y, %H:%M") == "06 Nov 2026, 14:30"
    # Still the same moment, in January too (India has no daylight saving).
    assert shown == datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
    assert in_ist(datetime(2027, 1, 1, 20, 0, tzinfo=UTC)).day == 2


def test_each_clock_reports_how_fast_it_runs() -> None:
    start = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
    assert SystemClock().rate == 1.0
    assert FakeClock(start).rate == 0.0
    assert AcceleratedClock(10, start).rate == 10
