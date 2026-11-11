"""Accounts (blueprint §3, §8): the name directory and the admin's user screen."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, UserAdminDep, requires
from app.api.schemas.admin import (
    CreateUserRequest,
    DirectoryEntryResponse,
    TechnicianFieldsRequest,
    UpdateUserRequest,
    UserResponse,
)
from app.domain.permissions import Permission
from app.domain.users import Technician, User
from app.services.user_admin import TechnicianFields

router = APIRouter(prefix="/users", tags=["users"])

UserManager = Annotated[User, Depends(requires(Permission.USERS_MANAGE))]
TechnicianManager = Annotated[User, Depends(requires(Permission.TECHNICIANS_MANAGE))]


@router.get("/directory", response_model=list[DirectoryEntryResponse])
def directory(user: CurrentUser, admin: UserAdminDep) -> list[DirectoryEntryResponse]:
    """Names for the ids on a screen; an employee is shown support staff only (BR-01)."""
    return [
        DirectoryEntryResponse(id=entry.id, full_name=entry.full_name, role=entry.role)
        for entry in admin.directory(user)
    ]


@router.get("", response_model=list[UserResponse])
def everyone(user: UserManager, admin: UserAdminDep) -> list[UserResponse]:
    return [_response(found) for found in admin.everyone()]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create(body: CreateUserRequest, user: UserManager, admin: UserAdminDep) -> UserResponse:
    """Create an account with any role; self-registration only makes Employees (D-008)."""
    created = admin.create(
        user,
        email=str(body.email),
        full_name=body.full_name,
        password=body.password,
        role=body.role,
        technician=_fields(body.technician) if body.technician else None,
    )
    return _response(created)


@router.patch("/{user_id}", response_model=UserResponse)
def update(
    user_id: int, body: UpdateUserRequest, user: UserManager, admin: UserAdminDep
) -> UserResponse:
    """Switch an account on or off, or give it another role."""
    changed = admin.get(user_id)
    if body.role is not None:
        changed = admin.change_role(user, user_id, body.role)
    if body.active is not None:
        changed = admin.set_active(user, user_id, active=body.active)
    return _response(changed)


@router.put("/{user_id}/technician", response_model=UserResponse)
def update_technician(
    user_id: int, body: TechnicianFieldsRequest, user: TechnicianManager, admin: UserAdminDep
) -> UserResponse:
    """A technician's skills, experience, availability and team (§5.3 reads all four)."""
    return _response(admin.update_technician(user, user_id, _fields(body)))


def _fields(body: TechnicianFieldsRequest) -> TechnicianFields:
    return TechnicianFields(
        skills=tuple(body.skills),
        experience_level=body.experience_level,
        available=body.available,
        team_id=body.team_id,
    )


def _response(user: User) -> UserResponse:
    response = UserResponse(
        id=user.id,
        email=str(user.email),
        full_name=user.full_name,
        role=user.role,
        active=user.active,
    )
    if isinstance(user, Technician):
        response.skills = list(user.skills.names)
        response.experience_level = user.experience_level
        response.available = user.available
        response.team_id = user.team_id
    return response
