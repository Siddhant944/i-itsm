"""SQLAlchemy repositories and the Unit of Work (blueprint §2, §9).

Pattern: Unit of Work. Problem solved: a change and its audit record must commit or roll back
together, so every repository in one transaction shares a single session; the service layer
calls ``commit`` once and never touches the session itself.

The same classes run on SQLite and PostgreSQL. Optimistic locking rides on
``incidents.version``: a second writer's UPDATE matches no row, SQLAlchemy raises
``StaleDataError`` and that becomes a ConcurrentModificationError (409).
"""

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Engine,
    Float,
    Select,
    and_,
    case,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql.elements import ColumnElement

from app.core.clock import Clock, SystemClock
from app.domain.analytics import (
    DurationStats,
    Metrics,
    Overview,
    SatisfactionStats,
    ServiceMetrics,
    TechnicianWorkload,
    TrendPoint,
)
from app.domain.assignment import MAX_LOAD, WORKLOAD_COST
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
from app.domain.notifications import ChannelName, Notification
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.repositories import (
    AnalyticsRepository,
    AuditRepository,
    CatalogueRepository,
    CredentialsRepository,
    IncidentRepository,
    NotificationRepository,
    SLAViolationRepository,
    UnitOfWork,
    UserRepository,
)
from app.domain.search import IncidentQuery, Page, SortField
from app.domain.sla import (
    SLAPolicyBook,
    SLAStatus,
    SLATarget,
    SLATier,
    SLAViolation,
    ViolationKind,
)
from app.domain.states import (
    AWAITING_REPORTER,
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    IncidentStatus,
)
from app.domain.users import Technician, User
from app.domain.value_objects import EmailAddress, SkillSet
from app.repositories.sqlalchemy import mappers
from app.repositories.sqlalchemy.models import (
    AuditRecordRow,
    Base,
    CategoryRow,
    FeedbackRow,
    IncidentRow,
    NotificationRow,
    ResolutionRow,
    ServiceDependencyRow,
    ServiceRow,
    SkillRow,
    SLAPolicyRow,
    SLAViolationRow,
    SystemConfigRow,
    TeamRow,
    TechnicianProfileRow,
    TechnicianSkillRow,
    UserRow,
    WorkNoteRow,
)

SEQUENCE_KEY_PREFIX = "incident_sequence:"
SECONDS_PER_DAY = 86_400.0


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

    def list_for_assignee(self, technician_id: int) -> tuple[Incident, ...]:
        rows = self.__session.scalars(
            select(IncidentRow)
            .where(IncidentRow.assignee_id == technician_id)
            .order_by(IncidentRow.created_at.desc(), IncidentRow.id.desc())
        ).all()
        return tuple(self.__load(row) for row in rows)

    def workloads(self) -> Mapping[int, int]:
        """One grouped query, so ranking candidates does not read every open incident."""
        rows = self.__session.execute(
            select(IncidentRow.assignee_id, IncidentRow.priority, func.count())
            .where(IncidentRow.assignee_id.is_not(None))
            .where(IncidentRow.status.in_(tuple(OPEN_STATUSES)))
            .where(IncidentRow.priority.is_not(None))
            .group_by(IncidentRow.assignee_id, IncidentRow.priority)
        ).all()
        loads: dict[int, int] = {}
        for assignee_id, priority, count in rows:
            if assignee_id is None or priority is None:  # excluded by the WHERE clauses
                continue
            loads[assignee_id] = loads.get(assignee_id, 0) + WORKLOAD_COST[priority] * count
        return loads

    def past_fixes(self, service_id: int) -> Mapping[int, int]:
        rows = self.__session.execute(
            select(IncidentRow.assignee_id, func.count())
            .join(ResolutionRow, ResolutionRow.incident_id == IncidentRow.id)
            .where(IncidentRow.service_id == service_id)
            .where(IncidentRow.assignee_id.is_not(None))
            .group_by(IncidentRow.assignee_id)
        ).all()
        return {assignee_id: count for assignee_id, count in rows if assignee_id is not None}

    def awaiting_auto_close(self, resolved_before: datetime) -> tuple[Incident, ...]:
        rows = self.__session.scalars(
            select(IncidentRow)
            .where(IncidentRow.status == IncidentStatus.RESOLVED)
            .where(IncidentRow.resolved_at.is_not(None))
            .where(IncidentRow.resolved_at < resolved_before)
            .order_by(IncidentRow.resolved_at)
        ).all()
        return tuple(self.__load(row) for row in rows)

    def needing_sla_attention(self, now: datetime) -> tuple[Incident, ...]:
        rows = self.__session.scalars(
            select(IncidentRow)
            .where(IncidentRow.status.notin_(tuple(TERMINAL_STATUSES)))
            .where(
                or_(
                    _sla_condition(SLAStatus.AT_RISK, now),
                    _sla_condition(SLAStatus.BREACHED, now),
                )
            )
            .order_by(IncidentRow.created_at)
        ).all()
        return tuple(self.__load(row) for row in rows)

    def search(self, query: IncidentQuery, now: datetime) -> Page[Incident]:
        """One page of matches plus the total, as two queries over the same filters (§9)."""
        conditions = _conditions(query, now)
        total = int(
            self.__session.scalar(select(func.count()).select_from(IncidentRow).where(*conditions))
            or 0
        )
        rows = self.__session.scalars(
            select(IncidentRow)
            .where(*conditions)
            .order_by(*_ordering(query))
            .offset(query.offset)
            .limit(query.limit)
        ).all()
        return Page(tuple(self.__load(row) for row in rows), total, query.offset, query.limit)

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


