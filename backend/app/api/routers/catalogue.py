"""Reading the catalogue (blueprint §3).

Every signed-in user needs the services and categories to report an incident, so these are
plain reads behind authentication. Editing them needs ``catalogue:manage`` and is audited.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import ConfigurationDep, CurrentUser, UowDep, requires
from app.api.schemas.admin import CategoryRequest, ServiceRequest
from app.api.schemas.catalogue import (
    CategoryResponse,
    ServiceResponse,
    SkillResponse,
    TeamResponse,
)
from app.domain.catalogue import Category, ITService
from app.domain.permissions import Permission
from app.domain.users import User
from app.services.configuration import CategoryChange, ServiceChange

router = APIRouter(prefix="/catalogue", tags=["catalogue"])

Manager = Annotated[User, Depends(requires(Permission.CATALOGUE_MANAGE))]


@router.get("/services", response_model=list[ServiceResponse])
def services(
    user: CurrentUser, uow: UowDep, include_inactive: bool = False
) -> list[ServiceResponse]:
    """The services someone can report an incident against.

    ``include_inactive`` adds the retired ones, flagged ``active: false``. Every screen needs
    them to name the service of an incident reported before it was retired; the report form
    offers only the active ones.
    """
    return [_service(s) for s in uow.catalogue.services(active_only=not include_inactive)]


@router.post("/services", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
def create_service(
    body: ServiceRequest, user: Manager, configuration: ConfigurationDep
) -> ServiceResponse:
    return _service(configuration.create_service(user, _service_change(body)))


@router.put("/services/{service_id}", response_model=ServiceResponse)
def update_service(
    service_id: int, body: ServiceRequest, user: Manager, configuration: ConfigurationDep
) -> ServiceResponse:
    return _service(configuration.update_service(user, service_id, _service_change(body)))


@router.get("/categories", response_model=list[CategoryResponse])
def categories(
    user: CurrentUser, uow: UowDep, include_inactive: bool = False
) -> list[CategoryResponse]:
    """The categories, with the keywords the rule-based classifier uses (§6.1)."""
    return [_category(c) for c in uow.catalogue.categories(active_only=not include_inactive)]


@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryRequest, user: Manager, configuration: ConfigurationDep
) -> CategoryResponse:
    """A new category is live at once: the classifier reads its keywords on the next report."""
    return _category(configuration.create_category(user, _category_change(body)))


@router.put("/categories/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: int, body: CategoryRequest, user: Manager, configuration: ConfigurationDep
) -> CategoryResponse:
    return _category(configuration.update_category(user, category_id, _category_change(body)))


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


def _service(service: ITService) -> ServiceResponse:
    return ServiceResponse(
        id=service.id,
        name=service.name,
        criticality=service.criticality,
        sla_tier=service.sla_tier,
        tier_overridden=service.tier_overridden,
        required_skill_id=service.required_skill_id,
        depends_on=list(service.depends_on),
        active=service.active,
    )


def _category(category: Category) -> CategoryResponse:
    return CategoryResponse(
        id=category.id,
        name=category.name,
        required_skill_id=category.required_skill_id,
        keywords=list(category.keywords),
        minimum_priority=category.minimum_priority,
        active=category.active,
    )


def _service_change(body: ServiceRequest) -> ServiceChange:
    return ServiceChange(
        name=body.name,
        criticality=body.criticality,
        sla_tier=body.sla_tier,
        required_skill_id=body.required_skill_id,
        depends_on=tuple(body.depends_on),
        active=body.active,
    )


def _category_change(body: CategoryRequest) -> CategoryChange:
    return CategoryChange(
        name=body.name,
        required_skill_id=body.required_skill_id,
        keywords=tuple(body.keywords),
        minimum_priority=body.minimum_priority,
        active=body.active,
    )
