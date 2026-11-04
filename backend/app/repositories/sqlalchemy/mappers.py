"""Row ↔ aggregate conversion (the Data Mapper half of the Repository pattern).

The domain knows nothing about SQLAlchemy, so this module is the only place that understands
both sides. Aggregates are rebuilt through their own named constructors
(``Incident.restore``, ``SLAClock.restore``, ``UserFactory.create``), never by writing to
their private attributes.
"""

from datetime import datetime, timedelta

from app.domain.audit import AuditAction, AuditRecord
from app.domain.catalogue import Category, ITService, Skill, Team
from app.domain.credentials import Credentials
from app.domain.incident import Feedback, Incident, Resolution, WorkNote
from app.domain.notifications import (
    ChannelName,
    DeliveryStatus,
    Notification,
    NotificationEvent,
)
from app.domain.sla import SLAClock, SLATarget
from app.domain.users import Technician, User, UserFactory
from app.domain.value_objects import SkillSet
from app.repositories.sqlalchemy.models import (
    AuditRecordRow,
    CategoryRow,
    FeedbackRow,
    IncidentRow,
    NotificationRow,
    NotificationStatus,
    ResolutionRow,
    ServiceRow,
    SkillRow,
    TeamRow,
    TechnicianProfileRow,
    UserRow,
    WorkNoteRow,
)

# ---------------------------------------------------------------- users


def new_user_row(user: User, created_at: datetime) -> UserRow:
    """A fresh users row. The registration timestamp comes from the repository's Clock, because
    a domain User does not carry one."""
    return user_to_row(user, UserRow(id=user.id, created_at=created_at))


def user_to_row(user: User, row: UserRow) -> UserRow:
    """Fill ``row`` with the domain-owned fields of ``user``.

    Credentials and the lockout counters belong to authentication (blueprint §8), so they are
    never written from a domain user.
    """
    row.id = user.id
    row.email = str(user.email)
    row.full_name = user.full_name
    row.role = user.role
    row.active = user.active
    return row


def technician_profile_to_row(
    technician: Technician, row: TechnicianProfileRow | None = None
) -> TechnicianProfileRow:
    row = row or TechnicianProfileRow(user_id=technician.id)
    row.experience_level = technician.experience_level
    row.available = technician.available
    row.team_id = technician.team_id
    return row


def row_to_user(
    row: UserRow, profile: TechnicianProfileRow | None = None, skills: SkillSet | None = None
) -> User:
    """Rebuild the right User subclass for the stored role (blueprint §3)."""
    if not UserFactory.is_support_role(row.role):
        return UserFactory.create(
            row.role,
            user_id=row.id,
            email=row.email,
            full_name=row.full_name,
            active=row.active,
        )
    return UserFactory.create(
        row.role,
        user_id=row.id,
        email=row.email,
        full_name=row.full_name,
        active=row.active,
        skills=skills or SkillSet(),
        experience_level=profile.experience_level if profile else None,
        available=profile.available if profile else None,
        team_id=profile.team_id if profile else None,
    )


def credentials_to_row(credentials: Credentials, row: UserRow) -> UserRow:
    """Write only the sign-in columns, so saving credentials never touches the profile."""
    row.password_hash = credentials.password_hash
    row.failed_login_count = credentials.failed_attempts
    row.locked_until = credentials.locked_until
    row.last_login_at = credentials.last_login_at
    return row


def row_to_credentials(row: UserRow) -> Credentials:
    return Credentials(
        user_id=row.id,
        password_hash=row.password_hash,
        failed_attempts=row.failed_login_count,
        locked_until=row.locked_until,
        last_login_at=row.last_login_at,
    )


def audit_to_row(record: AuditRecord) -> AuditRecordRow:
    return AuditRecordRow(
        incident_id=record.incident_id,
        actor_id=record.actor_id,
        action=record.action.value,
        details=dict(record.details),
        created_at=record.occurred_at,
        previous_hash=record.previous_hash,
        hash=record.hash,
    )


def row_to_audit(row: AuditRecordRow) -> AuditRecord:
    return AuditRecord(
        previous_hash=row.previous_hash,
        occurred_at=row.created_at,
        action=AuditAction(row.action),
        actor_id=row.actor_id,
        incident_id=row.incident_id,
        details=dict(row.details),
        hash=row.hash,
    )


