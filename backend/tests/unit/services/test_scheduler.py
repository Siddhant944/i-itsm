"""Scheduling the SLA monitor (blueprint §5.2, D-003)."""

import time
from datetime import UTC, datetime, timedelta

from app.core.clock import AcceleratedClock, FakeClock, SystemClock
from app.services.scheduler import MIN_REAL_SECONDS, MonitorScheduler, real_interval
from app.services.sla_monitor import TICK_INTERVAL, TickReport

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def test_the_real_gap_follows_the_clock_d003() -> None:
    """30 s of clock time is 30 real seconds normally, and 3 under the demo's ×10 clock."""
    assert real_interval(SystemClock()) == 30.0
    assert real_interval(AcceleratedClock(10.0)) == 3.0
    assert real_interval(AcceleratedClock(10.0), timedelta(minutes=5)) == 30.0


def test_a_very_fast_clock_is_still_bounded() -> None:
    assert real_interval(AcceleratedClock(10_000.0)) == MIN_REAL_SECONDS


def test_the_scheduler_reports_its_interval_without_starting() -> None:
    scheduler = MonitorScheduler(lambda: TickReport(), SystemClock())
    assert scheduler.seconds == 30.0
    assert scheduler.running is False
    scheduler.stop()  # stopping something that never started is harmless


def test_the_scheduler_runs_the_tick_and_stops_cleanly() -> None:
    runs: list[int] = []

    def tick() -> TickReport:
        runs.append(1)
        return TickReport()

    # One clock second is MIN_REAL_SECONDS of real time, which keeps the test quick.
    scheduler = MonitorScheduler(tick, SystemClock(), timedelta(milliseconds=1))
    scheduler.start()
    assert scheduler.running is True
    scheduler.start()  # starting twice must not schedule the job twice
    deadline = time.monotonic() + 5
    while not runs and time.monotonic() < deadline:
        time.sleep(0.05)
    scheduler.stop()
    assert runs, "the scheduled tick never ran"
    assert scheduler.running is False


def test_a_failing_tick_does_not_kill_the_scheduler() -> None:
    attempts: list[int] = []

    def tick() -> TickReport:
        attempts.append(1)
        msg = "the database went away"
        raise RuntimeError(msg)

    scheduler = MonitorScheduler(tick, FakeClock(NOW), timedelta(milliseconds=1))
    scheduler.start()
    deadline = time.monotonic() + 5
    while len(attempts) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    still_running = scheduler.running
    scheduler.stop()
    assert len(attempts) >= 2, "the scheduler stopped after the first failure"
    assert still_running is True


def test_a_fake_clock_schedules_like_real_time() -> None:
    """A FakeClock does not scale durations, so the job keeps its 30-second gap."""
    assert MonitorScheduler(lambda: TickReport(), FakeClock(NOW)).seconds == 30.0
    assert timedelta(seconds=30) == TICK_INTERVAL
