"""Response models for the catalogue the report form and the admin screens read (§3)."""

from pydantic import BaseModel

from app.domain.priority import Priority
from app.domain.sla import SLATier


class SkillResponse(BaseModel):
    id: int
    name: str


class CategoryResponse(BaseModel):
    id: int
    name: str
    required_skill_id: int | None
    keywords: list[str]
    minimum_priority: Priority | None
    active: bool


class ServiceResponse(BaseModel):
    id: int
    name: str
    criticality: int
    sla_tier: SLATier
    tier_overridden: bool = False
    required_skill_id: int | None
    depends_on: list[int]
    active: bool


class TeamResponse(BaseModel):
    id: int
    name: str
    lead_id: int | None
    member_ids: list[int]
