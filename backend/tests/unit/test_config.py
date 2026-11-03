import re
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import AppEnv, Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def test_env_example_lists_every_setting() -> None:
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE.read_text(), re.MULTILINE))
    backend_keys = {name for name in documented if not name.startswith("VITE_")}

    assert backend_keys == {name.upper() for name in Settings.model_fields}


def test_production_refuses_the_dev_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(app_env=AppEnv.PROD, _env_file=None)


def test_production_accepts_a_real_secret() -> None:
    settings = Settings(
        app_env=AppEnv.PROD,
        jwt_secret=SecretStr("a-long-random-production-secret"),
        _env_file=None,
    )
    assert settings.app_env is AppEnv.PROD