def _conditions(query: IncidentQuery, now: datetime) -> list[ColumnElement[bool]]:
    """The nine §9 filters and the free text, as WHERE clauses."""
    where: list[ColumnElement[bool]] = []
    if query.incident_id:
        where.append(IncidentRow.id.ilike(f"%{query.incident_id}%"))
    if query.text:
        # §9: ilike works the same on SQLite and PostgreSQL, and the ORM parameterises it.
        pattern = f"%{query.text}%"
        where.append(
            or_(
                IncidentRow.id.ilike(pattern),
                IncidentRow.title.ilike(pattern),
                IncidentRow.description.ilike(pattern),
            )
        )
    if query.created_from is not None:
        where.append(IncidentRow.created_at >= query.created_from)
    if query.created_to is not None:
        where.append(IncidentRow.created_at <= query.created_to)
    if query.statuses:
        where.append(IncidentRow.status.in_(query.statuses))
    if query.priorities:
        where.append(IncidentRow.priority.in_(query.priorities))
    if query.category_ids:
        where.append(IncidentRow.category_id.in_(query.category_ids))
    if query.service_ids:
        where.append(IncidentRow.service_id.in_(query.service_ids))
    if query.assignee_ids:
        where.append(IncidentRow.assignee_id.in_(query.assignee_ids))
    if query.reporter_ids:
        where.append(IncidentRow.reporter_id.in_(query.reporter_ids))
    if query.sla_statuses:
        where.append(or_(*(_sla_condition(status, now) for status in query.sla_statuses)))
    return where


def _response_moment(now: datetime) -> ColumnElement[datetime]:
    """When the response clock is measured: at the stop, or now (it is never paused)."""
    return case(
        (IncidentRow.sla_stopped_at.is_not(None), IncidentRow.sla_stopped_at),
        else_=literal(now),
    )


def _resolution_moment(now: datetime) -> ColumnElement[datetime]:
    """When the resolution clock is measured: at the stop, at the pause, or now (BR-07)."""
    return case(
        (IncidentRow.sla_stopped_at.is_not(None), IncidentRow.sla_stopped_at),
        (IncidentRow.sla_paused_since.is_not(None), IncidentRow.sla_paused_since),
        else_=literal(now),
    )


def _has_clock() -> ColumnElement[bool]:
    return IncidentRow.sla_resolution_deadline.is_not(None)


def _response_breached(now: datetime) -> ColumnElement[bool]:
    """Acknowledged too late, or still not acknowledged past the response deadline (§5.2)."""
    return or_(
        IncidentRow.sla_response_met.is_(False),
        and_(
            IncidentRow.sla_responded_at.is_(None),
            _response_moment(now) > IncidentRow.sla_response_deadline,
        ),
    )


