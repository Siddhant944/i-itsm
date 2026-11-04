"""Running the SLA monitor on a timer (blueprint §5.2, D-003).

APScheduler calls one method; everything the monitor does is in ``SLAMonitor.tick``, which is
why the schedule can be tested separately from the rules. The interval is 30 seconds of
*clock* time, so under the demo's ×10 clock the job really runs every 3 real seconds and a
P1's escalations at 5, 10 and 15 minutes happen 30, 60 and 90 real seconds into the demo.
"""

import logging
from collections.abc import Callable
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.clock import Clock
from app.services.sla_monitor import TICK_INTERVAL, TickReport

logger = logging.getLogger(__name__)
JOB_ID = "sla-monitor"
MIN_REAL_SECONDS = 0.5  # never spin faster than this, however fast the clock runs


def real_interval(clock: Clock, interval: timedelta = TICK_INTERVAL) -> float:
    """How many real seconds apart the job should run for ``interval`` of clock time."""
    return max(MIN_REAL_SECONDS, clock.real_seconds(interval))


class MonitorScheduler:
    """Starts and stops the background tick. A thin wrapper, so the app can do without it."""

    def __init__(
        self,
        tick: Callable[[], TickReport],
        clock: Clock,
        interval: timedelta = TICK_INTERVAL,
    ) -> None:
        self.__tick = tick
        self.__seconds = real_interval(clock, interval)
        self.__scheduler = BackgroundScheduler(daemon=True)

    @property
    def seconds(self) -> float:
        """The real-time gap between runs (D-003)."""
        return self.__seconds

    @property
    def running(self) -> bool:
        return bool(self.__scheduler.running)

    def start(self) -> None:
        if self.running:
            return
        self.__scheduler.add_job(
            self.__run,
            trigger="interval",
            seconds=self.__seconds,
            id=JOB_ID,
            max_instances=1,  # a slow tick must not overlap the next one
            coalesce=True,  # and a missed run is skipped, not queued up
            replace_existing=True,
        )
        self.__scheduler.start()
        logger.info("SLA monitor scheduled every %.1f real seconds", self.__seconds)

    def stop(self) -> None:
        if self.running:
            self.__scheduler.shutdown(wait=False)

    def __run(self) -> None:
        """One tick, with its failures logged: a crash must not kill the scheduler thread."""
        try:
            self.__tick()
        except Exception:
            logger.exception("the SLA monitor tick failed")
