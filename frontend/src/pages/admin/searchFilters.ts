import type { Schemas } from "../../api/client";
import type { SearchFilters } from "../../api/hooks";

export const PAGE_SIZE = 25;

/** The form's own state; dates stay as the strings the inputs produce until they are applied. */
export interface Draft {
  text: string;
  incidentId: string;
  statuses: Schemas["IncidentStatus"][];
  priorities: Schemas["Priority"][];
  slaStatuses: Schemas["SLAStatus"][];
  categoryId: string;
  serviceId: string;
  assigneeId: string;
  reporterId: string;
  from: string;
  to: string;
  sortBy: Schemas["SortField"];
  descending: boolean;
}

export const EMPTY_DRAFT: Draft = {
  text: "",
  incidentId: "",
  statuses: [],
  priorities: [],
  slaStatuses: [],
  categoryId: "",
  serviceId: "",
  assigneeId: "",
  reporterId: "",
  from: "",
  to: "",
  sortBy: "created_at",
  descending: true,
};

/** A date from an <input type="date"> is an IST calendar day; the API wants UTC instants. */
function istDay(day: string, endOfDay: boolean): string | null {
  if (day === "") return null;
  const instant = new Date(`${day}T${endOfDay ? "23:59:59.999" : "00:00:00.000"}+05:30`);
  return Number.isNaN(instant.getTime()) ? null : instant.toISOString();
}

const one = (value: string) => (value === "" ? [] : [Number(value)]);

/** The nine §9 filters plus free text, as the API's request body. */
export function toFilters(draft: Draft, offset: number): SearchFilters {
  return {
    text: draft.text.trim() === "" ? null : draft.text.trim(),
    incident_id: draft.incidentId.trim() === "" ? null : draft.incidentId.trim(),
    statuses: draft.statuses,
    priorities: draft.priorities,
    sla_statuses: draft.slaStatuses,
    category_ids: one(draft.categoryId),
    service_ids: one(draft.serviceId),
    assignee_ids: one(draft.assigneeId),
    reporter_ids: one(draft.reporterId),
    created_from: istDay(draft.from, false),
    created_to: istDay(draft.to, true),
    sort_by: draft.sortBy,
    descending: draft.descending,
    limit: PAGE_SIZE,
    offset,
  };
}

export function countActive(draft: Draft): number {
  return [
    draft.text.trim() !== "",
    draft.incidentId.trim() !== "",
    draft.statuses.length > 0,
    draft.priorities.length > 0,
    draft.slaStatuses.length > 0,
    draft.categoryId !== "",
    draft.serviceId !== "",
    draft.assigneeId !== "",
    draft.reporterId !== "",
    draft.from !== "" || draft.to !== "",
  ].filter(Boolean).length;
}
