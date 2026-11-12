"""The service dependency graph and incident correlation (blueprint §6.2).

An outage in a shared service shows up as incidents on everything built on it: the Fee Payment
Portal fails because the Database Cluster does. A breadth-first search over ``depends_on``
finds, for an incident, the open P1 and P2 incidents on the services it depends on — directly
or through others — and names the nearest one as the possible root cause. The same walk the
other way finds the incidents a failing service may be causing.

Pure: the caller hands in the services and the open incidents; nothing here reads a database.
"""

from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.domain.catalogue import ITService
from app.domain.incident import Incident
from app.domain.priority import Priority
from app.domain.states import IncidentStatus

#: §6.2: only a serious, still-open incident is worth suggesting as a root cause.
ROOT_CAUSE_PRIORITIES = frozenset({Priority.P1, Priority.P2})
#: Somebody is still dealing with it; RESOLVED is excluded because a fix has been applied.
LIVE_STATUSES = frozenset(
    {
        IncidentStatus.NEW,
        IncidentStatus.CLASSIFIED,
        IncidentStatus.ASSIGNED,
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.IN_PROGRESS,
        IncidentStatus.ON_HOLD,
    }
)


@dataclass(frozen=True, slots=True)
class Reach:
    """A service found by the walk, how far away it is and the way there."""

    service_id: int
    hops: int
    #: Service ids from the start to this one, both ends included.
    path: tuple[int, ...]


class DependencyGraph:
    """``depends_on`` edges between services, walked breadth first in either direction.

    The graph is kept acyclic when services are edited (``dependency_cycle``); the walk still
    remembers what it has seen, so a bad row can never make it loop.
    """

    def __init__(self, services: Iterable[ITService]) -> None:
        self.__depends_on: dict[int, tuple[int, ...]] = {}
        dependants: dict[int, list[int]] = {}
        for service in services:
            self.__depends_on[service.id] = service.depends_on
            for dependency in service.depends_on:
                dependants.setdefault(dependency, []).append(service.id)
        self.__dependants = {key: tuple(sorted(value)) for key, value in dependants.items()}

    def upstream(self, service_id: int) -> tuple[Reach, ...]:
        """Everything ``service_id`` depends on, directly or not, nearest first."""
        return self.__walk(service_id, self.__depends_on)

    def downstream(self, service_id: int) -> tuple[Reach, ...]:
        """Everything that depends on ``service_id``, directly or not, nearest first."""
        return self.__walk(service_id, self.__dependants)

    @staticmethod
    def __walk(start: int, edges: Mapping[int, Sequence[int]]) -> tuple[Reach, ...]:
        found: list[Reach] = []
        seen = {start}
        queue: deque[tuple[int, tuple[int, ...]]] = deque([(start, (start,))])
        while queue:
            current, path = queue.popleft()
            for following in sorted(edges.get(current, ())):
                if following in seen:
                    continue
                seen.add(following)
                route = (*path, following)
                found.append(Reach(following, len(route) - 1, route))
                queue.append((following, route))
        return tuple(found)


@dataclass(frozen=True, slots=True)
class Correlation:
    """One open incident related to another through the dependency graph."""

    incident: Incident
    reach: Reach

    @property
    def same_service(self) -> bool:
        return self.reach.hops == 0


@dataclass(frozen=True, slots=True)
class CorrelationReport:
    """What the graph says about one incident (§6.2)."""

    #: Open P1/P2 incidents on services this one depends on: nearest, most urgent, then
    #: closest in time first.
    root_causes: tuple[Correlation, ...]
    #: Open incidents on services that depend on this one's service.
    impacted: tuple[Correlation, ...]

    @property
    def likely_root_cause(self) -> Correlation | None:
        return self.root_causes[0] if self.root_causes else None


def _is_live(incident: Incident) -> bool:
    return incident.status in LIVE_STATUSES


def _ordering(incident: Incident) -> Callable[[Correlation], tuple[int, int, float, str]]:
    """Nearest in the graph, then most urgent, then reported closest in time to ``incident``.

    Closeness in time breaks the tie because an outage reported minutes before is far more
    likely to be the cause than one that has been open for days (§6.2 weighs time for
    duplicates for the same reason).
    """

    def key(correlation: Correlation) -> tuple[int, int, float, str]:
        other = correlation.incident
        rank = other.priority.rank if other.priority is not None else len(Priority) + 1
        gap = abs((other.created_at - incident.created_at).total_seconds())
        return (correlation.reach.hops, rank, gap, other.id)

    return key


def correlate(
    incident: Incident, graph: DependencyGraph, open_incidents: Iterable[Incident]
) -> CorrelationReport:
    """§6.2's correlation for ``incident``, from the incidents still open elsewhere.

    A root cause is a live P1 or P2 incident on a service ``incident``'s service depends on.
    The impacted are live incidents of any priority on services that depend on it — the ones
    this incident may be causing. Nothing is related to itself or to another incident on the
    very same service: that is the duplicate check's job.
    """
    upstream = {reach.service_id: reach for reach in graph.upstream(incident.service_id)}
    downstream = {reach.service_id: reach for reach in graph.downstream(incident.service_id)}
    causes: list[Correlation] = []
    impacted: list[Correlation] = []
    for other in open_incidents:
        if other.id == incident.id or not _is_live(other):
            continue
        if other.service_id in upstream and other.priority in ROOT_CAUSE_PRIORITIES:
            causes.append(Correlation(other, upstream[other.service_id]))
        elif other.service_id in downstream:
            impacted.append(Correlation(other, downstream[other.service_id]))
    causes.sort(key=_ordering(incident))
    impacted.sort(key=_ordering(incident))
    return CorrelationReport(tuple(causes), tuple(impacted))


def hint(report: CorrelationReport, service_names: Mapping[int, str]) -> str | None:
    """The plain-words hint of §6.2, e.g. "Likely related to INC-0040 (Database Cluster)"."""
    cause = report.likely_root_cause
    if cause is None:
        return None
    name = service_names.get(cause.incident.service_id, f"service {cause.incident.service_id}")
    via = ""
    if cause.reach.hops > 1:
        middle = [service_names.get(s, str(s)) for s in cause.reach.path[1:-1]]
        via = f", through {' and '.join(middle)}"
    return f"Likely related to {cause.incident.id} ({name}{via}): possible root cause."
