"""Registration, sign-in and ``/me`` (blueprint §8).

The routers stay thin: validate, call the service, map the result. Every failure leaves through
the ITSMError handlers, so this module has no try/except and no status codes of its own beyond
the ones it declares.
"""

from fastapi import APIRouter, status

from app.api.deps import AuthDep, CurrentUser, NotificationsDep, ServicesDep
from app.api.schemas.auth import (
    GoogleSignInRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    TechnicianProfileResponse,
    TelegramLinkRequest,
    TokenResponse,
)
from app.domain.notifications import ChannelName
from app.domain.permissions import Permission, portal_for
from app.domain.users import Technician, User
from app.services.auth_service import AccessToken

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, auth: AuthDep) -> TokenResponse:
    """Create an Employee account and sign the new user straight in."""
    auth.register(str(payload.email), payload.full_name, payload.password)
    return _token(auth.login(str(payload.email), payload.password))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, auth: AuthDep) -> TokenResponse:
    """Sign in. Five failures lock the account for fifteen minutes (blueprint §8)."""
    return _token(auth.login(payload.email, payload.password))


@router.post("/google", response_model=TokenResponse)
def google(payload: GoogleSignInRequest, auth: AuthDep) -> TokenResponse:
    """Sign in with Google (campus domain only); the first sign-in creates an Employee."""
    return _token(auth.google_sign_in(payload.credential))


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, auth: AuthDep, services: ServicesDep) -> MeResponse:
    """The signed-in user, their portal and their permissions."""
    return _me(user, auth, services)


@router.put("/me/telegram", response_model=MeResponse)
def link_telegram(
    payload: TelegramLinkRequest, user: CurrentUser, auth: AuthDep, services: ServicesDep
) -> MeResponse:
    """Send my P1/P2 alerts to this Telegram chat (§5.4). Audited."""
    return _me(auth.link_telegram(user, payload.chat_id), auth, services)


@router.delete("/me/telegram", response_model=MeResponse)
def unlink_telegram(user: CurrentUser, auth: AuthDep, services: ServicesDep) -> MeResponse:
    """Stop sending my alerts to Telegram."""
    return _me(auth.unlink_telegram(user), auth, services)


@router.post("/me/telegram/test", status_code=status.HTTP_204_NO_CONTENT)
def test_telegram(user: CurrentUser, notifications: NotificationsDep) -> None:
    """Send a test message to my linked chat; 503 if Telegram is down or not set up."""
    notifications.send_test(user, ChannelName.TELEGRAM)


def _token(issued: AccessToken) -> TokenResponse:
    return TokenResponse(
        access_token=issued.token,
        expires_in=issued.expires_in_seconds,
        user_id=issued.user_id,
        role=issued.role,
        portal=issued.portal,
        full_name=issued.full_name,
    )


def _me(user: User, auth: AuthDep, services: ServicesDep) -> MeResponse:
    profile = (
        TechnicianProfileResponse(
            skills=list(user.skills.names),
            experience_level=user.experience_level,
            available=user.available,
            team_id=user.team_id,
        )
        if isinstance(user, Technician)
        else None
    )
    return MeResponse(
        id=user.id,
        email=str(user.email),
        full_name=user.full_name,
        role=user.role,
        portal=portal_for(user.role).value,
        active=user.active,
        escalation_level=user.escalation_level,
        permissions=[Permission(name) for name in auth.permissions(user)],
        technician=profile,
        telegram_chat_id=user.telegram_chat_id,
        telegram_available=services.telegram is not None,
    )
