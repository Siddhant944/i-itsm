"""In-memory repositories for unit tests and the contract suite.

They keep the live aggregates, so there is nothing to copy back: ``save`` only has to check
that the caller is writing the object the repository already holds.
"""

from collections import defaultdict
from collections.abc import Mapping

from app.domain.assignment import WORKLOAD_COST
from app.domain.audit import AuditRecord
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.credentials import Credentials
from app.domain.errors import (
    IncidentNotFoundError,
    NotFoundError,
    ServiceNotFoundError,
)
from app.domain.incident import Incident
from app.domain.priority import Priority
from app.domain.repositories import (
    AuditRepository,
    CatalogueRepository,
    CredentialsRepository,
    IncidentRepository,
    UnitOfWork,
    UserRepository,
)
from app.domain.sla import SLAPolicyBook, SLATarget, SLATier, default_policies
from app.domain.states import OPEN_STATUSES
from app.domain.users import Technician, User
from app.domain.value_objects import EmailAddress


class InMemoryIncidentRepository(IncidentRepository):
    def __init__(self) -> None:
        self.__items: dict[str, Incident] = {}
        self.__sequences: defaultdict[int, int] = defaultdict(int)

    def add(self, incident: Incident) -> None:
        self.__items[incident.id] = incident

    def save(self, incident: Incident) -> None:
        if incident.id not in self.__items:
            raise IncidentNotFoundError(f"No incident {incident.id}.")
        self.__items[incident.id] = incident

    def get(self, incident_id: str) -> Incident:
        try:
            return self.__items[incident_id]
        except KeyError:
            raise IncidentNotFoundError(f"No incident {incident_id}.") from None

    def list_by_reporter(self, reporter_id: int) -> tuple[Incident, ...]:
        return tuple(i for i in self.__items.values() if i.reporter_id == reporter_id)

    def list_for_assignee(self, technician_id: int) -> tuple[Incident, ...]:
        found = [i for i in self.__items.values() if i.assignee_id == technician_id]
        return tuple(sorted(found, key=lambda i: i.created_at, reverse=True))

    def workloads(self) -> Mapping[int, int]:
        loads: defaultdict[int, int] = defaultdict(int)
        for incident in self.__items.values():
            if (
                incident.assignee_id is not None
                and incident.status in OPEN_STATUSES
                and incident.priority is not None
            ):
                loads[incident.assignee_id] += WORKLOAD_COST[incident.priority]
        return dict(loads)

    def past_fixes(self, service_id: int) -> Mapping[int, int]:
        fixes: defaultdict[int, int] = defaultdict(int)
        for incident in self.__items.values():
            if (
                incident.service_id == service_id
                and incident.assignee_id is not None
                and incident.resolution is not None
            ):
                fixes[incident.assignee_id] += 1
        return dict(fixes)

    def next_sequence(self, year: int) -> int:
        self.__sequences[year] += 1
        return self.__sequences[year]


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self.__items: dict[int, User] = {}

    def add(self, user: User) -> None:
        self.__items[user.id] = user

    def save(self, user: User) -> None:
        if user.id not in self.__items:
            raise NotFoundError(f"No user {user.id}.")
        self.__items[user.id] = user

    def get(self, user_id: int) -> User:
        try:
            return self.__items[user_id]
        except KeyError:
            raise NotFoundError(f"No user {user_id}.") from None

    def find_by_email(self, email: EmailAddress) -> User | None:
        return next((u for u in self.__items.values() if u.email == email), None)

    def technicians(self) -> tuple[Technician, ...]:
        return tuple(u for u in self.__items.values() if isinstance(u, Technician))

    def next_id(self) -> int:
        return max(self.__items, default=0) + 1


