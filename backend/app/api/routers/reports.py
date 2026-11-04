"""Search, CSV export and the dashboards (blueprint §9).

Search is a POST because the nine filters do not fit comfortably in a query string, and
because a saved search is a body the frontend can keep. Every result is scoped to the caller
by the service, so BR-01 holds no matter what filters were sent.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from app.api.deps import AnalyticsDep, CurrentUser, SearchDep, ServicesDep, requires
from app.api.schemas.incidents import summary_of
from app.api.schemas.reports import (
    DashboardResponse,
    IncidentPageResponse,
    MetricsResponse,
    OverviewResponse,
    SearchFilters,
    ServiceRowResponse,
    TrendPointResponse,
    Window,
    WorkloadRowResponse,
)
from app.domain.analytics import (
    Dashboard,
    Metrics,
    Overview,
    ServiceMetrics,
    TechnicianWorkload,
    TrendPoint,
)
from app.domain.permissions import Permission
from app.domain.search import IncidentQuery
from app.domain.users import User

router = APIRouter(tags=["reports"])
CSV_MEDIA_TYPE = "text/csv"


def _query(filters: SearchFilters) -> IncidentQuery:
    """The validated body as the domain's own query object."""
    return IncidentQuery(
        text=filters.text,
        incident_id=filters.incident_id,
        created_from=filters.created_from,
        created_to=filters.created_to,
        statuses=tuple(filters.statuses),
        priorities=tuple(filters.priorities),
        category_ids=tuple(filters.category_ids),
        service_ids=tuple(filters.service_ids),
        assignee_ids=tuple(filters.assignee_ids),
        reporter_ids=tuple(filters.reporter_ids),
        sla_statuses=tuple(filters.sla_statuses),
        sort_by=filters.sort_by,
        descending=filters.descending,
        offset=filters.offset,
        limit=filters.limit,
    )


