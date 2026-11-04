"""The search a technician or an admin runs (blueprint §9 "Search and reports").

The nine filters plus free text are one immutable value object, so the same query can be
validated once, run against any repository, counted, paged and exported without being
reassembled. Nothing here touches a database.
"""

import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Self

from app.domain.errors import InvalidUserInputError
from app.domain.priority import Priority
from app.domain.sla import SLAStatus
from app.domain.states import IncidentStatus

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 25
MAX_TEXT_LENGTH = 200
CSV_EXPORT_LIMIT = 10_000  # §9: export any filtered list, bounded so one click cannot hurt


class SortField(StrEnum):
    """What a list can be ordered by; the UI offers these columns."""

    CREATED_AT = "created_at"
    PRIORITY = "priority"
    STATUS = "status"
    ID = "id"


@dataclass(frozen=True, slots=True)
class IncidentQuery:
    """The nine filters of §9, plus free text, sorting and one page's worth of paging."""

    text: str | None = None  # free text over the id, title and description
    incident_id: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    statuses: tuple[IncidentStatus, ...] = field(default_factory=tuple)
    priorities: tuple[Priority, ...] = field(default_factory=tuple)
    category_ids: tuple[int, ...] = field(default_factory=tuple)
    service_ids: tuple[int, ...] = field(default_factory=tuple)
    assignee_ids: tuple[int, ...] = field(default_factory=tuple)
    reporter_ids: tuple[int, ...] = field(default_factory=tuple)
    sla_statuses: tuple[SLAStatus, ...] = field(default_factory=tuple)
    sort_by: SortField = SortField.CREATED_AT
    descending: bool = True
    offset: int = 0
    limit: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        errors: dict[str, str] = {}
        # A page is capped at MAX_PAGE_SIZE by the API; the hard ceiling here is the export,
        # which is one unpaged pass over the same filters (§9).
        if self.limit < 1 or self.limit > CSV_EXPORT_LIMIT:
            errors["limit"] = f"Must be 1-{CSV_EXPORT_LIMIT}."
        if self.offset < 0:
            errors["offset"] = "Must not be negative."
        if self.text is not None and len(self.text) > MAX_TEXT_LENGTH:
            errors["text"] = f"At most {MAX_TEXT_LENGTH} characters."
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from > self.created_to
        ):
            errors["created_from"] = "The start of the range must come before its end."
        if errors:
            raise InvalidUserInputError(errors)
        cleaned = self.text.strip() if self.text else None
        object.__setattr__(self, "text", cleaned or None)

    @property
    def is_filtered(self) -> bool:
        """True when any filter narrows the list (an empty query lists everything)."""
        return any(
            (
                self.text,
                self.incident_id,
                self.created_from,
                self.created_to,
                self.statuses,
                self.priorities,
                self.category_ids,
                self.service_ids,
                self.assignee_ids,
                self.reporter_ids,
                self.sla_statuses,
            )
        )

    def for_page(self, offset: int, limit: int | None = None) -> Self:
        return replace(self, offset=offset, limit=limit or self.limit)

    def for_export(self) -> Self:
        """The same filters, unpaged, for the CSV download (§9)."""
        return replace(self, offset=0, limit=CSV_EXPORT_LIMIT)

    def restricted_to_reporter(self, user_id: int) -> Self:
        """BR-01: an employee's search only ever covers their own incidents."""
        return replace(self, reporter_ids=(user_id,))

    def restricted_to_assignee(self, user_id: int) -> Self:
        return replace(self, assignee_ids=(user_id,))

    def restricted_to_assignees(self, user_ids: Sequence[int]) -> Self:
        """Narrow to a set of technicians, e.g. a Team Lead's own team (D-004)."""
        return replace(self, assignee_ids=tuple(user_ids))


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of results and enough context for the pager to render itself."""

    items: tuple[T, ...]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    @property
    def page_number(self) -> int:
        """1-based, for "page 3 of 7"."""
        return self.offset // self.limit + 1 if self.limit else 1

    @property
    def page_count(self) -> int:
        if not self.limit:
            return 1
        return max(1, -(-self.total // self.limit))  # ceiling division

    def map[R](self, convert: Callable[[T], R]) -> "Page[R]":
        """The same page with each item converted, keeping the counts."""
        return Page(
            tuple(convert(item) for item in self.items), self.total, self.offset, self.limit
        )


def empty_page[T](query: IncidentQuery) -> Page[T]:
    return Page((), 0, query.offset, query.limit)


def csv_rows(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Render a CSV the way a spreadsheet expects, quoting what needs quoting."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue()
