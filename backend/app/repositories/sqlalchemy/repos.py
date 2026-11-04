"""SQLAlchemy repositories and the Unit of Work (blueprint §2, §9).

Pattern: Unit of Work. Problem solved: a change and its audit record must commit or roll back
together, so every repository in one transaction shares a single session; the service layer
calls ``commit`` once and never touches the session itself.

The same classes run on SQLite and PostgreSQL. Optimistic locking rides on
``incidents.version``: a second writer's UPDATE matches no row, SQLAlchemy raises
``StaleDataError`` and that becomes a ConcurrentModificationError (409).
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, Select, delete, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.core.clock import Clock, SystemClock
from app.domain.audit import AuditRecord
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.credentials import Credentials
from app.domain.errors import (
    ConcurrentModificationError,
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
from app.domain.sla import SLAPolicyBook, SLATarget, SLATier
from app.domain.users import Technician, User
from app.domain.value_objects import EmailAddress, SkillSet
from app.repositories.sqlalchemy import mappers
from app.repositories.sqlalchemy.models import (
    AuditRecordRow,
    Base,
    CategoryRow,
    FeedbackRow,
    IncidentRow,
    ResolutionRow,
    ServiceDependencyRow,
    ServiceRow,
    SkillRow,
    SLAPolicyRow,
    SystemConfigRow,
    TeamRow,
    TechnicianProfileRow,
    TechnicianSkillRow,
    UserRow,
    WorkNoteRow,
)

SEQUENCE_KEY_PREFIX = "incident_sequence:"


class SqlAlchemyIncidentRepository(IncidentRepository):
    """Incidents with their work notes, resolution and feedback (composition, blueprint §3)."""

    def __init__(self, session: Session) -> None:
        self.__session = session
        self.__loaded_versions: dict[str, int] = {}

    def add(self, incident: Incident) -> None:
        row = mappers.incident_to_row(incident)
        self.__session.add(row)
        self.__session.flush()
        self.__loaded_versions[incident.id] = row.version
        self.__write_children(incident, note_offset=0)

    def save(self, incident: Incident) -> None:
        """Write the aggregate back, refusing the write if someone else got there first.

        The version this transaction loaded is compared with the row's current version, so a
        new work note contends with a status change: any concurrent edit of the incident loses.
        """
        row = self.__session.get(IncidentRow, incident.id)
        if row is None:
            raise IncidentNotFoundError(f"No incident {incident.id}.")
        expected = self.__loaded_versions.get(incident.id, row.version)
        if row.version != expected:
            raise ConcurrentModificationError()
        mappers.incident_to_row(incident, row)
        row.version = expected + 1  # user-managed version (see IncidentRow.__mapper_args__)
        stored_notes = self.__session.scalar(
            select(func.count())
            .select_from(WorkNoteRow)
            .where(WorkNoteRow.incident_id == incident.id)
        )
        self.__write_children(incident, note_offset=stored_notes or 0)
        try:
            self.__session.flush()
        except StaleDataError as error:
            raise ConcurrentModificationError() from error
        self.__loaded_versions[incident.id] = row.version

    def get(self, incident_id: str) -> Incident:
        row = self.__session.get(IncidentRow, incident_id)
        if row is None:
            raise IncidentNotFoundError(f"No incident {incident_id}.")
        return self.__load(row)

    @property
    def loaded_versions(self) -> Mapping[str, int]:
        """The version each incident was read at in this transaction (for 409 responses)."""
        return dict(self.__loaded_versions)

    def list_by_reporter(self, reporter_id: int) -> tuple[Incident, ...]:
        rows = self.__session.scalars(
            select(IncidentRow)
            .where(IncidentRow.reporter_id == reporter_id)
            .order_by(IncidentRow.created_at, IncidentRow.id)
        ).all()
        return tuple(self.__load(row) for row in rows)

    def next_sequence(self, year: int) -> int:
        """Reserve the next number for ``year``, locking the counter row on PostgreSQL."""
        key = f"{SEQUENCE_KEY_PREFIX}{year}"
        row = self.__session.scalars(
            select(SystemConfigRow).where(SystemConfigRow.key == key).with_for_update()
        ).one_or_none()
        if row is None:
            row = SystemConfigRow(key=key, value={"next": 1})
            self.__session.add(row)
        issued = int(row.value["next"])
        row.value = {"next": issued + 1}  # a new dict, so SQLAlchemy sees the change
        self.__session.flush()
        return issued

    # ------------------------------------------------------------ internals
    def __load(self, row: IncidentRow) -> Incident:
        self.__loaded_versions.setdefault(row.id, row.version)
        notes = self.__session.scalars(
            select(WorkNoteRow).where(WorkNoteRow.incident_id == row.id).order_by(WorkNoteRow.id)
        ).all()
        resolution = self.__session.scalars(
            select(ResolutionRow).where(ResolutionRow.incident_id == row.id)
        ).one_or_none()
        feedback = self.__session.scalars(
            select(FeedbackRow).where(FeedbackRow.incident_id == row.id)
        ).one_or_none()
        return mappers.row_to_incident(
            row,
            notes=tuple(mappers.row_to_note(note) for note in notes),
            resolution=mappers.row_to_resolution(resolution) if resolution else None,
            feedback=mappers.row_to_feedback(feedback) if feedback else None,
        )

    def __write_children(self, incident: Incident, *, note_offset: int) -> None:
        """Append new work notes and upsert the resolution and feedback.

        Work notes are append-only in the domain, so everything past ``note_offset`` is new.
        A rejected fix clears the resolution, which deletes the stored row.
        """
        for note in incident.notes[note_offset:]:
            self.__session.add(mappers.note_to_row(note, incident.id))

        resolution_row = self.__session.scalars(
            select(ResolutionRow).where(ResolutionRow.incident_id == incident.id)
        ).one_or_none()
        if incident.resolution is None:
            if resolution_row is not None:
                self.__session.delete(resolution_row)
        elif resolution_row is None:
            self.__session.add(mappers.resolution_to_row(incident.resolution, incident.id))
        else:
            mappers.resolution_to_row(incident.resolution, incident.id, resolution_row)

        if incident.feedback is not None:
            feedback_row = self.__session.scalars(
                select(FeedbackRow).where(FeedbackRow.incident_id == incident.id)
            ).one_or_none()
            if feedback_row is None:
                self.__session.add(mappers.feedback_to_row(incident.feedback, incident.id))
            else:
                mappers.feedback_to_row(incident.feedback, incident.id, feedback_row)


class SqlAlchemyUserRepository(UserRepository):
    """Users, with the technician-only fields in ``technician_profiles``."""

    def __init__(self, session: Session, clock: Clock) -> None:
        self.__session = session
        self.__clock = clock

    def add(self, user: User) -> None:
        self.__session.add(mappers.new_user_row(user, self.__clock.now()))
        self.__session.flush()
        self.__write_profile(user)

    def save(self, user: User) -> None:
        row = self.__session.get(UserRow, user.id)
        if row is None:
            raise NotFoundError(f"No user {user.id}.")
        mappers.user_to_row(user, row)
        self.__write_profile(user)
        self.__session.flush()

    def get(self, user_id: int) -> User:
        row = self.__session.get(UserRow, user_id)
        if row is None:
            raise NotFoundError(f"No user {user_id}.")
        return self.__load(row)

    def find_by_email(self, email: EmailAddress) -> User | None:
        row = self.__session.scalars(
            select(UserRow).where(UserRow.email == str(email))
        ).one_or_none()
        return self.__load(row) if row is not None else None

    def technicians(self) -> tuple[Technician, ...]:
        rows = self.__session.scalars(
            select(UserRow)
            .join(TechnicianProfileRow, TechnicianProfileRow.user_id == UserRow.id)
            .order_by(UserRow.id)
        ).all()
        return tuple(
            user for user in (self.__load(row) for row in rows) if isinstance(user, Technician)
        )

    def next_id(self) -> int:
        return int(self.__session.scalar(select(func.max(UserRow.id))) or 0) + 1

    # ------------------------------------------------------------ internals
    def __load(self, row: UserRow) -> User:
        profile = self.__session.get(TechnicianProfileRow, row.id)
        skills = SkillSet(
            self.__session.scalars(
                select(SkillRow.name)
                .join(TechnicianSkillRow, TechnicianSkillRow.skill_id == SkillRow.id)
                .where(TechnicianSkillRow.user_id == row.id)
            ).all()
        )
        return mappers.row_to_user(row, profile, skills)

    def __write_profile(self, user: User) -> None:
        """Keep ``technician_profiles`` and ``technician_skills`` in step with the user."""
        if not isinstance(user, Technician):
            return
        profile = self.__session.get(TechnicianProfileRow, user.id)
        if profile is None:
            self.__session.add(mappers.technician_profile_to_row(user))
        else:
            mappers.technician_profile_to_row(user, profile)
        self.__session.flush()
        self.__write_skills(user)

    def __write_skills(self, technician: Technician) -> None:
        wanted = {name: self.__skill_id(name) for name in technician.skills.names}
        self.__session.execute(
            delete(TechnicianSkillRow)
            .where(TechnicianSkillRow.user_id == technician.id)
            .where(TechnicianSkillRow.skill_id.notin_(wanted.values() or [-1]))
        )
        stored = set(
            self.__session.scalars(
                select(TechnicianSkillRow.skill_id).where(
                    TechnicianSkillRow.user_id == technician.id
                )
            ).all()
        )
        for skill_id in wanted.values():
            if skill_id not in stored:
                self.__session.add(TechnicianSkillRow(user_id=technician.id, skill_id=skill_id))
        self.__session.flush()

    def __skill_id(self, name: str) -> int:
        """The id of ``name``, creating the skill when a technician brings a new one."""
        found = self.__session.scalars(select(SkillRow).where(SkillRow.name == name)).one_or_none()
        if found is not None:
            return found.id
        row = SkillRow(name=name)
        self.__session.add(row)
        self.__session.flush()
        return row.id


class SqlAlchemyAuditRepository(AuditRepository):
    """The hash chain in ``audit_log``: insert only, and appends are serialised on the head.

    ``head_for_append`` takes a row lock on the newest record, so two transactions cannot both
    read the same predecessor and write two records claiming the same place in the chain. On
    SQLite the write lock already serialises them and the FOR UPDATE clause is simply omitted.
    """

    def __init__(self, session: Session) -> None:
        self.__session = session

    def append(self, record: AuditRecord) -> None:
        self.__session.add(mappers.audit_to_row(record))
        self.__session.flush()

    def head_for_append(self) -> AuditRecord | None:
        row = self.__session.scalars(
            select(AuditRecordRow).order_by(AuditRecordRow.id.desc()).limit(1).with_for_update()
        ).one_or_none()
        return None if row is None else mappers.row_to_audit(row)

    def records(
        self, *, incident_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[AuditRecord, ...]:
        statement = self.__filtered(select(AuditRecordRow), incident_id)
        rows = self.__session.scalars(
            statement.order_by(AuditRecordRow.id).limit(limit).offset(offset)
        ).all()
        return tuple(mappers.row_to_audit(row) for row in rows)

    def count(self, *, incident_id: str | None = None) -> int:
        statement = self.__filtered(select(func.count()).select_from(AuditRecordRow), incident_id)
        return int(self.__session.scalar(statement) or 0)

    def hash_before(self, offset: int) -> str | None:
        if offset <= 0:
            return None
        return self.__session.scalar(
            select(AuditRecordRow.hash).order_by(AuditRecordRow.id).limit(1).offset(offset - 1)
        )

    @staticmethod
    def __filtered(statement: Select[Any], incident_id: str | None) -> Select[Any]:
        if incident_id is None:
            return statement
        return statement.where(AuditRecordRow.incident_id == incident_id)


class SqlAlchemyCredentialsRepository(CredentialsRepository):
    """The sign-in columns of ``users``, read and written on their own."""

    def __init__(self, session: Session) -> None:
        self.__session = session

    def get(self, user_id: int) -> Credentials:
        row = self.__session.get(UserRow, user_id)
        if row is None:
            raise NotFoundError(f"No user {user_id}.")
        return mappers.row_to_credentials(row)

    def find_by_email(self, email: EmailAddress) -> Credentials | None:
        row = self.__session.scalars(
            select(UserRow).where(UserRow.email == str(email))
        ).one_or_none()
        return None if row is None else mappers.row_to_credentials(row)

    def save(self, credentials: Credentials) -> None:
        row = self.__session.get(UserRow, credentials.user_id)
        if row is None:
            raise NotFoundError(f"No user {credentials.user_id}.")
        mappers.credentials_to_row(credentials, row)
        self.__session.flush()


class SqlAlchemyCatalogueRepository(CatalogueRepository):
    """Skills, categories, services and their dependencies, teams and the SLA policy table."""

    def __init__(self, session: Session) -> None:
        self.__session = session

    # --- skills
    def save_skill(self, skill: Skill) -> None:
        row = self.__session.get(SkillRow, skill.id)
        if row is None:
            self.__session.add(mappers.skill_to_row(skill))
        else:
            mappers.skill_to_row(skill, row)
        self.__session.flush()

    def skills(self) -> tuple[Skill, ...]:
        rows = self.__session.scalars(select(SkillRow).order_by(SkillRow.id)).all()
        return tuple(mappers.row_to_skill(row) for row in rows)

    def skill_names(self) -> Mapping[int, str]:
        return {skill.id: skill.name for skill in self.skills()}

    # --- categories
    def save_category(self, category: Category) -> None:
        row = self.__session.get(CategoryRow, category.id)
        if row is None:
            self.__session.add(mappers.category_to_row(category))
        else:
            mappers.category_to_row(category, row)
        self.__session.flush()

    def get_category(self, category_id: int) -> Category:
        row = self.__session.get(CategoryRow, category_id)
        if row is None:
            raise NotFoundError(f"No category {category_id}.")
        return mappers.row_to_category(row)

    def categories(self, *, active_only: bool = False) -> tuple[Category, ...]:
        statement = select(CategoryRow).order_by(CategoryRow.id)
        if active_only:
            statement = statement.where(CategoryRow.active.is_(True))
        return tuple(mappers.row_to_category(r) for r in self.__session.scalars(statement).all())

    # --- services
    def save_service(self, service: ITService) -> None:
        row = self.__session.get(ServiceRow, service.id)
        if row is None:
            self.__session.add(mappers.service_to_row(service))
        else:
            mappers.service_to_row(service, row)
        self.__session.flush()
        self.__write_dependencies(service)

    def get_service(self, service_id: int) -> ITService:
        row = self.__session.get(ServiceRow, service_id)
        if row is None:
            raise ServiceNotFoundError(f"No service {service_id}.")
        return mappers.row_to_service(row, self.__dependencies(service_id))

    def services(self, *, active_only: bool = False) -> tuple[ITService, ...]:
        statement = select(ServiceRow).order_by(ServiceRow.id)
        if active_only:
            statement = statement.where(ServiceRow.active.is_(True))
        rows = self.__session.scalars(statement).all()
        return tuple(mappers.row_to_service(row, self.__dependencies(row.id)) for row in rows)

    # --- teams
    def save_team(self, team: Team) -> None:
        row = self.__session.get(TeamRow, team.id)
        if row is None:
            self.__session.add(mappers.team_to_row(team))
        else:
            mappers.team_to_row(team, row)
        self.__session.flush()
        self.__write_members(team)

    def get_team(self, team_id: int) -> Team:
        row = self.__session.get(TeamRow, team_id)
        if row is None:
            raise NotFoundError(f"No team {team_id}.")
        return mappers.row_to_team(row, self.__members(team_id))

    def teams(self) -> tuple[Team, ...]:
        rows = self.__session.scalars(select(TeamRow).order_by(TeamRow.id)).all()
        return tuple(mappers.row_to_team(row, self.__members(row.id)) for row in rows)

    # --- SLA policies
    def save_policies(self, policies: Mapping[tuple[SLATier, Priority], SLATarget]) -> None:
        self.__session.execute(delete(SLAPolicyRow))
        self.__session.flush()
        for (tier, priority), target in policies.items():
            self.__session.add(
                SLAPolicyRow(
                    tier=tier,
                    priority=priority,
                    response=target.response,
                    resolution=target.resolution,
                )
            )
        self.__session.flush()

    def policy_book(self) -> SLAPolicyBook:
        rows = self.__session.scalars(select(SLAPolicyRow)).all()
        return SLAPolicyBook(
            {(row.tier, row.priority): SLATarget(row.response, row.resolution) for row in rows}
        )

    # ------------------------------------------------------------ internals
    def __dependencies(self, service_id: int) -> tuple[int, ...]:
        return tuple(
            self.__session.scalars(
                select(ServiceDependencyRow.depends_on_id)
                .where(ServiceDependencyRow.service_id == service_id)
                .order_by(ServiceDependencyRow.position)
            ).all()
        )

    def __write_dependencies(self, service: ITService) -> None:
        self.__session.execute(
            delete(ServiceDependencyRow).where(ServiceDependencyRow.service_id == service.id)
        )
        self.__session.flush()
        for position, depends_on_id in enumerate(service.depends_on):
            self.__session.add(
                ServiceDependencyRow(
                    service_id=service.id, depends_on_id=depends_on_id, position=position
                )
            )
        self.__session.flush()

    def __members(self, team_id: int) -> tuple[int, ...]:
        return tuple(
            self.__session.scalars(
                select(TechnicianProfileRow.user_id)
                .where(TechnicianProfileRow.team_id == team_id)
                .order_by(TechnicianProfileRow.user_id)
            ).all()
        )

    def __write_members(self, team: Team) -> None:
        """A team owns which technicians point at it; technicians themselves are not deleted."""
        for user_id in team.member_ids:
            profile = self.__session.get(TechnicianProfileRow, user_id)
            if profile is not None:
                profile.team_id = team.id
        self.__session.flush()


class SqlAlchemyUnitOfWork(UnitOfWork):
    """One session, one transaction, three repositories."""

    def __init__(self, session_factory: sessionmaker[Session], clock: Clock | None = None) -> None:
        self.__session_factory = session_factory
        self.__clock = clock or SystemClock()
        self.__session = session_factory()
        self.incidents = SqlAlchemyIncidentRepository(self.__session)
        self.users = SqlAlchemyUserRepository(self.__session, self.__clock)
        self.credentials = SqlAlchemyCredentialsRepository(self.__session)
        self.catalogue = SqlAlchemyCatalogueRepository(self.__session)
        self.audit = SqlAlchemyAuditRepository(self.__session)

    @property
    def session(self) -> Session:
        """The session this transaction uses (the audit service writes through it, P2.4)."""
        return self.__session

    def commit(self) -> None:
        try:
            self.__session.commit()
        except StaleDataError as error:
            self.__session.rollback()
            raise ConcurrentModificationError() from error

    def rollback(self) -> None:
        self.__session.rollback()

    def close(self) -> None:
        self.__session.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessions that keep loaded rows usable after a commit."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Create every table (tests and ``make seed``; deployments run Alembic instead)."""
    Base.metadata.create_all(engine)
