"""The dashboard arithmetic (blueprint §9), including every empty case."""

from datetime import date, timedelta

from app.domain.analytics import (
    DurationStats,
    Metrics,
    Overview,
    SatisfactionStats,
    ServiceMetrics,
    TechnicianWorkload,
    TrendPoint,
)


def test_an_empty_system_reports_no_averages_rather_than_zero() -> None:
    """A fresh install must not claim an MTTR of zero hours or a CSAT of 0/5."""
    empty = Metrics()
    assert empty.mtta is None
    assert empty.mttr is None
    assert empty.csat is None
    assert empty.sla_compliance == 0.0
    assert empty.reopen_rate == 0.0


def test_the_means_are_the_total_over_the_count() -> None:
    metrics = Metrics(
        acknowledgement=DurationStats(timedelta(minutes=30), 3),
        resolution=DurationStats(timedelta(hours=9), 4),
    )
    assert metrics.mtta == timedelta(minutes=10)
    assert metrics.mttr == timedelta(hours=2, minutes=15)
    assert metrics.resolution.mean_hours == 2.25


def test_sla_compliance_and_the_reopen_rate_are_percentages() -> None:
    metrics = Metrics(sla_met=37, sla_measured=40, reopened=3, resolved_or_closed=24)
    assert metrics.sla_compliance == 92.5
    assert metrics.reopen_rate == 12.5


def test_csat_averages_the_ratings_people_gave() -> None:
    assert Metrics(satisfaction=SatisfactionStats(total_rating=22, responses=5)).csat == 4.4
    assert SatisfactionStats().average is None


def test_the_overview_shares_cope_with_an_empty_window() -> None:
    assert Overview(0, 0, 0, 0, 0, 0, 0, 0).open_share == 0.0
    busy = Overview(
        total=200,
        open_count=50,
        unassigned=4,
        awaiting_reporter=6,
        breached=10,
        at_risk=8,
        critical_open=2,
        resolved_in_window=120,
    )
    assert busy.open_share == 25.0
    assert busy.breached_share == 5.0


def test_a_technicians_free_capacity_is_what_is_left_of_the_cap() -> None:
    """§5.3: the cap is 10 points, and the UI shows how much is free."""
    half = TechnicianWorkload(1, "Arjun Menon", True, 3, 5, 10, 40)
    assert half.capacity_free == 50.0
    assert half.at_capacity is False

    full = TechnicianWorkload(2, "Priya Nair", True, 4, 10, 10, 90)
    assert full.capacity_free == 0.0
    assert full.at_capacity is True

    over = TechnicianWorkload(3, "Someone", False, 5, 12, 10, 1)
    assert over.capacity_free == 0.0  # never negative
    assert over.at_capacity is True


def test_a_services_breach_share_and_its_mttr() -> None:
    service = ServiceMetrics(
        service_id=1,
        name="Fee Payment Portal",
        incidents=40,
        breached=6,
        resolution=DurationStats(timedelta(hours=20), 10),
    )
    assert service.breach_share == 15.0
    assert service.resolution.mean_hours == 2.0

    quiet = ServiceMetrics(service_id=2, name="Printing", incidents=0, breached=0)
    assert quiet.breach_share == 0.0
    assert quiet.resolution.mean is None


def test_a_trend_point_keeps_both_series() -> None:
    point = TrendPoint(date(2026, 11, 6), reported=12, resolved=9)
    assert (point.reported, point.resolved) == (12, 9)
    assert point.day.isoformat() == "2026-11-06"