@router.post("/incidents/search", response_model=IncidentPageResponse)
def search(
    filters: SearchFilters,
    user: CurrentUser,
    search_service: SearchDep,
    services: ServicesDep,
) -> IncidentPageResponse:
    """The nine filters plus free text, paged. Scoped to what the caller may see (BR-01)."""
    page = search_service.search(user, _query(filters))
    return IncidentPageResponse(
        items=[summary_of(incident, services.clock) for incident in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
        page_number=page.page_number,
        page_count=page.page_count,
        has_more=page.has_more,
    )


@router.post(
    "/incidents/search/export",
    response_class=PlainTextResponse,
    responses={200: {"content": {CSV_MEDIA_TYPE: {}}, "description": "The filtered list as CSV"}},
)
def export(
    filters: SearchFilters, user: CurrentUser, search_service: SearchDep
) -> PlainTextResponse:
    """The same filtered list as a CSV download (§9)."""
    return PlainTextResponse(
        content=search_service.export_csv(user, _query(filters)),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="incidents.csv"'},
    )


@router.get("/reports/dashboard", response_model=DashboardResponse)
def dashboard(
    user: Annotated[User, Depends(requires(Permission.REPORTS_VIEW))],
    analytics: AnalyticsDep,
    window_days: Annotated[Window, Query()] = 30,
) -> DashboardResponse:
    """Everything the admin dashboard shows, in one call."""
    return _dashboard(analytics.dashboard(user, window_days), window_days)


@router.get("/reports/overview", response_model=OverviewResponse)
def overview(
    user: Annotated[User, Depends(requires(Permission.REPORTS_VIEW))],
    analytics: AnalyticsDep,
    window_days: Annotated[Window, Query()] = 30,
) -> OverviewResponse:
    return _overview(analytics.overview(user, window_days))


@router.get("/reports/metrics", response_model=MetricsResponse)
def metrics(
    user: Annotated[User, Depends(requires(Permission.REPORTS_VIEW))],
    analytics: AnalyticsDep,
    window_days: Annotated[Window, Query()] = 30,
) -> MetricsResponse:
    """MTTA, MTTR, SLA compliance, CSAT and the reopen rate."""
    return _metrics(analytics.metrics(user, window_days))


@router.get("/reports/workload", response_model=list[WorkloadRowResponse])
def workload(user: CurrentUser, analytics: AnalyticsDep) -> list[WorkloadRowResponse]:
    """Every technician's load for a lead or an admin; a technician sees only their own."""
    return [_workload_row(row) for row in analytics.workload(user)]


@router.get("/reports/services", response_model=list[ServiceRowResponse])
def services(
    user: Annotated[User, Depends(requires(Permission.REPORTS_VIEW))],
    analytics: AnalyticsDep,
    window_days: Annotated[Window, Query()] = 30,
) -> list[ServiceRowResponse]:
    return [_service_row(row) for row in analytics.by_service(user, window_days)]


@router.get("/reports/trend", response_model=list[TrendPointResponse])
def trend(
    user: Annotated[User, Depends(requires(Permission.REPORTS_VIEW))],
    analytics: AnalyticsDep,
    window_days: Annotated[Window, Query()] = 30,
) -> list[TrendPointResponse]:
    return [_trend_point(point) for point in analytics.trend(user, window_days)]


@router.get(
    "/reports/workload/export",
    response_class=PlainTextResponse,
    responses={200: {"content": {CSV_MEDIA_TYPE: {}}, "description": "Workload as CSV"}},
)
def workload_csv(user: CurrentUser, analytics: AnalyticsDep) -> PlainTextResponse:
    return PlainTextResponse(
        content=analytics.workload_csv(user),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="workload.csv"'},
    )


@router.get(
    "/reports/services/export",
    response_class=PlainTextResponse,
    responses={200: {"content": {CSV_MEDIA_TYPE: {}}, "description": "Service analysis as CSV"}},
)
def services_csv(
    user: Annotated[User, Depends(requires(Permission.REPORTS_VIEW))],
    analytics: AnalyticsDep,
    window_days: Annotated[Window, Query()] = 30,
) -> PlainTextResponse:
    return PlainTextResponse(
        content=analytics.services_csv(user, window_days),
        media_type=CSV_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="services.csv"'},
    )


# ---------------------------------------------------------------- mapping helpers
def _overview(overview: Overview) -> OverviewResponse:
    return OverviewResponse(
        total=overview.total,
        open_count=overview.open_count,
        unassigned=overview.unassigned,
        awaiting_reporter=overview.awaiting_reporter,
        breached=overview.breached,
        at_risk=overview.at_risk,
        critical_open=overview.critical_open,
        resolved_in_window=overview.resolved_in_window,
        open_share=overview.open_share,
        breached_share=overview.breached_share,
    )


def _metrics(metrics: Metrics) -> MetricsResponse:
    return MetricsResponse(
        mtta_hours=metrics.acknowledgement.mean_hours,
        mttr_hours=metrics.resolution.mean_hours,
        acknowledged=metrics.acknowledgement.count,
        resolved=metrics.resolution.count,
        sla_compliance=metrics.sla_compliance,
        sla_measured=metrics.sla_measured,
        csat=metrics.csat,
        csat_responses=metrics.satisfaction.responses,
        reopen_rate=metrics.reopen_rate,
        reopened=metrics.reopened,
    )


def _workload_row(row: TechnicianWorkload) -> WorkloadRowResponse:
    return WorkloadRowResponse(
        technician_id=row.technician_id,
        name=row.name,
        available=row.available,
        open_count=row.open_count,
        weighted_load=row.weighted_load,
        max_load=row.max_load,
        capacity_free=row.capacity_free,
        at_capacity=row.at_capacity,
        resolved=row.resolved,
    )


def _service_row(row: ServiceMetrics) -> ServiceRowResponse:
    return ServiceRowResponse(
        service_id=row.service_id,
        name=row.name,
        incidents=row.incidents,
        breached=row.breached,
        breach_share=row.breach_share,
        mttr_hours=row.resolution.mean_hours,
    )


def _trend_point(point: TrendPoint) -> TrendPointResponse:
    return TrendPointResponse(day=point.day, reported=point.reported, resolved=point.resolved)


def _dashboard(dashboard: Dashboard, window_days: int) -> DashboardResponse:
    return DashboardResponse(
        window_days=window_days,
        overview=_overview(dashboard.overview),
        metrics=_metrics(dashboard.metrics),
        workload=[_workload_row(row) for row in dashboard.workload],
        services=[_service_row(row) for row in dashboard.services],
        trend=[_trend_point(point) for point in dashboard.trend],
    )