def _resolution_breached(now: datetime) -> ColumnElement[bool]:
    return _resolution_moment(now) > IncidentRow.sla_resolution_deadline


def _at_risk(now: datetime) -> ColumnElement[bool]:
    """Either clock has reached 75 % of its target. A responded clock is never at risk."""
    return or_(
        and_(
            IncidentRow.sla_responded_at.is_(None),
            _response_moment(now) >= IncidentRow.sla_response_risk_at,
        ),
        _resolution_moment(now) >= IncidentRow.sla_resolution_risk_at,
    )


def _sla_condition(status: SLAStatus, now: datetime) -> ColumnElement[bool]:
    """Turn an SLA status into comparisons against the stored deadlines (D-018).

    The status is the worse of the two clocks, exactly as ``SLAClock.response_status`` and
    ``resolution_status`` combine in the in-memory implementation; the contract suite runs
    every case against both.
    """
    breached = and_(_has_clock(), or_(_response_breached(now), _resolution_breached(now)))
    if status is SLAStatus.BREACHED:
        return breached
    if status is SLAStatus.AT_RISK:
        return and_(_has_clock(), ~breached, _at_risk(now))
    return and_(_has_clock(), ~breached, ~_at_risk(now))


def _ordering(query: IncidentQuery) -> tuple[ColumnElement[Any], ...]:
    columns = {
        SortField.CREATED_AT: IncidentRow.created_at,
        SortField.PRIORITY: IncidentRow.priority,
        SortField.STATUS: IncidentRow.status,
        SortField.ID: IncidentRow.id,
    }
    column = columns[query.sort_by]
    # Be explicit about nulls: SQLite and PostgreSQL disagree by default, and an incident with
    # no priority yet belongs at the end of an ascending list, not the start.
    primary = column.desc().nulls_first() if query.descending else column.asc().nulls_last()
    tiebreak = IncidentRow.id.desc() if query.descending else IncidentRow.id.asc()
    return (primary, tiebreak)


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

    def administrators(self) -> tuple[User, ...]:
        rows = self.__session.scalars(
            select(UserRow)
            .where(UserRow.role.in_((Role.ADMINISTRATOR, Role.IT_MANAGER)))
            .order_by(UserRow.id)
        ).all()
        return tuple(self.__load(row) for row in rows)

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
        """The id of ``name``, creating the skill when a technician brings a new one.

        The id is chosen here rather than left to the database. The catalogue is seeded with
        explicit ids so that two machines hold the same data, and on PostgreSQL an explicit
        insert does not advance the table's sequence — so letting the database pick would
        collide with a seeded row.
        """
        found = self.__session.scalars(select(SkillRow).where(SkillRow.name == name)).one_or_none()
        if found is not None:
            return found.id
        next_id = int(self.__session.scalar(select(func.max(SkillRow.id))) or 0) + 1
        self.__session.add(SkillRow(id=next_id, name=name))
        self.__session.flush()
        return next_id


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


class SqlAlchemyNotificationRepository(NotificationRepository):
    """The ``notifications`` table: one row per person, per event, per channel."""

    def __init__(self, session: Session) -> None:
        self.__session = session

    def add(self, notification: Notification) -> Notification:
        row = mappers.notification_to_row(notification)
        self.__session.add(row)
        self.__session.flush()
        notification.identify(row.id)
        return notification

    def save(self, notification: Notification) -> None:
        if notification.id is None:
            raise NotFoundError("This notification has not been stored yet.")
        row = self.__session.get(NotificationRow, notification.id)
        if row is None:
            raise NotFoundError(f"No notification {notification.id}.")
        mappers.notification_to_row(notification, row)
        self.__session.flush()

    def get(self, notification_id: int) -> Notification:
        row = self.__session.get(NotificationRow, notification_id)
        if row is None:
            raise NotFoundError(f"No notification {notification_id}.")
        return mappers.row_to_notification(row)

    def in_app_for(
        self, user_id: int, *, unread_only: bool = False, limit: int = 20
    ) -> tuple[Notification, ...]:
        statement = (
            select(NotificationRow)
            .where(NotificationRow.user_id == user_id)
            .where(NotificationRow.channel == ChannelName.IN_APP.value)
        )
        if unread_only:
            statement = statement.where(NotificationRow.read_at.is_(None))
        rows = self.__session.scalars(
            statement.order_by(NotificationRow.created_at.desc(), NotificationRow.id.desc()).limit(
                limit
            )
        ).all()
        return tuple(mappers.row_to_notification(row) for row in rows)

    def count_unread(self, user_id: int) -> int:
        return int(
            self.__session.scalar(
                select(func.count())
                .select_from(NotificationRow)
                .where(NotificationRow.user_id == user_id)
                .where(NotificationRow.channel == ChannelName.IN_APP.value)
                .where(NotificationRow.read_at.is_(None))
            )
            or 0
        )


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


