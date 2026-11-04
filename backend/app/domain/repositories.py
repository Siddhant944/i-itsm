"""Repository interfaces (blueprint §2, §10). Implementations live in ``app.repositories``.

Pattern: Repository. Problem solved: the domain and services persist and load aggregates without
knowing whether SQLite, PostgreSQL or memory sits behind them; the same contract tests run
against every implementation.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import TracebackType
from typing import Self

from app.domain.audit import AuditRecord
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.credentials import Credentials
from app.domain.incident import Incident
from app.domain.priority import Priority
from app.domain.sla import SLAPolicyBook, SLATarget, SLATier
from app.domain.users import Technician, User
from app.domain.value_objects import EmailAddress


class IncidentRepository(ABC):
    @abstractmethod
    def add(self, incident: Incident) -> None:
        """Store a new incident with its notes, resolution and feedback."""

    @abstractmethod
    def save(self, incident: Incident) -> None:
        """Write back a loaded incident. Raise ConcurrentModificationError if it moved on."""

    @abstractmethod
    def get(self, incident_id: str) -> Incident:
        """Raise IncidentNotFoundError when absent."""

    @abstractmethod
    def list_by_reporter(self, reporter_id: int) -> tuple[Incident, ...]: ...

    @abstractmethod
    def next_sequence(self, year: int) -> int:
        """The next number for INC-<year>-NNNN (1-based, per year)."""


class UserRepository(ABC):
    @abstractmethod
    def add(self, user: User) -> None: ...

    @abstractmethod
    def save(self, user: User) -> None:
        """Write back a loaded user; credentials and login counters are left untouched."""

    @abstractmethod
    def get(self, user_id: int) -> User:
        """Raise NotFoundError when absent."""

    @abstractmethod
    def find_by_email(self, email: EmailAddress) -> User | None: ...

    @abstractmethod
    def technicians(self) -> tuple[Technician, ...]:
        """Every technician and team lead."""

    @abstractmethod
    def next_id(self) -> int:
        """The next free user id, for self-registration."""


class AuditRepository(ABC):
    """Append-only storage for the hash chain (BR-10): no update, no delete."""

    @abstractmethod
    def append(self, record: AuditRecord) -> None:
        """Add one record. Callers must hold the head (see ``head_for_append``)."""

    @abstractmethod
    def head_for_append(self) -> AuditRecord | None:
        """The newest record, locked against concurrent appends, or None on an empty chain."""

    @abstractmethod
    def records(
        self, *, incident_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[AuditRecord, ...]:
        """A page of the chain, oldest first."""

    @abstractmethod
    def count(self, *, incident_id: str | None = None) -> int: ...

    @abstractmethod
    def hash_before(self, offset: int) -> str | None:
        """The hash of the record just before ``offset``, so one page can be verified alone."""


class CredentialsRepository(ABC):
    """Sign-in state, kept apart from the user so a route can never read a password hash."""

    @abstractmethod
    def get(self, user_id: int) -> Credentials:
        """Raise NotFoundError when the user does not exist."""

    @abstractmethod
    def find_by_email(self, email: EmailAddress) -> Credentials | None:
        """The credentials of the account with this email, or None."""

    @abstractmethod
    def save(self, credentials: Credentials) -> None:
        """Write the hash and the failure counters back."""


class CatalogueRepository(ABC):
    """The admin-editable catalogue: skills, categories, services, teams and SLA policies.

    Every ``save_*`` method inserts or updates, because the catalogue is edited in place.
    """

    @abstractmethod
    def save_skill(self, skill: Skill) -> None: ...

    @abstractmethod
    def skills(self) -> tuple[Skill, ...]: ...

    @abstractmethod
    def skill_names(self) -> Mapping[int, str]:
        """Skill names by id, for building the required-skill set (D-002)."""

    @abstractmethod
    def save_category(self, category: Category) -> None: ...

    @abstractmethod
    def get_category(self, category_id: int) -> Category:
        """Raise NotFoundError when absent."""

    @abstractmethod
    def categories(self, *, active_only: bool = False) -> tuple[Category, ...]: ...

    @abstractmethod
    def save_service(self, service: ITService) -> None: ...

    @abstractmethod
    def get_service(self, service_id: int) -> ITService:
        """Raise ServiceNotFoundError when absent."""

    @abstractmethod
    def services(self, *, active_only: bool = False) -> tuple[ITService, ...]: ...

    @abstractmethod
    def save_team(self, team: Team) -> None: ...

    @abstractmethod
    def get_team(self, team_id: int) -> Team:
        """Raise NotFoundError when absent."""

    @abstractmethod
    def teams(self) -> tuple[Team, ...]: ...

    @abstractmethod
    def save_policies(self, policies: Mapping[tuple[SLATier, Priority], SLATarget]) -> None:
        """Replace the SLA policy table (blueprint §5.2)."""

    @abstractmethod
    def policy_book(self) -> SLAPolicyBook:
        """The configured targets; a missing row falls back to Gold (D-016)."""


class UnitOfWork(ABC):
    """One transaction: changes and their audit records commit or roll back together."""

    incidents: IncidentRepository
    users: UserRepository
    credentials: CredentialsRepository
    catalogue: CatalogueRepository
    audit: AuditRepository

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rollback()

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    def close(self) -> None:
        """Release whatever the transaction held; in memory there is nothing to release."""
        return
