"""Reading the catalogue (blueprint §3).

Every signed-in user needs the services and categories to report an incident, so these are
plain reads behind authentication. Editing them is an admin screen and arrives with P3.4.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, UowDep
from app.api.schemas.catalogue import (
    CategoryResponse,
    ServiceResponse,
    SkillResponse,
    TeamResponse,
)

router = APIRouter(prefix="/catalogue", tags=["catalogue"])


@router.get("/services", response_model=list[ServiceResponse])
def services(user: CurrentUser, uow: UowDep) -> list[ServiceResponse]:
    """The services someone can report an incident against."""
    return [
        ServiceResponse(
            id=service.id,
            name=service.name,
            criticality=service.criticality,
            sla_tier=service.sla_tier,
            required_skill_id=service.required_skill_id,
            depends_on=list(service.depends_on),
            active=service.active,
        )
        for service in uow.catalogue.services(active_only=True)
    ]


@router.get("/categories", response_model=list[CategoryResponse])
def categories(user: CurrentUser, uow: UowDep) -> list[CategoryResponse]:
    """The categories, with the keywords the rule-based classifier uses (§6.1)."""
    return [
        CategoryResponse(
            id=category.id,
            name=category.name,
            required_skill_id=category.required_skill_id,
            keywords=list(category.keywords),
            minimum_priority=category.minimum_priority,
            active=category.active,
        )
        for category in uow.catalogue.categories(active_only=True)
    ]


@router.get("/skills", response_model=list[SkillResponse])
def skills(user: CurrentUser, uow: UowDep) -> list[SkillResponse]:
    return [SkillResponse(id=skill.id, name=skill.name) for skill in uow.catalogue.skills()]


@router.get("/teams", response_model=list[TeamResponse])
def teams(user: CurrentUser, uow: UowDep) -> list[TeamResponse]:
    return [
        TeamResponse(
            id=team.id,
            name=team.name,
            lead_id=team.lead_id,
            member_ids=list(team.member_ids),
        )
        for team in uow.catalogue.teams()
    ]
