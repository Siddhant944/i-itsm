"""The dashboards (blueprint §9 "Search and reports").

One call gives a whole dashboard: the overview cards, the five metrics, the technician
workload table, the service analysis and the trend. The repository counts; the domain value
objects divide; this service decides the window and who is allowed to ask.
"""

from datetime import datetime, timedelta

from app.core.clock import Clock
from app.domain.analytics import (
    Dashboard,
    Metrics,
    Overview,
    ServiceMetrics,
    TechnicianWorkload,
    TrendPoint,
)
from app.domain.errors import InvalidUserInputError, UnauthorizedOperationError
from app.domain.permissions import Permission
from app.domain.repositories import UnitOfWork
from app.domain.search import csv_rows
from app.domain.users import User

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365
WORKLOAD_CSV_HEADER = (
    "Technician",
    "Available",
    "Open incidents",
    "Weighted load",
    "Capacity free %",
    "Resolved",
)
SERVICE_CSV_HEADER = ("Service", "Incidents", "Breached", "Breach %", "Mean time to resolve (h)")


class AnalyticsService:
    """Everything the admin dashboards show, and the technician's own workload."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self.__uow = uow
        self.__clock = clock

    def dashboard(self, actor: User, window_days: int = DEFAULT_WINDOW_DAYS) -> Dashboard:
        """The whole admin dashboard for the last ``window_days`` days."""
        self.__require(actor, Permission.REPORTS_VIEW)
        since = self.__since(window_days)
        now = self.__clock.now()
        return Dashboard(
            overview=self.__uow.analytics.overview(now, since),
            metrics=self.__uow.analytics.metrics(since),
            workload=self.__uow.analytics.workload(),
            services=self.__uow.analytics.by_service(since),
            trend=self.__uow.analytics.trend(since, now),
        )

    def overview(self, actor: User, window_days: int = DEFAULT_WINDOW_DAYS) -> Overview:
        self.__require(actor, Permission.REPORTS_VIEW)
        return self.__uow.analytics.overview(self.__clock.now(), self.__since(window_days))

    def metrics(self, actor: User, window_days: int = DEFAULT_WINDOW_DAYS) -> Metrics:
        """MTTA, MTTR, SLA compliance, CSAT and the reopen rate (§9)."""
        self.__require(actor, Permission.REPORTS_VIEW)
        return self.__uow.analytics.metrics(self.__since(window_days))

    def workload(self, actor: User) -> tuple[TechnicianWorkload, ...]:
        """Every technician's load for a lead or an admin; just their own for a technician."""
        if actor.can(Permission.WORKLOAD_VIEW_TEAM) or actor.can(Permission.REPORTS_VIEW):
            return self.__uow.analytics.workload()
        if actor.can(Permission.WORKLOAD_VIEW_OWN):
            return tuple(
                row for row in self.__uow.analytics.workload() if row.technician_id == actor.id
            )
        raise UnauthorizedOperationError("Your role may not view workloads.")

    def by_service(
        self, actor: User, window_days: int = DEFAULT_WINDOW_DAYS
    ) -> tuple[ServiceMetrics, ...]:
        self.__require(actor, Permission.REPORTS_VIEW)
        return self.__uow.analytics.by_service(self.__since(window_days))

    def trend(self, actor: User, window_days: int = DEFAULT_WINDOW_DAYS) -> tuple[TrendPoint, ...]:
        self.__require(actor, Permission.REPORTS_VIEW)
        return self.__uow.analytics.trend(self.__since(window_days), self.__clock.now())

    # ------------------------------------------------------------ exports (§9)
    def workload_csv(self, actor: User) -> str:
        rows = self.workload(actor)
        return csv_rows(
            WORKLOAD_CSV_HEADER,
            [
                (
                    row.name,
                    "yes" if row.available else "no",
                    row.open_count,
                    row.weighted_load,
                    row.capacity_free,
                    row.resolved,
                )
                for row in rows
            ],
        )

    def services_csv(self, actor: User, window_days: int = DEFAULT_WINDOW_DAYS) -> str:
        rows = self.by_service(actor, window_days)
        return csv_rows(
            SERVICE_CSV_HEADER,
            [
                (
                    row.name,
                    row.incidents,
                    row.breached,
                    row.breach_share,
                    row.resolution.mean_hours,
                )
                for row in rows
            ],
        )

    # ------------------------------------------------------------ internals
    def __since(self, window_days: int) -> datetime:
        if window_days < 1 or window_days > MAX_WINDOW_DAYS:
            raise InvalidUserInputError({"window_days": f"Must be 1-{MAX_WINDOW_DAYS}."})
        return self.__clock.now() - timedelta(days=window_days)

    @staticmethod
    def __require(actor: User, permission: Permission) -> None:
        if not actor.can(permission):
            raise UnauthorizedOperationError(f"Your role may not {permission.value}.")
