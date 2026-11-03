"""Liveness and readiness endpoint."""

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app import __version__
from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health status of the API and its database."""

    status: Literal["ok", "degraded"]
    app: str
    version: str
    env: str
    database: Literal["ok", "unreachable"]


def get_db_probe(request: Request) -> Callable[[], bool]:
    """Return the database probe wired by the composition root (``app.main``)."""
    probe: Callable[[], bool] = request.app.state.db_probe
    return probe


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Annotated[Settings, Depends(get_settings)],
    db_probe: Annotated[Callable[[], bool], Depends(get_db_probe)],
) -> HealthResponse:
    """Report whether the API is up and the database reachable."""
    db_ok = db_probe()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        app=settings.app_name,
        version=__version__,
        env=settings.app_env.value,
        database="ok" if db_ok else "unreachable",
    )