class SqlAlchemySLAViolationRepository(SLAViolationRepository):
    """``sla_violations``, whose unique key is what stops a tick reporting twice."""

    def __init__(self, session: Session) -> None:
        self.__session = session

    def record(self, violation: SLAViolation) -> bool:
        existing = self.__session.scalars(
            select(SLAViolationRow)
            .where(SLAViolationRow.incident_id == violation.incident_id)
            .where(SLAViolationRow.kind == violation.kind)
            .where(SLAViolationRow.cycle == violation.cycle)
        ).one_or_none()
        if existing is not None:
            return False
        self.__session.add(
            SLAViolationRow(
                incident_id=violation.incident_id,
                kind=violation.kind,
                cycle=violation.cycle,
                deadline=violation.deadline,
                detected_at=violation.detected_at,
                escalated_to_level=violation.escalated_to_level,
            )
        )
        self.__session.flush()
        return True

    def for_incident(self, incident_id: str) -> tuple[SLAViolation, ...]:
        rows = self.__session.scalars(
            select(SLAViolationRow)
            .where(SLAViolationRow.incident_id == incident_id)
            .order_by(SLAViolationRow.id)
        ).all()
        return tuple(_to_violation(row) for row in rows)

    def recent(self, limit: int = 50) -> tuple[SLAViolation, ...]:
        rows = self.__session.scalars(
            select(SLAViolationRow)
            .order_by(SLAViolationRow.detected_at.desc(), SLAViolationRow.id.desc())
            .limit(limit)
        ).all()
        return tuple(_to_violation(row) for row in rows)

    def count(self, *, breaches_only: bool = False) -> int:
        statement = select(func.count()).select_from(SLAViolationRow)
        if breaches_only:
            statement = statement.where(
                SLAViolationRow.kind.in_(
                    (ViolationKind.RESPONSE_BREACH, ViolationKind.RESOLUTION_BREACH)
                )
            )
        return int(self.__session.scalar(statement) or 0)


def _to_violation(row: SLAViolationRow) -> SLAViolation:
    return SLAViolation(
        incident_id=row.incident_id,
        kind=row.kind,
        cycle=row.cycle,
        deadline=row.deadline,
        detected_at=row.detected_at,
        escalated_to_level=row.escalated_to_level,
    )