def notification_to_row(
    notification: Notification, row: NotificationRow | None = None
) -> NotificationRow:
    row = row or NotificationRow(
        user_id=notification.user_id,
        incident_id=notification.incident_id,
        event=notification.event.value,
        channel=notification.channel.value,
        created_at=notification.created_at,
    )
    row.subject = notification.subject
    row.body = notification.body
    row.status = NotificationStatus(notification.status.value)
    row.attempts = notification.attempts
    row.sent_at = notification.sent_at
    row.read_at = notification.read_at
    return row


def row_to_notification(row: NotificationRow) -> Notification:
    return Notification(
        notification_id=row.id,
        user_id=row.user_id,
        event=NotificationEvent(row.event),
        channel=ChannelName(row.channel),
        subject=row.subject,
        body=row.body,
        created_at=row.created_at,
        incident_id=row.incident_id,
        status=DeliveryStatus(row.status.value),
        attempts=row.attempts,
        sent_at=row.sent_at,
        read_at=row.read_at,
    )


# ---------------------------------------------------------------- catalogue


def skill_to_row(skill: Skill, row: SkillRow | None = None) -> SkillRow:
    row = row or SkillRow(id=skill.id)
    row.name = skill.name
    return row


def row_to_skill(row: SkillRow) -> Skill:
    return Skill(row.id, row.name)


def category_to_row(category: Category, row: CategoryRow | None = None) -> CategoryRow:
    row = row or CategoryRow(id=category.id)
    row.name = category.name
    row.required_skill_id = category.required_skill_id
    row.keywords = list(category.keywords)
    row.minimum_priority = category.minimum_priority
    row.active = category.active
    return row


def row_to_category(row: CategoryRow) -> Category:
    return Category(
        row.id,
        row.name,
        required_skill_id=row.required_skill_id,
        keywords=tuple(row.keywords),
        minimum_priority=row.minimum_priority,
        active=row.active,
    )


def service_to_row(service: ITService, row: ServiceRow | None = None) -> ServiceRow:
    row = row or ServiceRow(id=service.id)
    row.name = service.name
    row.criticality = service.criticality
    row.sla_tier = service.sla_tier
    row.tier_overridden = service.tier_overridden
    row.required_skill_id = service.required_skill_id
    row.active = service.active
    return row


def row_to_service(row: ServiceRow, depends_on: tuple[int, ...] = ()) -> ITService:
    return ITService(
        row.id,
        row.name,
        criticality=row.criticality,
        sla_tier=row.sla_tier if row.tier_overridden else None,
        required_skill_id=row.required_skill_id,
        depends_on=depends_on,
        active=row.active,
    )


def team_to_row(team: Team, row: TeamRow | None = None) -> TeamRow:
    row = row or TeamRow(id=team.id)
    row.name = team.name
    row.lead_id = team.lead_id
    return row


def row_to_team(row: TeamRow, member_ids: tuple[int, ...] = ()) -> Team:
    return Team.restore(row.id, row.name, lead_id=row.lead_id, member_ids=member_ids)


# ---------------------------------------------------------------- incidents


def incident_to_row(incident: Incident, row: IncidentRow | None = None) -> IncidentRow:
    """Flatten the aggregate, SLA clock included, onto one row (blueprint §9)."""
    row = row or IncidentRow(id=incident.id, created_at=incident.created_at, version=1)
    row.reporter_id = incident.reporter_id
    row.assignee_id = incident.assignee_id
    row.category_id = incident.category_id
    row.service_id = incident.service_id
    row.parent_id = incident.parent_id
    row.title = incident.title
    row.description = incident.description
    row.impact = incident.impact
    row.urgency = incident.urgency
    row.status = incident.status
    row.priority = incident.priority
    row.priority_score = incident.priority_score
    row.priority_overridden = incident.priority_overridden
    row.cancel_reason = incident.cancel_reason
    row.acknowledged_at = incident.acknowledged_at
    row.resolved_at = incident.resolved_at
    row.closed_at = incident.closed_at
    row.reopen_count = incident.reopen_count
    row.escalation_level = incident.escalation_level
    _sla_to_row(incident.sla_clock, row)
    return row


