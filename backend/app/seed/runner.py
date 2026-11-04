"""``make seed``: fill an empty database with the campus catalogue, the demo accounts and
the historical incidents (blueprint §9).

Deterministic: the same seed produces the same rows on every machine. Idempotent: the
catalogue and the accounts are written by id, so re-running updates them in place, and the
history is generated only once, recorded by a marker row in ``system_config``.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.clock import Clock
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.permissions import Role
from app.domain.priority import WeightedProductPriorityStrategy
from app.domain.sla import default_policies
from app.domain.users import Technician, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.sqlalchemy.models import IncidentRow, SystemConfigRow, UserRow
from app.repositories.sqlalchemy.repos import SqlAlchemyUnitOfWork
from app.seed import campus, people
from app.seed.history import Catalogue, HistoryGenerator

SEED_MARKER = "seed:history"
SEED_VERSION = 1
PasswordHasher = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class SeedReport:
    users: int
    services: int
    categories: int
    incidents: int
    history_written: bool

    def summary(self) -> str:
        written = "written" if self.history_written else "already present"
        return (
            f"seed: {self.users} users, {self.services} services, "
            f"{self.categories} categories, {self.incidents} incidents ({written})"
        )


def seed(
    uow: SqlAlchemyUnitOfWork,
    clock: Clock,
    *,
    hash_password: PasswordHasher | None = None,
    history: int | None = None,
) -> SeedReport:
    """Seed ``uow``'s database and commit. Safe to run on a database already seeded.

    ``hash_password`` is supplied from P2.3 onwards, when the project has a hasher; until then
    the demo accounts exist with no credentials rather than with a fake hash.
    """
    skills = _skills(uow)
    _teams(uow)
    categories = _categories(uow, skills)
    services = _services(uow, skills)
    uow.catalogue.save_policies(default_policies())
    _users(uow, hash_password)
    uow.commit()

    written = _history(uow, clock, history)
    uow.commit()
    return SeedReport(
        users=len(people.ALL_USERS),
        services=len(services),
        categories=len(categories),
        incidents=_incident_count(uow),
        history_written=written,
    )


# ---------------------------------------------------------------- catalogue
def _skills(uow: SqlAlchemyUnitOfWork) -> dict[str, int]:
    for index, name in enumerate(campus.SKILLS, start=1):
        uow.catalogue.save_skill(Skill(index, name))
    return {skill.name: skill.id for skill in uow.catalogue.skills()}


def _teams(uow: SqlAlchemyUnitOfWork) -> dict[str, int]:
    for index, (name, _) in enumerate(campus.TEAMS, start=1):
        uow.catalogue.save_team(Team(index, name))
    return {team.name: team.id for team in uow.catalogue.teams()}


def _categories(uow: SqlAlchemyUnitOfWork, skills: dict[str, int]) -> list[Category]:
    built = [
        Category(
            index,
            seed_data.name,
            required_skill_id=skills[seed_data.skill],
            keywords=seed_data.keywords,
            minimum_priority=seed_data.minimum_priority,
        )
        for index, seed_data in enumerate(campus.CATEGORIES, start=1)
    ]
    for category in built:
        uow.catalogue.save_category(category)
    return built


def _services(uow: SqlAlchemyUnitOfWork, skills: dict[str, int]) -> list[ITService]:
    ids = {seed_data.name: index for index, seed_data in enumerate(campus.SERVICES, start=1)}
    built = [
        ITService(
            ids[seed_data.name],
            seed_data.name,
            criticality=seed_data.criticality,
            required_skill_id=skills[seed_data.skill] if seed_data.skill else None,
            depends_on=tuple(ids[name] for name in seed_data.depends_on),
        )
        for seed_data in campus.SERVICES
    ]
    for service in sorted(built, key=lambda s: len(s.depends_on)):  # parents before children
        uow.catalogue.save_service(service)
    return built


# ---------------------------------------------------------------- people
def _users(uow: SqlAlchemyUnitOfWork, hash_password: PasswordHasher | None) -> None:
    teams = {team.name: team.id for team in uow.catalogue.teams()}
    stored = set(uow.session.scalars(select(UserRow.id)).all())
    for seed_data in people.ALL_USERS:
        user = UserFactory.create(
            seed_data.role,
            user_id=seed_data.user_id,
            email=seed_data.email,
            full_name=seed_data.full_name,
            skills=SkillSet(seed_data.skills) if seed_data.skills else None,
            experience_level=seed_data.experience_level
            if UserFactory.is_support_role(seed_data.role)
            else None,
            available=seed_data.available if UserFactory.is_support_role(seed_data.role) else None,
            team_id=teams.get(seed_data.team or "") if seed_data.team else None,
        )
        if seed_data.user_id in stored:
            uow.users.save(user)
        else:
            uow.users.add(user)
    _team_leads(uow, teams)
    if hash_password is not None:
        _credentials(uow, hash_password)


def _team_leads(uow: SqlAlchemyUnitOfWork, teams: dict[str, int]) -> None:
    """Each team's lead is the TeamLead the data put in it (D-004)."""
    for name, team_id in teams.items():
        members = [
            seed_data
            for seed_data in people.ALL_USERS
            if seed_data.team == name and seed_data.role is Role.TEAM_LEAD
        ]
        if not members:
            continue
        team = uow.catalogue.get_team(team_id)
        team.set_lead(members[0].user_id)
        uow.catalogue.save_team(team)


def _credentials(uow: SqlAlchemyUnitOfWork, hash_password: PasswordHasher) -> None:
    """Give every demo account the documented demo password (blueprint §14)."""
    digest = hash_password(people.DEMO_PASSWORD)
    for row in uow.session.scalars(select(UserRow)).all():
        row.password_hash = digest
    uow.session.flush()


# ---------------------------------------------------------------- history
def _history(uow: SqlAlchemyUnitOfWork, clock: Clock, size: int | None) -> bool:
    marker = uow.session.get(SystemConfigRow, SEED_MARKER)
    if marker is not None and int(marker.value.get("version", 0)) >= SEED_VERSION:
        return False

    technicians = uow.users.technicians()
    catalogue = Catalogue(
        categories=uow.catalogue.categories(),
        services=uow.catalogue.services(),
        technicians=[t for t in technicians if isinstance(t, Technician)],
        skill_names=dict(uow.catalogue.skill_names()),
        policies=uow.catalogue.policy_book(),
        strategy=WeightedProductPriorityStrategy(),
    )
    generator = HistoryGenerator(catalogue, clock.now())
    allocate = uow.incidents.next_sequence
    incidents = generator.generate(allocate) if size is None else generator.generate(allocate, size)
    for incident in incidents:
        incident.pull_events()  # the history is the past; nothing to notify about
        uow.incidents.add(incident)

    uow.session.add(
        SystemConfigRow(
            key=SEED_MARKER,
            value={"version": SEED_VERSION, "incidents": len(incidents)},
            updated_at=clock.now(),
        )
    )
    uow.session.flush()
    return True


def _incident_count(uow: SqlAlchemyUnitOfWork) -> int:
    return int(uow.session.scalar(select(func.count()).select_from(IncidentRow)) or 0)
