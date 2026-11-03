"""Repository interfaces (blueprint §2, §10). Implementations live in ``app.repositories``.

Pattern: Repository. Problem solved: the domain and services persist and load aggregates without
knowing whether SQLite, PostgreSQL or memory sits behind them; the same contract tests run
against every implementation.
"""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from app.domain.incident import Incident
from app.domain.users import Technician, User
from app.domain.value_objects import EmailAddress


class IncidentRepository(ABC):
    @abstractmethod
    def add(self, incident: Incident) -> None: ...

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
    def get(self, user_id: int) -> User:
        """Raise NotFoundError when absent."""

    @abstractmethod
    def find_by_email(self, email: EmailAddress) -> User | None: ...

    @abstractmethod
    def technicians(self) -> tuple[Technician, ...]:
        """Every technician and team lead."""


class UnitOfWork(ABC):
    """One transaction: changes and their audit records commit or roll back together."""

    incidents: IncidentRepository
    users: UserRepository

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