def _sla_to_row(clock: SLAClock | None, row: IncidentRow) -> None:
    if clock is None:
        row.sla_started_at = None
        row.sla_response_target = None
        row.sla_resolution_target = None
        row.sla_responded_at = None
        row.sla_paused_total = None
        row.sla_paused_since = None
        row.sla_stopped_at = None
        row.sla_response_met = None
        row.sla_resolution_target_at_stop = None
        return
    row.sla_started_at = clock.started_at
    row.sla_response_target = clock.target.response
    row.sla_resolution_target = clock.target.resolution
    row.sla_responded_at = clock.responded_at
    row.sla_paused_total = clock.paused_accumulated
    row.sla_paused_since = clock.paused_since
    row.sla_stopped_at = clock.stopped_at
    row.sla_response_met = clock.response_met
    row.sla_resolution_target_at_stop = clock.resolution_target_at_stop


def row_to_sla_clock(row: IncidentRow) -> SLAClock | None:
    """Rebuild the SLA clock, or None when the incident has not been prioritised yet."""
    if (
        row.sla_started_at is None
        or row.sla_response_target is None
        or row.sla_resolution_target is None
    ):
        return None
    return SLAClock.restore(
        started_at=row.sla_started_at,
        target=SLATarget(row.sla_response_target, row.sla_resolution_target),
        responded_at=row.sla_responded_at,
        paused_total=row.sla_paused_total or timedelta(),
        paused_since=row.sla_paused_since,
        stopped_at=row.sla_stopped_at,
        response_met=row.sla_response_met,
        resolution_target_at_stop=row.sla_resolution_target_at_stop,
    )


def note_to_row(note: WorkNote, incident_id: str) -> WorkNoteRow:
    return WorkNoteRow(
        incident_id=incident_id,
        author_id=note.author_id,
        kind=note.kind,
        text=note.text,
        created_at=note.created_at,
    )


def row_to_note(row: WorkNoteRow) -> WorkNote:
    return WorkNote(row.author_id, row.created_at, row.kind, row.text)


def resolution_to_row(
    resolution: Resolution, incident_id: str, row: ResolutionRow | None = None
) -> ResolutionRow:
    row = row or ResolutionRow(incident_id=incident_id)
    row.resolver_id = resolution.resolver_id
    row.summary = resolution.summary
    row.resolved_at = resolution.resolved_at
    return row


def row_to_resolution(row: ResolutionRow) -> Resolution:
    return Resolution(row.resolver_id, row.resolved_at, row.summary)


def feedback_to_row(
    feedback: Feedback, incident_id: str, row: FeedbackRow | None = None
) -> FeedbackRow:
    row = row or FeedbackRow(incident_id=incident_id)
    row.rating = feedback.rating
    row.comment = feedback.comment
    row.given_at = feedback.given_at
    return row


def row_to_feedback(row: FeedbackRow) -> Feedback:
    return Feedback(row.rating, row.comment, row.given_at)


def row_to_incident(
    row: IncidentRow,
    notes: tuple[WorkNote, ...] = (),
    resolution: Resolution | None = None,
    feedback: Feedback | None = None,
) -> Incident:
    return Incident.restore(
        incident_id=row.id,
        reporter_id=row.reporter_id,
        title=row.title,
        description=row.description,
        service_id=row.service_id,
        impact=row.impact,
        urgency=row.urgency,
        created_at=row.created_at,
        status=row.status,
        category_id=row.category_id,
        assignee_id=row.assignee_id,
        parent_id=row.parent_id,
        cancel_reason=row.cancel_reason,
        acknowledged_at=row.acknowledged_at,
        resolved_at=row.resolved_at,
        closed_at=row.closed_at,
        reopen_count=row.reopen_count,
        escalation_level=row.escalation_level,
        priority=row.priority,
        priority_score=row.priority_score,
        priority_overridden=row.priority_overridden,
        sla_clock=row_to_sla_clock(row),
        notes=notes,
        resolution=resolution,
        feedback=feedback,
    )