class SqlAlchemyAnalyticsRepository(AnalyticsRepository):
    """The dashboard figures as grouped queries (blueprint §9).

    Everything is counted in the database. The durations come back as totals and counts, and
    ``app.domain.analytics`` does the division, so the averaging rules are tested once and read
    the same whichever database is underneath.
    """

    def __init__(self, session: Session) -> None:
        self.__session = session
        self.__dialect = session.get_bind().dialect.name

    def overview(self, now: datetime, since: datetime | None = None) -> Overview:
        window = _since(since)
        alive = IncidentRow.status.notin_(tuple(TERMINAL_STATUSES))
        counts = self.__session.execute(
            select(
                func.count(),
                func.sum(_flag(IncidentRow.status.in_(tuple(OPEN_STATUSES)))),
                func.sum(_flag(and_(IncidentRow.assignee_id.is_(None), alive))),
                func.sum(_flag(IncidentRow.status.in_(tuple(AWAITING_REPORTER)))),
                func.sum(_flag(and_(alive, _sla_condition(SLAStatus.BREACHED, now)))),
                func.sum(_flag(and_(alive, _sla_condition(SLAStatus.AT_RISK, now)))),
                func.sum(_flag(and_(alive, IncidentRow.priority == Priority.P1))),
                func.sum(_flag(IncidentRow.resolved_at.is_not(None))),
            ).where(*window)
        ).one()
        total, open_count, unassigned, waiting, breached, at_risk, critical, resolved = counts
        return Overview(
            total=int(total or 0),
            open_count=int(open_count or 0),
            unassigned=int(unassigned or 0),
            awaiting_reporter=int(waiting or 0),
            breached=int(breached or 0),
            at_risk=int(at_risk or 0),
            critical_open=int(critical or 0),
            resolved_in_window=int(resolved or 0),
        )

    def metrics(self, since: datetime | None = None) -> Metrics:
        window = _since(since)
        acknowledgement = self.__durations(IncidentRow.acknowledged_at, window)
        resolution = self.__durations(IncidentRow.resolved_at, window)

        # Only resolved incidents with a clock can be measured for compliance.
        measured = int(
            self.__session.scalar(
                select(func.count())
                .select_from(IncidentRow)
                .where(*window)
                .where(IncidentRow.resolved_at.is_not(None))
                .where(IncidentRow.sla_resolution_deadline.is_not(None))
            )
            or 0
        )
        # One met its SLA when it was answered in time and finished before its deadline.
        met = int(
            self.__session.scalar(
                select(func.count())
                .select_from(IncidentRow)
                .where(*window)
                .where(IncidentRow.resolved_at.is_not(None))
                .where(IncidentRow.sla_resolution_deadline.is_not(None))
                .where(IncidentRow.resolved_at <= IncidentRow.sla_resolution_deadline)
                .where(
                    or_(
                        IncidentRow.sla_response_met.is_(True),
                        IncidentRow.sla_response_met.is_(None),
                    )
                )
            )
            or 0
        )

        ratings, responses = self.__session.execute(
            select(func.sum(FeedbackRow.rating), func.count())
            .select_from(FeedbackRow)
            .join(IncidentRow, IncidentRow.id == FeedbackRow.incident_id)
            .where(*window)
        ).one()

        reopened = int(
            self.__session.scalar(
                select(func.count())
                .select_from(IncidentRow)
                .where(*window)
                .where(IncidentRow.reopen_count > 0)
            )
            or 0
        )
        finished = int(
            self.__session.scalar(
                select(func.count())
                .select_from(IncidentRow)
                .where(*window)
                .where(
                    or_(
                        IncidentRow.resolved_at.is_not(None),
                        IncidentRow.closed_at.is_not(None),
                    )
                )
            )
            or 0
        )
        return Metrics(
            acknowledgement=acknowledgement,
            resolution=resolution,
            sla_met=met,
            sla_measured=measured,
            satisfaction=SatisfactionStats(int(ratings or 0), int(responses or 0)),
            reopened=reopened,
            resolved_or_closed=finished,
        )

    def workload(self) -> tuple[TechnicianWorkload, ...]:
        rows = self.__session.execute(
            select(
                UserRow.id,
                UserRow.full_name,
                UserRow.active,
                TechnicianProfileRow.available,
            )
            .join(TechnicianProfileRow, TechnicianProfileRow.user_id == UserRow.id)
            .order_by(UserRow.id)
        ).all()
        open_counts = dict(
            self.__session.execute(
                select(IncidentRow.assignee_id, func.count())
                .where(IncidentRow.status.in_(tuple(OPEN_STATUSES)))
                .group_by(IncidentRow.assignee_id)
            ).all()
        )
        fixed = dict(
            self.__session.execute(
                select(IncidentRow.assignee_id, func.count())
                .join(ResolutionRow, ResolutionRow.incident_id == IncidentRow.id)
                .group_by(IncidentRow.assignee_id)
            ).all()
        )
        loads = SqlAlchemyIncidentRepository(self.__session).workloads()
        return tuple(
            TechnicianWorkload(
                technician_id=user_id,
                name=name,
                available=bool(active and available),
                open_count=int(open_counts.get(user_id, 0)),
                weighted_load=loads.get(user_id, 0),
                max_load=MAX_LOAD,
                resolved=int(fixed.get(user_id, 0)),
            )
            for user_id, name, active, available in rows
        )

    def by_service(self, since: datetime | None = None) -> tuple[ServiceMetrics, ...]:
        window = _since(since)
        counted = dict(
            self.__session.execute(
                select(IncidentRow.service_id, func.count())
                .where(*window)
                .group_by(IncidentRow.service_id)
            ).all()
        )
        breached = dict(
            self.__session.execute(
                select(IncidentRow.service_id, func.count())
                .where(*window)
                .where(IncidentRow.resolved_at.is_not(None))
                .where(IncidentRow.sla_resolution_deadline.is_not(None))
                .where(IncidentRow.resolved_at > IncidentRow.sla_resolution_deadline)
                .group_by(IncidentRow.service_id)
            ).all()
        )
        resolved = {
            service_id: DurationStats(timedelta(seconds=float(seconds or 0)), int(count or 0))
            for service_id, seconds, count in self.__session.execute(
                select(
                    IncidentRow.service_id,
                    func.sum(self.__elapsed_seconds(IncidentRow.resolved_at)),
                    func.count(),
                )
                .where(*window)
                .where(IncidentRow.resolved_at.is_not(None))
                .group_by(IncidentRow.service_id)
            ).all()
        }
        services = self.__session.execute(
            select(ServiceRow.id, ServiceRow.name).order_by(ServiceRow.id)
        ).all()
        return tuple(
            ServiceMetrics(
                service_id=service_id,
                name=name,
                incidents=int(counted.get(service_id, 0)),
                breached=int(breached.get(service_id, 0)),
                resolution=resolved.get(service_id, DurationStats()),
            )
            for service_id, name in services
        )

    def trend(self, since: datetime, until: datetime) -> tuple[TrendPoint, ...]:
        reported = self.__per_day(IncidentRow.created_at, since, until)
        resolved = self.__per_day(IncidentRow.resolved_at, since, until)
        days = sorted(set(reported) | set(resolved))
        return tuple(TrendPoint(day, reported.get(day, 0), resolved.get(day, 0)) for day in days)

    # ------------------------------------------------------------ internals
    def __durations(
        self, column: Mapped[datetime | None], window: list[ColumnElement[bool]]
    ) -> DurationStats:
        seconds, count = self.__session.execute(
            select(func.sum(self.__elapsed_seconds(column)), func.count())
            .select_from(IncidentRow)
            .where(*window)
            .where(column.is_not(None))
        ).one()
        return DurationStats(timedelta(seconds=float(seconds or 0)), int(count or 0))

    def __elapsed_seconds(self, column: Mapped[datetime | None]) -> ColumnElement[float]:
        """Seconds from creation to ``column``, in whichever dialect is underneath.

        SQLite and PostgreSQL have no shared way to subtract two timestamps, so each is asked
        in its own terms; the division into an average happens in app.domain.analytics either
        way, which is where the rule is tested.
        """
        if self.__dialect == "sqlite":
            return (
                func.julianday(column) - func.julianday(IncidentRow.created_at)
            ) * SECONDS_PER_DAY
        return cast(
            func.extract("epoch", column) - func.extract("epoch", IncidentRow.created_at),
            Float,
        )

    def __per_day(
        self, column: Mapped[datetime | None], since: datetime, until: datetime
    ) -> dict[date, int]:
        rows = self.__session.execute(
            select(IncidentRow.id, column)
            .where(column.is_not(None))
            .where(column >= since)
            .where(column <= until)
        ).all()
        counts: dict[date, int] = {}
        for _, moment in rows:
            if moment is None:
                continue
            day = moment.date()
            counts[day] = counts.get(day, 0) + 1
        return counts


def _since(since: datetime | None) -> list[ColumnElement[bool]]:
    return [] if since is None else [IncidentRow.created_at >= since]


def _flag(condition: ColumnElement[bool]) -> ColumnElement[int]:
    """1 when the condition holds, 0 otherwise, so one query can count several things."""
    return case((condition, 1), else_=0)


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
        self.notifications = SqlAlchemyNotificationRepository(self.__session)
        self.analytics = SqlAlchemyAnalyticsRepository(self.__session)
        self.violations = SqlAlchemySLAViolationRepository(self.__session)

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
