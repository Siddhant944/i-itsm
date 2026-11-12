"""Application settings, read once from the environment (and an optional, untracked ``.env``).

Every variable is listed in ``.env.example``; a test keeps the two in sync.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"  # noqa: S105 - documented dev default
MIN_PROD_SECRET_LENGTH = 32
# The one optional .env file, at the repository root (absent inside Docker images).
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class AppEnv(StrEnum):
    """Deployment environment; ``test`` and ``demo`` enable the clock-control endpoint (D-009)."""

    DEV = "dev"
    TEST = "test"
    DEMO = "demo"
    PROD = "prod"


class ClockMode(StrEnum):
    """Which Clock implementation the app uses (blueprint §5.2)."""

    SYSTEM = "system"
    ACCELERATED = "accelerated"
    #: Stands still until ``/dev/clock`` moves it; only for tests and the demo (D-009).
    FAKE = "fake"


class Settings(BaseSettings):
    """Typed settings. Secrets are ``SecretStr`` so they never appear in logs or reprs."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    # --- application
    app_env: AppEnv = AppEnv.DEV
    app_name: str = "I-ITSM"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./itsm.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    frontend_url: str = "http://localhost:5173"

    # --- auth (blueprint §8)
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_access_ttl_minutes: int = 30
    allowed_email_domains: list[str] = Field(default_factory=list)

    # --- clock (blueprint §5.2, §14)
    clock_mode: ClockMode = ClockMode.SYSTEM
    clock_acceleration: float = 10.0
    #: D-003: the SLA monitor ticks every 30 s of clock time. 0 disables the scheduler.
    sla_tick_seconds: int = 30

    # --- Gemini (blueprint §6)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = ""
    gemini_embedding_model: str = ""

    # --- email (blueprint §5.4); console fallback when SMTP_HOST is empty
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = "I-ITSM <no-reply@localhost>"
    smtp_starttls: bool = True

    # --- Telegram (blueprint §5.4)
    telegram_bot_token: SecretStr | None = None

    # --- Google Sign-In (blueprint §8)
    google_client_id: str = ""
    google_hd_domain: str = ""

    @property
    def clock_control_enabled(self) -> bool:
        """D-009: ``/dev/clock`` exists only in the test and demo environments."""
        return self.app_env in (AppEnv.TEST, AppEnv.DEMO)

    @model_validator(mode="after")
    def _refuse_a_fake_clock_in_prod(self) -> Self:
        if self.app_env is AppEnv.PROD and self.clock_mode is ClockMode.FAKE:
            msg = "CLOCK_MODE=fake is for tests and the demo, never for prod"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _refuse_weak_secret_in_prod(self) -> Self:
        secret = self.jwt_secret.get_secret_value()
        if self.app_env is AppEnv.PROD and (
            secret == DEV_JWT_SECRET or len(secret) < MIN_PROD_SECRET_LENGTH
        ):
            msg = f"JWT_SECRET must be set to at least {MIN_PROD_SECRET_LENGTH} characters in prod"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _lock_cors_in_prod(self) -> Self:
        """P5.1: in prod the browser may call the API only from the deployed web app's origin."""
        if self.app_env is not AppEnv.PROD:
            return self
        loose = [o for o in self.cors_origins if not _is_https_origin(o)]
        if not self.cors_origins or loose:
            msg = (
                "CORS_ORIGINS must list the web app's https:// origin(s) in prod"
                f" (refused: {loose or 'an empty list'})"
            )
            raise ValueError(msg)
        return self


def _is_https_origin(value: str) -> bool:
    """An origin as browsers send it: ``https://host[:port]``, with no path and no slash.

    ``https://web.example.com/`` (copied from the address bar) never equals the ``Origin``
    header, so accepting it would let the API start and then refuse every sign-in (P5 review).
    """
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and bool(parts.netloc)
        and not (parts.path or parts.query or parts.fragment)
        and not value.endswith("/")
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached)."""
    return Settings()
