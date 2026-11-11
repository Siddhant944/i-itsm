"""The numbers the dashboards show (blueprint §9 "Search and reports").

These are value objects with the arithmetic that turns raw counts into the figures §9 names:
mean time to acknowledge and to resolve, SLA compliance, average satisfaction and the reopen
rate. Doing the division here keeps it out of the SQL and makes every edge case — no incidents
yet, nothing resolved yet, nobody has rated anything — a tested one rather than a crash.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

PERCENT = 100.0


def _share(part: int, whole: int) -> float:
    """``part`` as a percentage of ``whole``, rounded to one place; 0 when there is no whole."""
    if whole <= 0:
        return 0.0
    return round(part * PERCENT / whole, 1)


def _mean(total: timedelta, count: int) -> timedelta | None:
    """The average, or None when there is nothing to average (an empty dashboard, not a zero)."""
    if count <= 0:
        return None
    return total / count


@dataclass(frozen=True, slots=True)
class Overview:
    """The cards at the top of every dashboard."""

    total: int
    open_count: int
    unassigned: int
    awaiting_reporter: int
    breached: int
    at_risk: int
    critical_open: int
    resolved_in_window: int

    @property
    def open_share(self) -> float:
        return _share(self.open_count, self.total)

    @property
    def breached_share(self) -> float:
        return _share(self.breached, self.total)


@dataclass(frozen=True, slots=True)
class DurationStats:
    """A mean built from a total and a count, so "no data yet" stays distinguishable from zero."""

    total: timedelta = timedelta()
    count: int = 0

    @property
    def mean(self) -> timedelta | None:
        return _mean(self.total, self.count)

    @property
    def mean_hours(self) -> float | None:
        average = self.mean
        return None if average is None else round(average.total_seconds() / 3600, 2)


@dataclass(frozen=True, slots=True)
class ServiceMetrics:
    """One row of the service analysis table (§9)."""

    service_id: int
    name: str
    incidents: int
    breached: int
    resolution: DurationStats = field(default_factory=DurationStats)

    @property
    def breach_share(self) -> float:
        return _share(self.breached, self.incidents)


@dataclass(frozen=True, slots=True)
class TechnicianWorkload:
    """One row of the technician workload table (§5.3, §9)."""

    technician_id: int
    name: str
    available: bool
    open_count: int
    weighted_load: int
    max_load: int
    resolved: int

    @property
    def capacity_free(self) -> float:
        """How much of the 10-point cap is still free, as a percentage."""
        return _share(max(0, self.max_load - self.weighted_load), self.max_load)

    @property
    def at_capacity(self) -> bool:
        return self.weighted_load >= self.max_load


@dataclass(frozen=True, slots=True)
class SatisfactionStats:
    """The CSAT figure: the average of the ratings reporters gave (§9)."""

    total_rating: int = 0
    responses: int = 0

    @property
    def average(self) -> float | None:
        if self.responses <= 0:
            return None
        return round(self.total_rating / self.responses, 2)


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """One day on the trend chart."""

    day: date
    reported: int
    resolved: int


@dataclass(frozen=True, slots=True)
class Metrics:
    """Every §9 metric in one object, so a dashboard is one call."""

    acknowledgement: DurationStats = field(default_factory=DurationStats)
    resolution: DurationStats = field(default_factory=DurationStats)
    sla_met: int = 0
    sla_measured: int = 0
    satisfaction: SatisfactionStats = field(default_factory=SatisfactionStats)
    reopened: int = 0
    resolved_or_closed: int = 0

    @property
    def mtta(self) -> timedelta | None:
        """Mean time to acknowledge."""
        return self.acknowledgement.mean

    @property
    def mttr(self) -> timedelta | None:
        """Mean time to resolve."""
        return self.resolution.mean

    @property
    def sla_compliance(self) -> float:
        """The share of measured incidents that met their SLA, as a percentage."""
        return _share(self.sla_met, self.sla_measured)

    @property
    def csat(self) -> float | None:
        return self.satisfaction.average

    @property
    def reopen_rate(self) -> float:
        """The share of resolved incidents a reporter sent back."""
        return _share(self.reopened, self.resolved_or_closed)


@dataclass(frozen=True, slots=True)
class Dashboard:
    """What one call to the analytics service returns."""

    overview: Overview
    metrics: Metrics
    workload: tuple[TechnicianWorkload, ...] = field(default_factory=tuple)
    services: tuple[ServiceMetrics, ...] = field(default_factory=tuple)
    trend: tuple[TrendPoint, ...] = field(default_factory=tuple)
