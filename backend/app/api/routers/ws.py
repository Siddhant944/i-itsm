"""The live-update socket (blueprint §6.4, P4.8).

Browsers cannot put an Authorization header on a WebSocket, and a token in the URL ends up in
logs, so the first message carries it: ``{"token": "<access token>"}``. Anything else, or
nothing within ten seconds, closes the socket with 4401. After that the server only talks:
``{"type": "ready"}``, then ``{"type": "incident", "incident_id": …, "status": …}`` whenever
something the user may care about changes. The browser refetches through the API.
"""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import Services
from app.core.security import TokenService
from app.domain.errors import ITSMError
from app.domain.permissions import Permission
from app.domain.users import User
from app.services.auth_service import AuthService
from app.services.live import Subscription

router = APIRouter(tags=["live"])

AUTH_TIMEOUT_SECONDS = 10.0
#: Application close code: "sign in again" (4000-4999 are ours to define).
UNAUTHORISED = 4401


@router.websocket("/ws")
async def live(socket: WebSocket) -> None:
    services: Services = socket.app.state.services
    await socket.accept()
    try:
        first = await asyncio.wait_for(socket.receive_json(), AUTH_TIMEOUT_SECONDS)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        await _close(socket)
        return
    token = first.get("token") if isinstance(first, dict) else None
    user = await asyncio.to_thread(_authenticate, services, token)
    if user is None:
        await _close(socket)
        return

    subscription = services.live.subscribe(
        user.id,
        watches_all=user.can(Permission.INCIDENT_VIEW_ALL)
        or user.can(Permission.INCIDENT_VIEW_TEAM),
    )
    try:
        await socket.send_json({"type": "ready"})
        await _serve(socket, subscription)
    finally:
        services.live.unsubscribe(subscription)


async def _serve(socket: WebSocket, subscription: Subscription) -> None:
    """Forward queued messages until the browser goes away."""

    async def send() -> None:
        while True:
            await socket.send_json(await subscription.queue.get())

    async def listen() -> None:
        with contextlib.suppress(WebSocketDisconnect):
            while True:
                await socket.receive_text()  # pings, or the close frame

    sender, listener = asyncio.create_task(send()), asyncio.create_task(listen())
    await asyncio.wait({sender, listener}, return_when=asyncio.FIRST_COMPLETED)
    for task in (sender, listener):
        task.cancel()
        # A browser that vanished mid-send is the normal way for this to end.
        with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await task


def _authenticate(services: Services, token: object) -> User | None:
    if not isinstance(token, str) or not token:
        return None
    uow = services.unit_of_work()
    try:
        tokens: TokenService = services.tokens
        auth = AuthService(uow, services.hasher, tokens, services.clock, services.policy)
        user = auth.authenticate(token)
        return user if user.active else None
    except ITSMError:
        return None
    finally:
        uow.rollback()
        uow.close()


async def _close(socket: WebSocket) -> None:
    """Close with 4401, unless the browser has already gone (React remounts in development)."""
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await socket.close(code=UNAUTHORISED)
