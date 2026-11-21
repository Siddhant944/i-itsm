"""Request and response models for the notification bell (blueprint §5.4)."""

from datetime import datetime

from pydantic import BaseModel

from app.domain.notifications import ChannelName, DeliveryStatus, NotificationEvent


class NotificationResponse(BaseModel):
    id: int
    event: NotificationEvent
    channel: ChannelName
    subject: str
    body: str
    incident_id: str | None
    #: The incident's title, so the bell names the incident (None when it is unknown).
    incident_title: str | None = None
    created_at: datetime
    read_at: datetime | None
    status: DeliveryStatus


class NotificationSummaryResponse(BaseModel):
    """What the bell shows: the unread count and the latest few."""

    unread: int
    latest: list[NotificationResponse]
