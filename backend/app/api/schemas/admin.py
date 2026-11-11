"""Request and response models for the admin screens (blueprint §3, §8)."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.domain.permissions import Role
from app.domain.priority import Priority
from app.domain.sla import SLATier
from app.domain.users import MAX_EXPERIENCE_LEVEL, MIN_EXPERIENCE_LEVEL

MAX_NAME = 120
MAX_KEYWORDS = 50
MAX_MINUTES = 60 * 24 * 30  # a month; nothing in §5.2 comes near it


# ---------------------------------------------------------------- users
class DirectoryEntryResponse(BaseModel):
    """Just enough to show a name beside an id."""

    id: int
    full_name: str
    role: Role


class TechnicianFieldsRequest(BaseModel):
    skills: list[str] = Field(default_factory=list, max_length=20)
    experience_level: int = Field(
        default=MIN_EXPERIENCE_LEVEL, ge=MIN_EXPERIENCE_LEVEL, le=MAX_EXPERIENCE_LEVEL
    )
    available: bool = True
    team_id: int | None = None


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: Role
    active: bool
    skills: list[str] | None = None
    experience_level: int | None = None
    available: bool | None = None
    team_id: int | None = None


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    role: Role
    technician: TechnicianFieldsRequest | None = None


class UpdateUserRequest(BaseModel):
    """Either or both; a field left out is left alone."""

    active: bool | None = None
    role: Role | None = None


# ---------------------------------------------------------------- catalogue
class CategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    required_skill_id: int | None = None
    keywords: list[str] = Field(default_factory=list, max_length=MAX_KEYWORDS)
    minimum_priority: Priority | None = None
    active: bool = True


class ServiceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    criticality: int = Field(ge=1, le=3)
    #: None means "follow the criticality" (3 Gold, 2 Silver, 1 Bronze; §5.2).
    sla_tier: SLATier | None = None
    required_skill_id: int | None = None
    depends_on: list[int] = Field(default_factory=list, max_length=50)
    active: bool = True


# ---------------------------------------------------------------- SLA and assignment
class SLAPolicyResponse(BaseModel):
    tier: SLATier
    priority: Priority
    response_minutes: int
    resolution_minutes: int


class SLAPolicyRequest(BaseModel):
    response_minutes: int = Field(ge=1, le=MAX_MINUTES)
    resolution_minutes: int = Field(ge=1, le=MAX_MINUTES)


class AssignmentWeights(BaseModel):
    """The four weights of §5.3: skill coverage, spare capacity, experience, past fixes."""

    skills: float = Field(ge=0, le=1)
    capacity: float = Field(ge=0, le=1)
    experience: float = Field(ge=0, le=1)
    history: float = Field(ge=0, le=1)


class AssignmentSettingsRequest(BaseModel):
    strategy: str = Field(min_length=1, max_length=40)
    weights: AssignmentWeights


class AssignmentSettingsResponse(BaseModel):
    strategy: str
    weights: AssignmentWeights
    available: list[str]


# ---------------------------------------------------------------- audit
class AuditRecordResponse(BaseModel):
    sequence: int
    occurred_at: datetime
    action: str
    actor_id: int | None
    incident_id: str | None
    details: dict[str, object]
    hash: str


class AuditPageResponse(BaseModel):
    items: list[AuditRecordResponse]
    total: int
    limit: int
    offset: int


class AuditVerificationResponse(BaseModel):
    intact: bool
    checked: int
    broken_at: int | None
    summary: str
