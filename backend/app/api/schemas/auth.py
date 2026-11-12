"""Request and response models for registration and sign-in (blueprint §8)."""

from pydantic import BaseModel, EmailStr, Field

from app.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.domain.permissions import Permission, Role
from app.domain.users import MAX_EXPERIENCE_LEVEL, MIN_EXPERIENCE_LEVEL


class RegisterRequest(BaseModel):
    """Self-registration (D-008). The role is never taken from the request."""

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class LoginRequest(BaseModel):
    """Sign-in. The password is not length-checked here, so a wrong one still counts."""

    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class TokenResponse(BaseModel):
    """A short-lived access token and just enough about the user to render the shell."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth token type, not a secret
    expires_in: int
    user_id: int
    role: Role
    portal: str
    full_name: str


class TechnicianProfileResponse(BaseModel):
    """The technician-only part of ``/me``."""

    skills: list[str]
    experience_level: int = Field(ge=MIN_EXPERIENCE_LEVEL, le=MAX_EXPERIENCE_LEVEL)
    available: bool
    team_id: int | None


class MeResponse(BaseModel):
    """Who the caller is, where they belong and what they may do."""

    id: int
    email: str
    full_name: str
    role: Role
    portal: str
    active: bool
    escalation_level: int | None
    permissions: list[Permission]
    technician: TechnicianProfileResponse | None = None
    #: P4.9: the linked Telegram chat, and whether this deployment can send to Telegram at all.
    telegram_chat_id: str | None = None
    telegram_available: bool = False


class TelegramLinkRequest(BaseModel):
    """The chat to send P1/P2 alerts to; the user finds it by messaging the bot (§5.4)."""

    chat_id: str = Field(min_length=1, max_length=21)
