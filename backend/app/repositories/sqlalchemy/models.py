"""The eighteen tables that hold the system's state (blueprint §9).

The same declarative models run on SQLite in development and PostgreSQL in deployment, so no
dialect-specific type is used: enums are stored as checked strings with the domain's own values,
timestamps as timezone-aware UTC and durations as whole seconds.

These classes are rows, not domain objects: ``app.repositories.sqlalchemy.mappers`` converts
between them and the aggregates, which keeps SQLAlchemy out of ``app.domain`` (blueprint §2).
"""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.incident import CancelReason, NoteKind
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.sla import SLATier, ViolationKind
from app.domain.states import IncidentStatus
from app.repositories.sqlalchemy.types import Seconds, UtcDateTime

INCIDENT_ID_LENGTH = 20  # INC-YYYY-NNNN
HASH_LENGTH = 64  # SHA-256, hex
MIN_RATING, MAX_RATING = 1, 5

# Predictable constraint names, so Alembic can drop and recreate them on SQLite (batch mode).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _enum(python_type: type[StrEnum], name: str) -> Enum:
    """Store a domain enum as its own string value, with a CHECK constraint on both databases."""
    return Enum(
        python_type,
        name=name,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda enum: [member.value for member in enum],
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this class attribute
        datetime: UtcDateTime,
        timedelta: Seconds,
        dict[str, Any]: JSON,
        list[str]: JSON,
        list[float]: JSON,
    }


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


# ---------------------------------------------------------------- identity
class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    google_subject: Mapped[str | None] = mapped_column(String(64), unique=True)


class TeamRow(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class TechnicianProfileRow(Base):
    """The technician-only fields of a user row (one-to-one with ``users``)."""

    __tablename__ = "technician_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    experience_level: Mapped[int] = mapped_column(Integer, default=1)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)

    __table_args__ = (
        CheckConstraint(
            "experience_level BETWEEN 1 AND 3", name="experience_level_between_1_and_3"
        ),
    )


class SkillRow(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class TechnicianSkillRow(Base):
    __tablename__ = "technician_skills"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("technician_profiles.user_id"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), primary_key=True)


# ---------------------------------------------------------------- catalogue
class CategoryRow(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    required_skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"))
    keywords: Mapped[list[str]] = mapped_column(default=list)
    minimum_priority: Mapped[Priority | None] = mapped_column(_enum(Priority, "priority"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceRow(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    criticality: Mapped[int] = mapped_column(Integer)
    sla_tier: Mapped[SLATier] = mapped_column(_enum(SLATier, "sla_tier"))
    tier_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    # D-002: the service's own required skill, unioned with the category's.
    required_skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("criticality BETWEEN 1 AND 3", name="criticality_between_1_and_3"),
    )


class ServiceDependencyRow(Base):
    """``service_id`` needs ``depends_on_id`` (walked by the correlation engine, §6.2)."""

    __tablename__ = "service_dependencies"

    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), primary_key=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("services.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (CheckConstraint("service_id <> depends_on_id", name="no_self_dependency"),)


class SLAPolicyRow(Base):
    """One row per tier and priority (blueprint §5.2); admins edit the targets."""

    __tablename__ = "sla_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    tier: Mapped[SLATier] = mapped_column(_enum(SLATier, "sla_tier"))
    priority: Mapped[Priority] = mapped_column(_enum(Priority, "priority"))
    response: Mapped[timedelta]
    resolution: Mapped[timedelta]

    __table_args__ = (UniqueConstraint("tier", "priority"),)


# ---------------------------------------------------------------- incidents
class IncidentRow(Base):
    """The incident aggregate flattened: its SLA clock, escalation level and parent id.

    ``version`` carries the optimistic lock: SQLAlchemy raises ``StaleDataError`` when two
    sessions write the same row, which the repository turns into ConcurrentModificationError.
    """

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(INCIDENT_ID_LENGTH), primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(INCIDENT_ID_LENGTH), ForeignKey("incidents.id"), index=True
    )

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    impact: Mapped[int] = mapped_column(Integer)
    urgency: Mapped[int] = mapped_column(Integer)
    status: Mapped[IncidentStatus] = mapped_column(
        _enum(IncidentStatus, "incident_status"), index=True
    )
    priority: Mapped[Priority | None] = mapped_column(_enum(Priority, "priority"), index=True)
    priority_score: Mapped[int | None] = mapped_column(Integer)
    priority_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_reason: Mapped[CancelReason | None] = mapped_column(_enum(CancelReason, "cancel_reason"))

    created_at: Mapped[datetime]
    acknowledged_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)

    # --- SLA clock (absent until the incident is prioritised)
    sla_started_at: Mapped[datetime | None]
    sla_response_target: Mapped[timedelta | None]
    sla_resolution_target: Mapped[timedelta | None]
    sla_responded_at: Mapped[datetime | None]
    sla_paused_total: Mapped[timedelta | None]
    sla_paused_since: Mapped[datetime | None]
    sla_stopped_at: Mapped[datetime | None]
    sla_response_met: Mapped[bool | None]
    sla_resolution_target_at_stop: Mapped[timedelta | None]
    # Derived from the clock and kept by the mapper, so a search can ask "breached?" with a
    # comparison instead of datetime arithmetic SQLite and PostgreSQL spell differently (D-018).
    sla_response_deadline: Mapped[datetime | None]
    sla_response_risk_at: Mapped[datetime | None]
    sla_resolution_deadline: Mapped[datetime | None]
    sla_resolution_risk_at: Mapped[datetime | None]

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # The repository raises the version on every save, so adding a work note contends with a
    # status change: any concurrent edit of the aggregate loses, not just one of the same column.
    __mapper_args__ = {  # noqa: RUF012 - SQLAlchemy configuration
        "version_id_col": version,
        "version_id_generator": False,
    }
    __table_args__ = (
        Index("ix_incidents_status_priority", "status", "priority"),
        Index("ix_incidents_assignee_id_status", "assignee_id", "status"),
        Index("ix_incidents_created_at", "created_at"),
        Index("ix_incidents_status_sla_resolution_deadline", "status", "sla_resolution_deadline"),
        CheckConstraint("impact BETWEEN 1 AND 3", name="impact_between_1_and_3"),
        CheckConstraint("urgency BETWEEN 1 AND 3", name="urgency_between_1_and_3"),
    )


class WorkNoteRow(Base):
    __tablename__ = "work_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(INCIDENT_ID_LENGTH), ForeignKey("incidents.id"), index=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[NoteKind] = mapped_column(_enum(NoteKind, "note_kind"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class ResolutionRow(Base):
    __tablename__ = "resolutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(INCIDENT_ID_LENGTH), ForeignKey("incidents.id"), unique=True
    )
    resolver_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    summary: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime]


