"""Search and analytics must give the same answers in memory and in SQL (blueprint §9).

Both implementations are built from the same fixture, so every filter, every page boundary and
every dashboard figure is checked twice. A disagreement between walking Python objects and
running SQL is exactly the kind of bug that would otherwise reach the demo.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from app.core.clock import FakeClock
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.incident import Incident, IncidentFactory
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.repositories import UnitOfWork
from app.domain.search import DEFAULT_PAGE_SIZE, IncidentQuery, SortField
from app.domain.sla import SLAStatus, SLATarget, default_policies
from app.domain.states import IncidentStatus as S
from app.domain.users import UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.database import make_engine
from app.repositories.memory import InMemoryUnitOfWork
from app.repositories.sqlalchemy.models import Base
from app.repositories.sqlalchemy.repos import (
    SqlAlchemyUnitOfWork,
    create_schema,
    make_session_factory,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
TARGET = SLATarget(timedelta(minutes=15), timedelta(hours=4))
REPORTER, OTHER, TECH, TECH2, LEAD, ADMIN = 1, 2, 3, 4, 5, 6
WIFI, PORTAL = 1, 2
NETWORK, PAYMENTS = 1, 2


@pytest.fixture(params=["memory", "sqlalchemy"])
def uow(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[UnitOfWork]:
    if request.param == "memory":
        unit: UnitOfWork = InMemoryUnitOfWork()
        _populate(unit)
        yield unit
        return

    url = os.environ.get("TEST_DATABASE_URL") or (
        f"sqlite:///{tmp_path_factory.mktemp('search') / 'search.db'}"
    )
    engine: Engine = make_engine(url)
    Base.metadata.drop_all(engine)
    create_schema(engine)
    unit = SqlAlchemyUnitOfWork(make_session_factory(engine), FakeClock(NOW))
    _populate(unit)
    unit.commit()
    yield unit
    unit.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _populate(uow: UnitOfWork) -> None:
    uow.catalogue.save_skill(Skill(1, "networking"))
    uow.catalogue.save_category(Category(NETWORK, "Network", keywords=("wifi",)))
    uow.catalogue.save_category(Category(PAYMENTS, "Payments", keywords=("payment",)))
    uow.catalogue.save_service(ITService(WIFI, "Campus Wi-Fi", criticality=2))
    uow.catalogue.save_service(ITService(PORTAL, "Fee Payment Portal", criticality=3))
    uow.catalogue.save_policies(default_policies())
    uow.catalogue.save_team(Team(1, "Network Operations"))
    for user_id, role, name in (
        (REPORTER, Role.EMPLOYEE, "Devika Rao"),
        (OTHER, Role.EMPLOYEE, "Other Person"),
        (TECH, Role.TECHNICIAN, "Arjun Menon"),
        (TECH2, Role.TECHNICIAN, "Tara Sheikh"),
        (LEAD, Role.TEAM_LEAD, "Priya Nair"),
        (ADMIN, Role.ADMINISTRATOR, "Rahul Verma"),
    ):
        support = UserFactory.is_support_role(role)
        uow.users.add(
            UserFactory.create(
                role,
                user_id=user_id,
                email=f"u{user_id}@campus.edu",
                full_name=name,
                skills=SkillSet({"networking"}) if support else None,
                experience_level=2 if support else None,
                team_id=1 if support else None,
            )
        )
    team = uow.catalogue.get_team(1)
    for member in (TECH, TECH2, LEAD):
        team.add_member(member)
    team.set_lead(LEAD)
    uow.catalogue.save_team(team)
    _incidents(uow)


def _make(
    uow: UnitOfWork,
    *,
    sequence: int,
    created_at: datetime,
    reporter_id: int,
    service_id: int,
    title: str,
    description: str,
    impact: int = 2,
    urgency: int = 2,
) -> Incident:
    clock = FakeClock(created_at)
    incident = IncidentFactory.create(
        sequence=sequence,
        clock=clock,
        reporter_id=reporter_id,
        title=title,
        description=description,
        service_id=service_id,
        impact=impact,
        urgency=urgency,
    )
    uow.incidents.add(incident)
    return incident


def _incidents(uow: UnitOfWork) -> None:
    """Nine incidents, each in one clear state, so every filter has an unambiguous answer.

    1 NEW, never touched           2 ACKNOWLEDGED, on track
    3 ACKNOWLEDGED, at risk        4 ACKNOWLEDGED, resolution breached
    5 ACKNOWLEDGED too late        6 IN_PROGRESS, on track
    7 ON_HOLD, clock paused        8 RESOLVED inside its target
    9 CLOSED after one rejection
    """
    # 1: untouched, reported five minutes ago, so it has no SLA clock at all yet
    _make(
        uow,
        sequence=1,
        created_at=NOW - timedelta(minutes=5),
        reporter_id=REPORTER,
        service_id=WIFI,
        title="Wi-Fi down in the library",
        description="No wifi signal at all",
    )

    # 2: acknowledged promptly, plenty of time left on the resolution clock
    _worked(
        uow,
        sequence=2,
        created_at=NOW - timedelta(minutes=20),
        reporter_id=REPORTER,
        service_id=WIFI,
        title="Wi-Fi slow in the hostel",
        description="The wifi is slow this evening",
        technician=TECH,
        priority=Priority.P3,
    )

    # 3: acknowledged promptly, now three-quarters of the way to its deadline
    _worked(
        uow,
        sequence=3,
        created_at=NOW - timedelta(hours=3, minutes=10),
        reporter_id=OTHER,
        service_id=PORTAL,
        title="Payment portal is slow",
        description="A payment takes a minute to go through",
        technician=TECH,
        priority=Priority.P2,
    )

    # 4: acknowledged promptly, but past its four-hour resolution deadline
    _worked(
        uow,
        sequence=4,
        created_at=NOW - timedelta(hours=6),
        reporter_id=OTHER,
        service_id=PORTAL,
        title="Payment portal rejects cards",
        description="Every payment is rejected",
        technician=TECH2,
        priority=Priority.P1,
    )

    # 5: acknowledged forty minutes late, so its response SLA is breached for good
    _worked(
        uow,
        sequence=5,
        created_at=NOW - timedelta(hours=2),
        reporter_id=REPORTER,
        service_id=WIFI,
        title="Printer offline",
        description="The printer in the lab is offline",
        technician=TECH,
        priority=Priority.P3,
        acknowledge_after=timedelta(minutes=40),
    )

    # 6: being worked on, on track
    sixth = _worked(
        uow,
        sequence=6,
        created_at=NOW - timedelta(hours=1),
        reporter_id=REPORTER,
        service_id=WIFI,
        title="Projector will not turn on",
        description="No picture in the lecture theatre",
        technician=TECH,
        priority=Priority.P4,
    )
    clock = FakeClock(NOW - timedelta(hours=1) + timedelta(minutes=3))
    sixth.start(TECH, clock)
    uow.incidents.save(sixth)

    # 7: waiting for the reporter, so its resolution clock is paused (BR-07)
    seventh = _worked(
        uow,
        sequence=7,
        created_at=NOW - timedelta(hours=5),
        reporter_id=OTHER,
        service_id=WIFI,
        title="Cannot log in to the portal",
        description="My password does not work",
        technician=TECH2,
        priority=Priority.P3,
    )
    clock = FakeClock(NOW - timedelta(hours=5) + timedelta(minutes=3))
    seventh.start(TECH2, clock)
    seventh.hold(TECH2, clock, "Which account are you using?")
    uow.incidents.save(seventh)

    # 8: resolved inside its target, waiting for the reporter to confirm
    eighth = _worked(
        uow,
        sequence=8,
        created_at=NOW - timedelta(days=2),
        reporter_id=REPORTER,
        service_id=PORTAL,
        title="Receipt never arrived",
        description="A payment went through with no receipt",
        technician=TECH,
        priority=Priority.P3,
    )
    clock = FakeClock(NOW - timedelta(days=2) + timedelta(minutes=3))
    eighth.start(TECH, clock)
    clock.advance(timedelta(hours=1))
    eighth.resolve(TECH, clock, "Re-sent the receipt")
    uow.incidents.save(eighth)

    # 9: resolved, rejected once, fixed again, verified and closed
    ninth = _worked(
        uow,
        sequence=9,
        created_at=NOW - timedelta(days=5),
        reporter_id=OTHER,
        service_id=WIFI,
        title="Wi-Fi drops in the canteen",
        description="The wifi keeps dropping at lunchtime",
        technician=TECH2,
        priority=Priority.P2,
    )
    clock = FakeClock(NOW - timedelta(days=5) + timedelta(minutes=3))
    ninth.start(TECH2, clock)
    clock.advance(timedelta(hours=2))
    ninth.resolve(TECH2, clock, "Moved the access point")
    clock.advance(timedelta(hours=3))
    ninth.reject(OTHER, clock, "It came back")
    clock.advance(timedelta(hours=2))
    ninth.resolve(TECH2, clock, "Replaced the access point")
    clock.advance(timedelta(hours=1))
    ninth.verify(OTHER, clock, rating=4, comment="Thanks")
    ninth.close(TECH2, clock)
    uow.incidents.save(ninth)


def _worked(
    uow: UnitOfWork,
    *,
    sequence: int,
    created_at: datetime,
    reporter_id: int,
    service_id: int,
    title: str,
    description: str,
    technician: int,
    priority: Priority,
    acknowledge_after: timedelta = timedelta(minutes=2),
) -> Incident:
    """Report, prioritise, set the SLA, classify, assign and acknowledge, as the facade would."""
    incident = _make(
        uow,
        sequence=sequence,
        created_at=created_at,
        reporter_id=reporter_id,
        service_id=service_id,
        title=title,
        description=description,
    )
    _open(uow, incident, created_at, technician, priority)
    clock = FakeClock(created_at + acknowledge_after)
    incident.acknowledge(technician, clock)
    uow.incidents.save(incident)
    return incident


def _open(
    uow: UnitOfWork, incident: Incident, created_at: datetime, technician: int, priority: Priority
) -> None:
    """Classify, prioritise, set the SLA clock and assign, as the facade would."""
    from app.domain.priority import PriorityAssessment

    clock = FakeClock(created_at)
    category = NETWORK if incident.service_id == WIFI else PAYMENTS
    incident.prioritise(PriorityAssessment(priority, None, "fixture"), clock)
    incident.apply_sla(TARGET)
    incident.classify(category, None, clock)
    incident.assign(technician, None, clock)
    uow.incidents.save(incident)


def ids(uow: UnitOfWork, query: IncidentQuery) -> list[str]:
    return [i.id for i in uow.incidents.search(query, NOW).items]


ALL = [f"INC-2026-{n:04d}" for n in range(1, 10)]


# ---------------------------------------------------------------- the nine filters
def test_an_empty_query_lists_everything_newest_first(uow: UnitOfWork) -> None:
    page = uow.incidents.search(IncidentQuery(), NOW)
    assert page.total == 9
    assert len(page.items) == 9
    assert [i.id for i in page.items] == ALL[:1] + list(reversed(ALL[1:]))[:0] + [
        "INC-2026-0002",
        "INC-2026-0006",
        "INC-2026-0005",
        "INC-2026-0003",
        "INC-2026-0007",
        "INC-2026-0004",
        "INC-2026-0008",
        "INC-2026-0009",
    ]
    assert IncidentQuery().is_filtered is False


def test_filter_by_id_matches_part_of_it(uow: UnitOfWork) -> None:
    assert ids(uow, IncidentQuery(incident_id="INC-2026-0004")) == ["INC-2026-0004"]
    assert sorted(ids(uow, IncidentQuery(incident_id="0004"))) == ["INC-2026-0004"]
    assert ids(uow, IncidentQuery(incident_id="INC-2027")) == []


def test_filter_by_date_range(uow: UnitOfWork) -> None:
    recent = IncidentQuery(created_from=NOW - timedelta(hours=7))
    assert sorted(ids(uow, recent)) == sorted(ALL[:7])

    old = IncidentQuery(created_to=NOW - timedelta(days=1))
    assert sorted(ids(uow, old)) == ["INC-2026-0008", "INC-2026-0009"]

    both = IncidentQuery(created_from=NOW - timedelta(days=3), created_to=NOW - timedelta(days=1))
    assert ids(uow, both) == ["INC-2026-0008"]


def test_filter_by_status_and_priority(uow: UnitOfWork) -> None:
    assert ids(uow, IncidentQuery(statuses=(S.NEW,))) == ["INC-2026-0001"]
    assert sorted(ids(uow, IncidentQuery(statuses=(S.RESOLVED, S.CLOSED)))) == [
        "INC-2026-0008",
        "INC-2026-0009",
    ]
    assert sorted(ids(uow, IncidentQuery(priorities=(Priority.P1, Priority.P2)))) == [
        "INC-2026-0003",
        "INC-2026-0004",
        "INC-2026-0009",
    ]


def test_filter_by_category_service_assignee_and_reporter(uow: UnitOfWork) -> None:
    assert sorted(ids(uow, IncidentQuery(category_ids=(PAYMENTS,)))) == [
        "INC-2026-0003",
        "INC-2026-0004",
        "INC-2026-0008",
    ]
    assert sorted(ids(uow, IncidentQuery(service_ids=(PORTAL,)))) == [
        "INC-2026-0003",
        "INC-2026-0004",
        "INC-2026-0008",
    ]
    assert sorted(ids(uow, IncidentQuery(assignee_ids=(TECH2,)))) == [
        "INC-2026-0004",
        "INC-2026-0007",
        "INC-2026-0009",
    ]
    assert sorted(ids(uow, IncidentQuery(reporter_ids=(OTHER,)))) == [
        "INC-2026-0003",
        "INC-2026-0004",
        "INC-2026-0007",
        "INC-2026-0009",
    ]


def test_filter_by_sla_status(uow: UnitOfWork) -> None:
    """The ninth filter: the SLA state computed from the clock (§5.2)."""
    breached = ids(uow, IncidentQuery(sla_statuses=(SLAStatus.BREACHED,)))
    assert "INC-2026-0004" in breached  # past its resolution deadline
    assert "INC-2026-0005" in breached  # acknowledged too late
    assert "INC-2026-0002" not in breached

    at_risk = ids(uow, IncidentQuery(sla_statuses=(SLAStatus.AT_RISK,)))
    assert "INC-2026-0003" in at_risk
    assert "INC-2026-0004" not in at_risk

    on_track = ids(uow, IncidentQuery(sla_statuses=(SLAStatus.ON_TRACK,)))
    assert "INC-2026-0002" in on_track
    assert "INC-2026-0004" not in on_track
    # A paused incident counts as on track: BR-07 stops its clock, so time cannot carry it
    # into a breach while it waits for the reporter.
    assert "INC-2026-0007" in on_track

    # An incident without a clock yet is in none of the three.
    assert "INC-2026-0001" not in breached + at_risk + on_track
    # The three states are exclusive, and together they cover everything with a clock.
    assert set(breached) & set(at_risk) == set()
    assert set(breached) & set(on_track) == set()
    assert set(at_risk) & set(on_track) == set()
    assert sorted(breached + at_risk + on_track) == ALL[1:]


def test_free_text_searches_the_id_the_title_and_the_description(uow: UnitOfWork) -> None:
    assert sorted(ids(uow, IncidentQuery(text="wifi"))) == [
        "INC-2026-0001",
        "INC-2026-0002",
        "INC-2026-0009",
    ]
    assert sorted(ids(uow, IncidentQuery(text="PAYMENT"))) == [
        "INC-2026-0003",
        "INC-2026-0004",
        "INC-2026-0008",
    ]
    assert ids(uow, IncidentQuery(text="0006")) == ["INC-2026-0006"]
    assert ids(uow, IncidentQuery(text="nothing matches this")) == []


def test_filters_combine(uow: UnitOfWork) -> None:
    combined = IncidentQuery(
        text="payment",
        service_ids=(PORTAL,),
        statuses=(S.ACKNOWLEDGED,),
        priorities=(Priority.P1,),
        reporter_ids=(OTHER,),
    )
    assert ids(uow, combined) == ["INC-2026-0004"]
    assert combined.is_filtered is True

    # One filter that excludes everything else wins.
    assert ids(uow, IncidentQuery(text="payment", service_ids=(WIFI,))) == []


# ---------------------------------------------------------------- paging and sorting
def test_paging_walks_the_whole_list_without_repeating(uow: UnitOfWork) -> None:
    seen: list[str] = []
    offset = 0
    while True:
        page = uow.incidents.search(IncidentQuery(offset=offset, limit=4), NOW)
        assert page.total == 9
        assert page.limit == 4
        seen.extend(i.id for i in page.items)
        if not page.has_more:
            break
        offset += 4
    assert sorted(seen) == ALL
    assert len(seen) == len(set(seen))


def test_page_boundaries(uow: UnitOfWork) -> None:
    first = uow.incidents.search(IncidentQuery(limit=4), NOW)
    assert (first.page_number, first.page_count, first.has_more) == (1, 3, True)

    last = uow.incidents.search(IncidentQuery(offset=8, limit=4), NOW)
    assert len(last.items) == 1
    assert last.has_more is False

    past_the_end = uow.incidents.search(IncidentQuery(offset=50, limit=4), NOW)
    assert past_the_end.items == ()
    assert past_the_end.total == 9
    assert past_the_end.has_more is False


def test_the_default_page_size_is_the_documented_one(uow: UnitOfWork) -> None:
    assert uow.incidents.search(IncidentQuery(), NOW).limit == DEFAULT_PAGE_SIZE


def test_sorting_by_each_column(uow: UnitOfWork) -> None:
    by_id = ids(uow, IncidentQuery(sort_by=SortField.ID, descending=False))
    assert by_id == ALL

    by_priority = uow.incidents.search(
        IncidentQuery(sort_by=SortField.PRIORITY, descending=False, limit=3), NOW
    )
    assert by_priority.items[0].priority is Priority.P1

    by_created = ids(uow, IncidentQuery(sort_by=SortField.CREATED_AT, descending=False, limit=1))
    assert by_created == ["INC-2026-0009"]  # the oldest


# ---------------------------------------------------------------- the dashboards (§9)
def test_the_overview_counts_every_card(uow: UnitOfWork) -> None:
    overview = uow.analytics.overview(NOW)
    assert overview.total == 9
    assert overview.open_count == 6  # assigned, acknowledged, in progress, on hold
    assert overview.unassigned == 1  # the untouched one
    assert overview.awaiting_reporter == 1  # resolved, not yet verified
    assert overview.critical_open == 1  # the P1
    assert overview.resolved_in_window == 2
    assert overview.breached >= 2
    assert overview.at_risk >= 1
    assert overview.open_share > 0


def test_the_metrics_are_the_five_figures_of_the_blueprint(uow: UnitOfWork) -> None:
    metrics = uow.analytics.metrics()
    assert metrics.mtta is not None
    assert metrics.mttr is not None
    assert metrics.acknowledgement.count == 8  # every incident but the untouched one
    assert metrics.resolution.count == 2
    assert metrics.csat == 4.0  # one rating of 4
    assert metrics.reopened == 1
    assert metrics.resolved_or_closed == 2
    assert metrics.reopen_rate == 50.0
    assert 0 <= metrics.sla_compliance <= 100


def test_the_window_narrows_the_metrics(uow: UnitOfWork) -> None:
    recent = uow.analytics.metrics(since=NOW - timedelta(hours=12))
    assert recent.resolution.count == 0  # both resolutions are older than twelve hours
    assert recent.csat is None
    assert recent.reopened == 0


def test_the_workload_table_has_a_row_per_technician(uow: UnitOfWork) -> None:
    rows = uow.analytics.workload()
    assert [row.technician_id for row in rows] == [TECH, TECH2, LEAD]
    by_id = {row.technician_id: row for row in rows}
    assert by_id[TECH].open_count == 4  # 2, 3, 5 and 6
    assert by_id[TECH2].open_count == 2  # 4 and 7
    assert by_id[LEAD].open_count == 0
    assert by_id[TECH].weighted_load > 0
    assert by_id[TECH].resolved == 1
    assert by_id[TECH2].resolved == 1
    assert by_id[LEAD].capacity_free == 100.0
    assert by_id[TECH].max_load == 10


def test_the_service_analysis_has_a_row_per_service(uow: UnitOfWork) -> None:
    rows = uow.analytics.by_service(NOW)
    assert [row.service_id for row in rows] == [WIFI, PORTAL]
    by_id = {row.service_id: row for row in rows}
    assert by_id[WIFI].incidents == 6
    assert by_id[PORTAL].incidents == 3
    assert by_id[WIFI].name == "Campus Wi-Fi"
    assert by_id[PORTAL].resolution.count == 1
    assert 0 <= by_id[WIFI].breach_share <= 100

    # The service table and the overview card must agree about what a breach is.
    overview = uow.analytics.overview(NOW)
    assert sum(row.breached for row in rows) >= overview.breached


def test_the_trend_has_one_point_per_day_with_something_on_it(uow: UnitOfWork) -> None:
    points = uow.analytics.trend(NOW - timedelta(days=7), NOW)
    assert points
    assert [point.day for point in points] == sorted(point.day for point in points)
    assert sum(point.reported for point in points) == 9
    assert sum(point.resolved for point in points) == 2

    narrow = uow.analytics.trend(NOW - timedelta(hours=2), NOW)
    assert sum(point.reported for point in narrow) == 4  # 1, 2, 5 and 6


def test_an_unacknowledged_incident_is_at_risk_on_its_response_clock(uow: UnitOfWork) -> None:
    """The status is the worse of the two clocks, so a late acknowledgement shows up too."""
    created = NOW - timedelta(minutes=12)  # 80 % of the 15-minute response target
    _make(
        uow,
        sequence=10,
        created_at=created,
        reporter_id=REPORTER,
        service_id=WIFI,
        title="Laptop will not charge",
        description="The dock does nothing",
    )
    waiting = uow.incidents.get("INC-2026-0010")
    _open(uow, waiting, created, TECH, Priority.P3)  # assigned, never acknowledged

    at_risk = ids(uow, IncidentQuery(sla_statuses=(SLAStatus.AT_RISK,)))
    assert "INC-2026-0010" in at_risk
    assert "INC-2026-0010" not in ids(uow, IncidentQuery(sla_statuses=(SLAStatus.ON_TRACK,)))
    assert "INC-2026-0010" in [i.id for i in uow.incidents.needing_sla_attention(NOW)]

    stored = uow.incidents.get("INC-2026-0010")
    assert stored.sla_clock is not None
    assert stored.sla_clock.response_status(NOW) is SLAStatus.AT_RISK


def test_lowering_the_priority_after_a_breach_does_not_unbreach_it(uow: UnitOfWork) -> None:
    """D-017 and D-018 together: the frozen target wins, in the domain *and* in the search.

    An incident resolved past its deadline has breached. Re-prioritising it afterwards —
    RESOLVED is not terminal, so the API allows it — must not rewrite that, and the stored
    deadline the SQL filter compares against must agree with the aggregate.
    """
    created = NOW - timedelta(hours=10)
    _make(
        uow,
        sequence=11,
        created_at=created,
        reporter_id=REPORTER,
        service_id=PORTAL,
        title="Payment portal was down for hours",
        description="Took far too long to fix",
    )
    late = uow.incidents.get("INC-2026-0011")
    _open(uow, late, created, TECH, Priority.P2)
    clock = FakeClock(created + timedelta(minutes=2))
    late.acknowledge(TECH, clock)
    late.start(TECH, clock)
    clock.advance(timedelta(hours=9))  # the target is four hours
    late.resolve(TECH, clock, "Restarted the gateway")
    uow.incidents.save(late)

    assert late.sla_clock is not None
    assert late.sla_clock.resolution_status(NOW) is SLAStatus.BREACHED
    assert "INC-2026-0011" in ids(uow, IncidentQuery(sla_statuses=(SLAStatus.BREACHED,)))

    # Now lower the priority, which retargets the clock to a far longer target.
    stored = uow.incidents.get("INC-2026-0011")
    stored.override_priority(Priority.P4, "Not as urgent as first thought", ADMIN, FakeClock(NOW))
    target, _ = uow.catalogue.policy_book().target_or_default(
        uow.catalogue.get_service(PORTAL).sla_tier, Priority.P4
    )
    stored.apply_sla(target)
    uow.incidents.save(stored)

    reloaded = uow.incidents.get("INC-2026-0011")
    assert reloaded.sla_clock is not None
    assert reloaded.sla_clock.resolution_status(NOW) is SLAStatus.BREACHED
    assert "INC-2026-0011" in ids(uow, IncidentQuery(sla_statuses=(SLAStatus.BREACHED,)))
    assert "INC-2026-0011" not in ids(uow, IncidentQuery(sla_statuses=(SLAStatus.ON_TRACK,)))
    # The stored at-risk moment must stay before the stored deadline, or neither means anything.
    assert reloaded.sla_clock.risk_at() < reloaded.sla_clock.resolution_deadline_at_rest
