"""Request-scoped dependencies (blueprint §2, §8).

The composition root puts the built pieces — the session factory, the clock, the hasher, the
token service and the auth policy — on ``app.state``; these dependencies turn them into one
Unit of Work per request and one authenticated user per protected route.

Authorisation is a dependency, never a check inside a handler, so a route cannot forget it.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.clock import Clock
from app.core.security import PasswordHasher, TokenService
from app.domain.errors import InvalidLoginError
from app.domain.permissions import Permission
from app.domain.repositories import UnitOfWork
from app.domain.users import User
from app.services.audit import AuditService
from app.services.auth_service import AuthPolicy, AuthService

#: ``auto_error=False`` so a missing header becomes our own 401 body, not FastAPI's.
bearer = HTTPBearer(auto_error=False, scheme_name="Bearer")


@dataclass(frozen=True, slots=True)
class Services:
    """Everything built once at start-up and shared by every request."""

    unit_of_work: Callable[[], UnitOfWork]
    clock: Clock
    hasher: PasswordHasher
    tokens: TokenService
    policy: AuthPolicy


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


def get_uow(services: ServicesDep) -> Iterator[UnitOfWork]:
    """One Unit of Work per request, rolled back and closed however the request ends."""
    uow = services.unit_of_work()
    try:
        yield uow
    finally:
        uow.rollback()
        uow.close()


UowDep = Annotated[UnitOfWork, Depends(get_uow)]


def get_auth_service(services: ServicesDep, uow: UowDep) -> AuthService:
    return AuthService(uow, services.hasher, services.tokens, services.clock, services.policy)


AuthDep = Annotated[AuthService, Depends(get_auth_service)]


def get_audit_service(services: ServicesDep, uow: UowDep) -> AuditService:
    return AuditService(uow.audit, services.clock)


AuditDep = Annotated[AuditService, Depends(get_audit_service)]


def get_current_user(
    auth: AuthDep,
    token: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    """The signed-in user, or 401. Every protected route depends on this."""
    if token is None or not token.credentials:
        raise InvalidLoginError("Sign in to continue.")
    return auth.authenticate(token.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def requires(permission: Permission) -> Callable[[User, AuthService], User]:
    """A dependency that refuses the request with 403 unless the role grants ``permission``.

    Used as ``Depends(requires(Permission.AUDIT_VERIFY))`` so the check is declared on the
    route, is visible in the OpenAPI document, and is impossible to skip by accident.
    """

    def dependency(user: CurrentUser, auth: AuthDep) -> User:
        auth.require(user, permission)
        return user

    return dependency
