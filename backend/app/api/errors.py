"""One ITSMError, one HTTP status, one JSON shape (blueprint §8).

Handlers are registered on the app, so a router never builds an error response and a stack
trace never reaches a client. The status for each group comes straight from the §8 table.
"""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import (
    AssignmentError,
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    InfrastructureError,
    ITSMError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

#: Blueprint §8: the group a specific error belongs to decides its status code.
STATUS_BY_GROUP: tuple[tuple[type[ITSMError], int], ...] = (
    (AuthenticationError, status.HTTP_401_UNAUTHORIZED),
    (AuthorizationError, status.HTTP_403_FORBIDDEN),
    (ValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConflictError, status.HTTP_409_CONFLICT),
    (AssignmentError, status.HTTP_409_CONFLICT),
    (ConfigurationError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (InfrastructureError, status.HTTP_503_SERVICE_UNAVAILABLE),
)


def status_for(error: ITSMError) -> int:
    """The HTTP status for ``error``; an unmapped ITSMError is a server fault, not a leak."""
    for group, code in STATUS_BY_GROUP:
        if isinstance(error, group):
            return code
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def body(code: str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The single error shape the frontend handles."""
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = dict(details)
    return payload


def register_error_handlers(app: FastAPI) -> None:
    """Map every error the API can raise to its response."""

    @app.exception_handler(ITSMError)
    async def _itsm(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, ITSMError)  # noqa: S101 - FastAPI types the handler loosely
        code = status_for(error)
        if code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.error("unhandled ITSM error: %s", error.code, exc_info=error)
        headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None
        return JSONResponse(
            status_code=code,
            content=body(error.code, error.message, error.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)  # noqa: S101 - see above
        fields = {
            ".".join(str(part) for part in item.get("loc", ())[1:]) or "body": str(
                item.get("msg", "Invalid value.")
            )
            for item in error.errors()
        }
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=body("invalid_user_input", "Some fields are invalid.", {"fields": fields}),
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, error: Exception) -> JSONResponse:
        logger.exception("unexpected error", exc_info=error)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=body("internal_error", "Something went wrong. Please try again."),
        )
