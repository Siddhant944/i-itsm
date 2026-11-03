"""In-memory repositories for unit tests and the contract suite."""

from collections import defaultdict

from app.domain.errors import IncidentNotFoundError, NotFoundError
from app.domain.incident import Incident
from app.domain.repositories import IncidentRepository, UnitOfWork, UserRepository
from app.domain.users import Technician, User
from app.domain.value_objects import EmailAddress


class InMemoryIncidentRepository(IncidentRepository):
    def __init__(self) -> None:
        self.__items: dict[str, Incident] = {}
        self.__sequences: defaultdict[int, int] = defaultdict(int)

    def add(self, incident: Incident) -> None:
        self.__items[incident.id] = incident

    def get(self, incident_id: str) -> Incident:
        try:
            return self.__items[incident_id]
        except KeyError:
            raise IncidentNotFoundError(f"No incident {incident_id}.") from None

    def list_by_reporter(self, reporter_id: int) -> tuple[Incident, ...]:
        return tuple(i for i in self.__items.values() if i.reporter_id == reporter_id)

    def next_sequence(self, year: int) -> int:
        self.__sequences[year] += 1
        return self.__sequences[year]


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self.__items: dict[int, User] = {}

    def add(self, user: User) -> None:
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


class InMemoryUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self.incidents = InMemoryIncidentRepository()
        self.users = InMemoryUserRepository()
        self.committed = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        """Nothing to undo in memory; real implementations roll back the transaction."""
