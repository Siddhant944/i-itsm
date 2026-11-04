"""Request and response models for search and the dashboards (blueprint §9)."""

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.api.schemas.incidents import IncidentSummaryResponse
from app.domain.priority import Priority
from app.domain.search import MAX_PAGE_SIZE, MAX_TEXT_LENGTH, SortField
from app.domain.sla import SLAStatus
from app.domain.states import IncidentStatus

Window = Annotated[int, Field(ge=1, le=365, description="How many days the figures cover")]


class SearchFilters(BaseModel):
    """The nine filters of §9 plus free text, sorting and paging, as one query body."""

    text: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    incident_id: str | None = Field(default=None, max_length=20)
    created_from: datetime | None = None
    created_to: datetime | None = None
    statuses: list[IncidentStatus] = Field(default_factory=list)
    priorities: list[Priority] = Field(default_factory=list)
    category_ids: list[int] = Field(default_factory=list)
    service_ids: list[int] = Field(default_factory=list)
    assignee_ids: list[int] = Field(default_factory=list)
    reporter_ids: list[int] = Field(default_factory=list)
    sla_statuses: list[SLAStatus] = Field(default_factory=list)
    sort_by: SortField = SortField.CREATED_AT
    descending: bool = True
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=MAX_PAGE_SIZE)


class IncidentPageResponse(BaseModel):
    """One page of results, with what the pager needs to draw itself."""

    items: list[IncidentSummaryResponse]
    total: int
    offset: int
    limit: int
    page_number: int
    page_count: int
    has_more: bool


class OverviewResponse(BaseModel):
    total: int
    open_count: int
    unassigned: int
    awaiting_reporter: int
    breached: int
    at_risk: int
    critical_open: int
    resolved_in_window: int
    open_share: float
    breached_share: float


class MetricsResponse(BaseModel):
    """The five figures §9 names, with None where there is nothing to average yet."""

    mtta_hours: float | None
    mttr_hours: float | None
    acknowledged: int
    resolved: int
    sla_compliance: float
    sla_measured: int
    csat: float | None
    csat_responses: int
    reopen_rate: float
    reopened: int


class WorkloadRowResponse(BaseModel):
    technician_id: int
    name: str
    available: bool
    open_count: int
    weighted_load: int
    max_load: int
    capacity_free: float
    at_capacity: bool
    resolved: int


class ServiceRowResponse(BaseModel):
    service_id: int
    name: str
    incidents: int
    breached: int
    breach_share: float
    mttr_hours: float | None


class TrendPointResponse(BaseModel):
    day: date
    reported: int
    resolved: int


class DashboardResponse(BaseModel):
    """Everything an admin dashboard shows, in one call."""

    window_days: int
    overview: OverviewResponse
    metrics: MetricsResponse
    workload: list[WorkloadRowResponse]
    services: list[ServiceRowResponse]
    trend: list[TrendPointResponse]