class FeedbackRow(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(INCIDENT_ID_LENGTH), ForeignKey("incidents.id"), unique=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    given_at: Mapped[datetime]

    __table_args__ = (
        CheckConstraint(
            f"rating BETWEEN {MIN_RATING} AND {MAX_RATING}", name="rating_between_1_and_5"
        ),
    )


class IncidentEmbeddingRow(Base):
    """A provider-tagged vector for duplicate detection (§6.2); recomputed if the model changes."""

    __tablename__ = "incident_embeddings"

    incident_id: Mapped[str] = mapped_column(
        String(INCIDENT_ID_LENGTH), ForeignKey("incidents.id"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list[float]] = mapped_column(default=list)
    created_at: Mapped[datetime]


class SLAViolationRow(Base):
    """One row per warning or breach per incident cycle, so a tick can never double-report."""

    __tablename__ = "sla_violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(INCIDENT_ID_LENGTH), ForeignKey("incidents.id"), index=True
    )
    kind: Mapped[ViolationKind] = mapped_column(_enum(ViolationKind, "violation_kind"))
    cycle: Mapped[int] = mapped_column(Integer, default=0)  # the incident's reopen count
    deadline: Mapped[datetime]
    detected_at: Mapped[datetime]
    escalated_to_level: Mapped[int | None]

    __table_args__ = (UniqueConstraint("incident_id", "kind", "cycle"),)


# ---------------------------------------------------------------- operations
class AuditRecordRow(Base):
    """Append-only, hash-chained history (blueprint §8, BR-10). Rows are never updated."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[str | None] = mapped_column(
        String(INCIDENT_ID_LENGTH), ForeignKey("incidents.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime]
    previous_hash: Mapped[str | None] = mapped_column(String(HASH_LENGTH))
    hash: Mapped[str] = mapped_column(String(HASH_LENGTH), unique=True)

    __table_args__ = (Index("ix_audit_log_incident_id_id", "incident_id", "id"),)


class NotificationRow(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    incident_id: Mapped[str | None] = mapped_column(
        String(INCIDENT_ID_LENGTH), ForeignKey("incidents.id")
    )
    event: Mapped[str] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[NotificationStatus] = mapped_column(
        _enum(NotificationStatus, "notification_status"), default=NotificationStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]

    __table_args__ = (Index("ix_notifications_user_id_read_at", "user_id", "read_at"),)


class SystemConfigRow(Base):
    """Admin-editable settings: the active assignment strategy, its weights, counters."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


TABLE_COUNT = 18  # blueprint §9
