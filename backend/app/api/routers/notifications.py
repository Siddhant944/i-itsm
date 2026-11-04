"""The notification bell (blueprint §5.4): read your own, and mark them read."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, NotificationsDep
from app.api.schemas.notifications import NotificationResponse, NotificationSummaryResponse
from app.domain.notifications import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])
MAX_PAGE = 100


@router.get("", response_model=NotificationSummaryResponse)
def bell(
    user: CurrentUser,
    notifications: NotificationsDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
) -> NotificationSummaryResponse:
    """The caller's own unread count and latest in-app notifications."""
    summary = notifications.summary(user, limit=limit)
    return NotificationSummaryResponse(
        unread=summary.unread, latest=[_response(n) for n in summary.latest]
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: int, user: CurrentUser, notifications: NotificationsDep
) -> NotificationResponse:
    """Mark one of the caller's own notifications read; somebody else's is a 403."""
    return _response(notifications.mark_read(user, notification_id))


def _response(notification: Notification) -> NotificationResponse:
    assert notification.id is not None  # noqa: S101 - stored notifications always have an id
    return NotificationResponse(
        id=notification.id,
        event=notification.event,
        channel=notification.channel,
        subject=notification.subject,
        body=notification.body,
        incident_id=notification.incident_id,
        created_at=notification.created_at,
        read_at=notification.read_at,
        status=notification.status,
    )