class InMemoryAuditRepository(AuditRepository):
    def __init__(self) -> None:
        self.__records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.__records.append(record)

    def head_for_append(self) -> AuditRecord | None:
        return self.__records[-1] if self.__records else None

    def records(
        self, *, incident_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[AuditRecord, ...]:
        found = self.__selected(incident_id)
        return tuple(found[offset : offset + limit])

    def count(self, *, incident_id: str | None = None) -> int:
        return len(self.__selected(incident_id))

    def hash_before(self, offset: int) -> str | None:
        return self.__records[offset - 1].hash if 0 < offset <= len(self.__records) else None

    def __selected(self, incident_id: str | None) -> list[AuditRecord]:
        if incident_id is None:
            return list(self.__records)
        return [r for r in self.__records if r.incident_id == incident_id]


class InMemoryCredentialsRepository(CredentialsRepository):
    """Sign-in state beside the users it belongs to."""

    def __init__(self, users: InMemoryUserRepository) -> None:
        self.__users = users
        self.__items: dict[int, Credentials] = {}

    def get(self, user_id: int) -> Credentials:
        self.__users.get(user_id)  # raises NotFoundError for an unknown account
        return self.__items.setdefault(user_id, Credentials(user_id=user_id))

    def find_by_email(self, email: EmailAddress) -> Credentials | None:
        user = self.__users.find_by_email(email)
        return None if user is None else self.get(user.id)

    def save(self, credentials: Credentials) -> None:
        self.__users.get(credentials.user_id)
        self.__items[credentials.user_id] = credentials


class InMemoryCatalogueRepository(CatalogueRepository):
    """A technician's ``team_id`` is the single source of team membership, as in the schema."""

    def __init__(self, users: InMemoryUserRepository) -> None:
        self.__users = users
        self.__skills: dict[int, Skill] = {}
        self.__categories: dict[int, Category] = {}
        self.__services: dict[int, ITService] = {}
        self.__teams: dict[int, tuple[str, int | None]] = {}
        self.__policies: dict[tuple[SLATier, Priority], SLATarget] = default_policies()

    def save_skill(self, skill: Skill) -> None:
        self.__skills[skill.id] = skill

    def skills(self) -> tuple[Skill, ...]:
        return tuple(self.__skills[key] for key in sorted(self.__skills))

    def skill_names(self) -> Mapping[int, str]:
        return {skill.id: skill.name for skill in self.skills()}

    def save_category(self, category: Category) -> None:
        self.__categories[category.id] = category

    def get_category(self, category_id: int) -> Category:
        try:
            return self.__categories[category_id]
        except KeyError:
            raise NotFoundError(f"No category {category_id}.") from None

    def categories(self, *, active_only: bool = False) -> tuple[Category, ...]:
        found = (self.__categories[key] for key in sorted(self.__categories))
        return tuple(c for c in found if c.active or not active_only)

    def save_service(self, service: ITService) -> None:
        self.__services[service.id] = service

    def get_service(self, service_id: int) -> ITService:
        try:
            return self.__services[service_id]
        except KeyError:
            raise ServiceNotFoundError(f"No service {service_id}.") from None

    def services(self, *, active_only: bool = False) -> tuple[ITService, ...]:
        found = (self.__services[key] for key in sorted(self.__services))
        return tuple(s for s in found if s.active or not active_only)

    def save_team(self, team: Team) -> None:
        self.__teams[team.id] = (team.name, team.lead_id)
        for member_id in team.member_ids:
            member = self.__users.get(member_id)
            if isinstance(member, Technician):
                member.join_team(team.id)

    def get_team(self, team_id: int) -> Team:
        if team_id not in self.__teams:
            raise NotFoundError(f"No team {team_id}.")
        name, lead_id = self.__teams[team_id]
        members = tuple(t.id for t in self.__users.technicians() if t.team_id == team_id)
        return Team.restore(team_id, name, lead_id=lead_id, member_ids=sorted(members))

    def teams(self) -> tuple[Team, ...]:
        return tuple(self.get_team(key) for key in sorted(self.__teams))

    def save_policies(self, policies: Mapping[tuple[SLATier, Priority], SLATarget]) -> None:
        self.__policies = dict(policies)

    def policy_book(self) -> SLAPolicyBook:
        return SLAPolicyBook(self.__policies)


class InMemoryUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self.incidents = InMemoryIncidentRepository()
        self.users = InMemoryUserRepository()
        self.credentials = InMemoryCredentialsRepository(self.users)
        self.catalogue = InMemoryCatalogueRepository(self.users)
        self.audit = InMemoryAuditRepository()
        self.committed = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        """Nothing to undo in memory; real implementations roll back the transaction."""
