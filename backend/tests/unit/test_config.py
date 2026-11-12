import logging
import re
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import DEV_JWT_SECRET, AppEnv, Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def test_env_example_lists_every_setting() -> None:
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE.read_text(), re.MULTILINE))
    backend_keys = {name for name in documented if not name.startswith("VITE_")}

    assert backend_keys == {name.upper() for name in Settings.model_fields}


def test_production_refuses_the_dev_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(app_env=AppEnv.PROD, _env_file=None)


def test_production_refuses_a_short_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(app_env=AppEnv.PROD, jwt_secret=SecretStr("too-short"), _env_file=None)


def test_copied_env_example_keeps_defaults_for_empty_values() -> None:
    settings = Settings(_env_file=ENV_EXAMPLE)

    assert settings.jwt_secret.get_secret_value() == DEV_JWT_SECRET
    assert settings.gemini_api_key is None
    assert settings.smtp_password is None
    assert settings.telegram_bot_token is None


def test_copied_env_example_cannot_run_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=ENV_EXAMPLE)


WEB = ["https://i-itsm-web.onrender.com"]


def test_production_accepts_a_real_secret() -> None:
    settings = Settings(
        app_env=AppEnv.PROD,
        jwt_secret=SecretStr("x" * 48),
        cors_origins=WEB,
        _env_file=None,
    )
    assert settings.app_env is AppEnv.PROD


@pytest.mark.parametrize(
    "origins",
    [
        ["*"],
        ["http://localhost:5173"],
        [],
        ["https://i-itsm-web.onrender.com", "*"],
        ["https://i-itsm-web.onrender.com/"],
        ["https://i-itsm-web.onrender.com/login"],
        ["https://"],
    ],
)
def test_production_locks_cors_to_https_origins(origins: list[str]) -> None:
    """P5.1: no wildcard, no plain http, and not the localhost default."""
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(
            app_env=AppEnv.PROD,
            jwt_secret=SecretStr("x" * 48),
            cors_origins=origins,
            _env_file=None,
        )


def test_other_environments_keep_the_local_cors_default() -> None:
    assert Settings(app_env=AppEnv.DEMO, _env_file=None).cors_origins == ["http://localhost:5173"]


def test_http_client_loggers_never_print_request_urls_which_carry_the_bot_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """P4 review: httpx logs every request URL at INFO; Telegram's URL contains the token."""
    import httpx

    from app.core.logging import configure_logging

    configure_logging("INFO")
    secret = "123456:SECRET-TOKEN"
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    with caplog.at_level(logging.INFO):
        client.post(f"https://api.telegram.org/bot{secret}/sendMessage", json={})
    assert secret not in caplog.text
