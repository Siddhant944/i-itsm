"""Request-scoped dependencies (blueprint §2, §8).

The composition root puts the built pieces — the session factory, the clock, the hasher, the
token service and the auth policy — on ``app.state``; these dependencies turn them into one
Unit of Work per request and one authenticated user per protected route.

Authorisation is a dependency, never a check inside a handler, so a route cannot forget it.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.clock import Clock
from app.core.security import PasswordHasher, TokenService
from app.domain.errors import InvalidLoginError, ITSMError
from app.domain.permissions import Permission
from app.domain.ports import AIAdvisor, EmailSender, EmbeddingProvider, ResolutionSummarizer
from app.domain.repositories import UnitOfWork
from app.domain.similarity import TfIdfEmbeddings
from app.domain.users import User
from app.services.analytics import AnalyticsService
from app.services.audit import AuditService
from app.services.auth_service import AuthPolicy, AuthService
from app.services.configuration import ConfigurationService, active_strategy
from app.services.dispatcher import PostCommitDispatcher
from app.services.duplicates import DuplicateDetector
from app.services.incident_service import IncidentService
from app.services.notifications import EmailChannel, default_factory
from app.services.notifications.service import NotificationService
from app.services.resolution_advisor import ResolutionAdvisor
from app.services.search import SearchService
from app.services.sla_monitor import SLAMonitor
from app.services.user_admin import UserAdminService

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
    email: EmailSender
    advisor: AIAdvisor
    #: §6.2: Gemini when configured; TF-IDF offline, and always the fallback.
    embeddings: EmbeddingProvider = field(default_factory=TfIdfEmbeddings)
    #: §6.1: Gemini summarises past fixes when configured; without it the list stands alone.
    summarizer: ResolutionSummarizer | None = None


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


def get_notification_service(services: ServicesDep, uow: UowDep) -> NotificationService:
    """The notification service for this request, with the channels this deployment has."""
    channels = default_factory(
        email=EmailChannel(services.email, lambda user_id: _address(uow, user_id))
    )
    return NotificationService(uow, services.clock, channels)


NotificationsDep = Annotated[NotificationService, Depends(get_notification_service)]


def _address(uow: UnitOfWork, user_id: int) -> str | None:
    """A recipient's email, or None when the account has gone."""
    try:
        return str(uow.users.get(user_id).email)
    except ITSMError:
        return None


def get_incident_service(
    services: ServicesDep, uow: UowDep, notifications: NotificationsDep
) -> IncidentService:
    """The facade, with notifications wired to fire only after the commit (§5.4)."""
    return IncidentService(
        uow,
        services.clock,
        dispatcher=PostCommitDispatcher([notifications.on_event]),
        advisor=services.advisor,
        # §5.3: the admin's saved choice, read per request so a switch takes effect at once.
        assignment_strategy=active_strategy(uow.settings),
        duplicates=DuplicateDetector(uow, services.clock, services.embeddings),
        resolutions=ResolutionAdvisor(uow, services.clock, services.summarizer),
    )


IncidentsDep = Annotated[IncidentService, Depends(get_incident_service)]


def get_configuration_service(services: ServicesDep, uow: UowDep) -> ConfigurationService:
    return ConfigurationService(uow, services.clock)


ConfigurationDep = Annotated[ConfigurationService, Depends(get_configuration_service)]


def get_user_admin_service(services: ServicesDep, uow: UowDep) -> UserAdminService:
    return UserAdminService(uow, services.clock, services.hasher)


UserAdminDep = Annotated[UserAdminService, Depends(get_user_admin_service)]


def get_search_service(services: ServicesDep, uow: UowDep) -> SearchService:
    return SearchService(uow, services.clock)


SearchDep = Annotated[SearchService, Depends(get_search_service)]


def get_analytics_service(services: ServicesDep, uow: UowDep) -> AnalyticsService:
    return AnalyticsService(uow, services.clock)


AnalyticsDep = Annotated[AnalyticsService, Depends(get_analytics_service)]


def get_sla_monitor(
    services: ServicesDep, uow: UowDep, notifications: NotificationsDep
) -> SLAMonitor:
    """The monitor for this request, notifying through the §5.4 channels after its tick."""
    return SLAMonitor(uow, services.clock, notify=notifications.notify)


MonitorDep = Annotated[SLAMonitor, Depends(get_sla_monitor)]


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
