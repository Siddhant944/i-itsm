from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.main import create_app


def test_health_reports_ok_with_reachable_database(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["env"] == "test"


def test_health_reports_degraded_when_database_unreachable() -> None:
    settings = Settings(
        app_env=AppEnv.TEST,
        database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/none?connect_timeout=1",
        _env_file=None,
    )
    with TestClient(create_app(settings)) as client:
        body = client.get("/health").json()

    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    allowed = client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    denied = client.options(
        "/health",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers
