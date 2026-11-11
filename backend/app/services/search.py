"""Searching and exporting incidents (blueprint §9).

The service's job is the part a repository must not decide: what the *caller* is allowed to
see. BR-01 is applied by narrowing the query before it runs — an employee's search is rewritten
to their own incidents — so no filter combination can be used to enumerate other people's.
"""

from collections.abc import Sequence
from datetime import datetime

from app.core.clock import Clock, in_ist
from app.domain.errors import NotFoundError
from app.domain.incident import Incident
from app.domain.permissions import Permission
from app.domain.repositories import UnitOfWork
from app.domain.search import IncidentQuery, Page, csv_rows
from app.domain.sla import SLAStatus
from app.domain.users import Technician, User

CSV_HEADER: tuple[str, ...] = (
    "ID",
    "Title",
    "Status",
    "Priority",
    "Service",
    "Category",
    "Reporter",
    "Assignee",
    "Created (IST)",
    "Acknowledged (IST)",
    "Resolved (IST)",
    "SLA",
    "Reopened",
)
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


class SearchService:
    """One search, scoped to whoever is asking."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self.__uow = uow
        self.__clock = clock

    def search(self, actor: User, query: IncidentQuery) -> Page[Incident]:
        """One page of the incidents ``actor`` may see that match ``query``."""
        return self.__uow.incidents.search(self.scoped(actor, query), self.__clock.now())

    def scoped(self, actor: User, query: IncidentQuery) -> IncidentQuery:
        """Narrow ``query`` to what ``actor`` may see (BR-01).

        An admin searches everything. A Team Lead searches their own team, narrowed to whoever
        of it they asked about. A technician always searches their own queue: asking about a
        colleague gives you your own list, never theirs. Anyone else searches only what they
        reported, so adding filters can narrow the result but never widen it.
        """
        if actor.can(Permission.INCIDENT_VIEW_ALL):
            return query
        if actor.can(Permission.INCIDENT_VIEW_TEAM) and isinstance(actor, Technician):
            return self.__team_scope(actor, query)
        if actor.can(Permission.INCIDENT_VIEW_ASSIGNED):
            return query.restricted_to_assignee(actor.id)
        return query.restricted_to_reporter(actor.id)

    def export_csv(self, actor: User, query: IncidentQuery) -> str:
        """The same filtered list as a CSV download (§9)."""
        page = self.__uow.incidents.search(
            self.scoped(actor, query).for_export(), self.__clock.now()
        )
        services = {service.id: service.name for service in self.__uow.catalogue.services()}
        categories = {c.id: c.name for c in self.__uow.catalogue.categories()}
        names = self.__names(page.items)
        return csv_rows(
            CSV_HEADER,
            [self.__row(i, services, categories, names) for i in page.items],
        )

    # ------------------------------------------------------------ internals
    def __team_scope(self, actor: Technician, query: IncidentQuery) -> IncidentQuery:
        if actor.team_id is None:
            return query.restricted_to_assignee(actor.id)
        members = self.__uow.catalogue.get_team(actor.team_id).member_ids
        wanted = tuple(query.assignee_ids) or members
        allowed = tuple(user_id for user_id in wanted if user_id in members)
        # Asking only about technicians outside the team leaves the lead their own queue.
        return query.restricted_to_assignees(allowed or (actor.id,))

    def __names(self, incidents: Sequence[Incident]) -> dict[int, str]:
        wanted = {i.reporter_id for i in incidents} | {
            i.assignee_id for i in incidents if i.assignee_id is not None
        }
        found: dict[int, str] = {}
        for user_id in sorted(wanted):
            try:
                found[user_id] = self.__uow.users.get(user_id).full_name
            except NotFoundError:
                # Users are never deleted (BR-10), but an export must not die if one is.
                found[user_id] = f"user {user_id}"
        return found

    def __row(
        self,
        incident: Incident,
        services: dict[int, str],
        categories: dict[int, str],
        names: dict[int, str],
    ) -> list[object]:
        return [
            incident.id,
            incident.title,
            incident.status.value,
            incident.priority.value if incident.priority else None,
            services.get(incident.service_id, incident.service_id),
            categories.get(incident.category_id or -1),
            names.get(incident.reporter_id),
            names.get(incident.assignee_id or -1),
            self.__shown(incident.created_at),
            self.__shown(incident.acknowledged_at),
            self.__shown(incident.resolved_at),
            self.__sla(incident),
            incident.reopen_count,
        ]

    @staticmethod
    def __shown(moment: datetime | None) -> str | None:
        return None if moment is None else in_ist(moment).strftime(TIMESTAMP_FORMAT)

    def __sla(self, incident: Incident) -> str | None:
        clock = incident.sla_clock
        if clock is None:
            return None
        now = self.__clock.now()
        statuses = (clock.response_status(now), clock.resolution_status(now))
        for worst in (SLAStatus.BREACHED, SLAStatus.AT_RISK):
            if worst in statuses:
                return worst.value
        return SLAStatus.ON_TRACK.value
