"""The dependency graph and correlation (blueprint §6.2): BFS over depends_on."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import FakeClock
from app.domain.catalogue import ITService
from app.domain.dependency_graph import DependencyGraph, correlate, hint
from app.domain.incident import CancelReason, Incident, IncidentFactory
from app.domain.priority import Priority, PriorityAssessment

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
# The seeded campus, cut down: the Fee Portal sits on the Database and the Identity Provider,
# which both sit on the Network Core; the Exam Portal shares the Database.
NETWORK, DATABASE, IDENTITY, FEES, EXAMS, PRINTING = 1, 2, 3, 4, 5, 6
NAMES = {
    NETWORK: "Campus Network Core",
    DATABASE: "Database Cluster",
    IDENTITY: "Identity Provider",
    FEES: "Fee Payment Portal",
    EXAMS: "Exam Portal",
    PRINTING: "Printing",
}


@pytest.fixture
def graph() -> DependencyGraph:
    return DependencyGraph(
        [
            ITService(NETWORK, NAMES[NETWORK], criticality=3),
            ITService(DATABASE, NAMES[DATABASE], criticality=3, depends_on=(NETWORK,)),
            ITService(IDENTITY, NAMES[IDENTITY], criticality=3, depends_on=(NETWORK,)),
            ITService(FEES, NAMES[FEES], criticality=3, depends_on=(DATABASE, IDENTITY)),
            ITService(EXAMS, NAMES[EXAMS], criticality=3, depends_on=(DATABASE,)),
            ITService(PRINTING, NAMES[PRINTING], criticality=1),
        ]
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


_sequence = iter(range(1, 10_000))


def incident(
    clock: FakeClock, service_id: int, priority: Priority | None = Priority.P1
) -> Incident:
    made = IncidentFactory.create(
        sequence=next(_sequence),
        clock=clock,
        reporter_id=1,
        title=f"Trouble with {NAMES[service_id]}",
        description="It is broken",
        service_id=service_id,
        impact=3,
        urgency=3,
    )
    if priority is not None:
        made.prioritise(PriorityAssessment(priority, None, "test"), clock)
    clock.advance(timedelta(minutes=1))
    return made


def test_upstream_is_breadth_first_with_the_way_there(graph: DependencyGraph) -> None:
    reached = graph.upstream(FEES)
    assert [(r.service_id, r.hops) for r in reached] == [(DATABASE, 1), (IDENTITY, 1), (NETWORK, 2)]
    # The network is reached once, by the first way found, not once per path.
    assert reached[2].path == (FEES, DATABASE, NETWORK)
    assert graph.upstream(PRINTING) == ()
    assert graph.upstream(999) == ()


def test_downstream_walks_the_edges_the_other_way(graph: DependencyGraph) -> None:
    assert [(r.service_id, r.hops) for r in graph.downstream(DATABASE)] == [(FEES, 1), (EXAMS, 1)]
    assert {r.service_id for r in graph.downstream(NETWORK)} == {DATABASE, IDENTITY, FEES, EXAMS}


def test_a_cycle_in_bad_data_cannot_make_the_walk_loop() -> None:
    # A cycle cannot be saved (dependency_cycle); build one behind the editor's back.
    looped = DependencyGraph(
        [
            ITService(1, "A", criticality=1, depends_on=(2,)),
            ITService(2, "B", criticality=1, depends_on=(1,)),
        ]
    )
    assert [r.service_id for r in looped.upstream(1)] == [2]


def test_the_fee_portal_incident_points_at_the_database_outage(
    graph: DependencyGraph, clock: FakeClock
) -> None:
    """§6.2's own example: "likely related to INC-0040 (Database), possible root cause"."""
    database = incident(clock, DATABASE, Priority.P1)
    fees = incident(clock, FEES, Priority.P2)
    report = correlate(fees, graph, [database, fees])
    assert report.likely_root_cause is not None
    assert report.likely_root_cause.incident is database
    assert hint(report, NAMES) == (
        f"Likely related to {database.id} (Database Cluster): possible root cause."
    )
    # ...and from the database's side, the fee portal is what it may be causing.
    reverse = correlate(database, graph, [database, fees])
    assert [c.incident.id for c in reverse.impacted] == [fees.id]
    assert reverse.root_causes == ()


def test_a_transitive_cause_says_which_way_it_runs(
    graph: DependencyGraph, clock: FakeClock
) -> None:
    network = incident(clock, NETWORK, Priority.P2)
    fees = incident(clock, FEES, Priority.P3)
    report = correlate(fees, graph, [network])
    assert report.likely_root_cause is not None
    assert report.likely_root_cause.reach.hops == 2
    assert hint(report, NAMES) == (
        f"Likely related to {network.id} (Campus Network Core, through Database Cluster): "
        "possible root cause."
    )


def test_the_nearest_then_the_most_urgent_cause_comes_first(
    graph: DependencyGraph, clock: FakeClock
) -> None:
    network = incident(clock, NETWORK, Priority.P1)
    identity_p2 = incident(clock, IDENTITY, Priority.P2)
    database_p1 = incident(clock, DATABASE, Priority.P1)
    fees = incident(clock, FEES)
    causes = correlate(fees, graph, [network, identity_p2, database_p1]).root_causes
    assert [c.incident.id for c in causes] == [database_p1.id, identity_p2.id, network.id]


def test_no_hint_from_minor_unrelated_or_finished_incidents(
    graph: DependencyGraph, clock: FakeClock
) -> None:
    fees = incident(clock, FEES)
    minor = incident(clock, DATABASE, Priority.P3)
    unrelated = incident(clock, PRINTING, Priority.P1)
    exams = incident(clock, EXAMS, Priority.P1)  # a sibling, not something fees depends on
    same_service = incident(clock, FEES, Priority.P1)  # the duplicate check's business
    cancelled = incident(clock, DATABASE, Priority.P1)
    cancelled.cancel(1, clock, CancelReason.WITHDRAWN)
    resolved = incident(clock, DATABASE, Priority.P1)
    resolved.classify(1, None, clock)
    resolved.assign(9, None, clock)
    resolved.acknowledge(9, clock)
    resolved.start(9, clock)
    resolved.resolve(9, clock, "Restarted the primary")
    unprioritised = incident(clock, DATABASE, None)

    report = correlate(
        fees,
        graph,
        [fees, minor, unrelated, exams, same_service, cancelled, resolved, unprioritised],
    )
    assert report.root_causes == ()
    assert hint(report, NAMES) is None
