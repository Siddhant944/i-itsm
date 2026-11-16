import { useState } from "react";

import type { Schemas } from "../../api/client";
import { downloadCsv, useCategories, useDirectory, useSearch, useServices } from "../../api/hooks";
import { Button } from "../../components/Button";
import { ChipGroup, SelectField, TextField } from "../../components/Field";
import { FilterBar } from "../../components/FilterBar";
import { IncidentTable } from "../../components/IncidentTable";
import { EmptyState, PageHeader, QueryView } from "../../components/States";
import { useToasts } from "../../components/Toasts";
import {
  ALL_PRIORITIES,
  ALL_SLA_STATUSES,
  ALL_STATUSES,
  priorityLabel,
  slaLabel,
  statusLabel,
} from "../../lib/format";
import { usePortal } from "../../lib/usePortal";
import { incidentPath } from "../../shell/nav";
import { countActive, EMPTY_DRAFT, PAGE_SIZE, toFilters, type Draft } from "./searchFilters";

/** Search every incident with the nine §9 filters, page through the result, export it. */
export function SearchPage() {
  const portal = usePortal();
  const toasts = useToasts();
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [applied, setApplied] = useState<Draft>(EMPTY_DRAFT);
  const [offset, setOffset] = useState(0);
  const [exporting, setExporting] = useState(false);
  const services = useServices(true);
  const categories = useCategories(true);
  const directory = useDirectory();
  const result = useSearch(toFilters(applied, offset));

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };
  const staff = (directory.data ?? []).filter((person) => person.role !== "employee");

  const exportCsv = () => {
    setExporting(true);
    downloadCsv("/incidents/search/export", "incidents.csv", toFilters(applied, 0))
      .catch((error: unknown) => {
        toasts.error(error);
      })
      .finally(() => {
        setExporting(false);
      });
  };

  return (
    <>
      <PageHeader title="Incidents" subtitle="Search every incident, then export what you find." />
      <FilterBar
        activeCount={countActive(applied)}
        onApply={() => {
          setApplied(draft);
          setOffset(0);
        }}
        onReset={() => {
          setDraft(EMPTY_DRAFT);
          setApplied(EMPTY_DRAFT);
          setOffset(0);
        }}
        extra={
          <Button busy={exporting} onClick={exportCsv}>
            Export CSV
          </Button>
        }
      >
        <TextField
          label="Text"
          placeholder="Words in the title or description"
          value={draft.text}
          onChange={(event) => {
            set("text", event.target.value);
          }}
        />
        <TextField
          label="Incident ID"
          placeholder="INC-2026-0001"
          value={draft.incidentId}
          onChange={(event) => {
            set("incidentId", event.target.value);
          }}
        />
        <div className="grid grid-cols-2 gap-2">
          <TextField
            label="Reported from"
            type="date"
            value={draft.from}
            onChange={(event) => {
              set("from", event.target.value);
            }}
          />
          <TextField
            label="Reported to"
            type="date"
            value={draft.to}
            onChange={(event) => {
              set("to", event.target.value);
            }}
          />
        </div>
        <ChipGroup
          label="Status"
          options={ALL_STATUSES.map((value) => ({ value, label: statusLabel(value) }))}
          selected={draft.statuses}
          onChange={(next) => {
            set("statuses", next);
          }}
        />
        <ChipGroup
          label="Priority"
          options={ALL_PRIORITIES.map((value) => ({ value, label: priorityLabel(value) }))}
          selected={draft.priorities}
          onChange={(next) => {
            set("priorities", next);
          }}
        />
        <ChipGroup
          label="SLA status"
          options={ALL_SLA_STATUSES.map((value) => ({ value, label: slaLabel(value) }))}
          selected={draft.slaStatuses}
          onChange={(next) => {
            set("slaStatuses", next);
          }}
        />
        <SelectField
          label="Category"
          value={draft.categoryId}
          onChange={(event) => {
            set("categoryId", event.target.value);
          }}
        >
          <option value="">Any category</option>
          {categories.data?.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </SelectField>
        <SelectField
          label="Service"
          value={draft.serviceId}
          onChange={(event) => {
            set("serviceId", event.target.value);
          }}
        >
          <option value="">Any service</option>
          {services.data?.map((service) => (
            <option key={service.id} value={service.id}>
              {service.name}
            </option>
          ))}
        </SelectField>
        <div className="grid grid-cols-2 gap-2">
          <SelectField
            label="Assigned to"
            value={draft.assigneeId}
            onChange={(event) => {
              set("assigneeId", event.target.value);
            }}
          >
            <option value="">Anyone</option>
            {staff.map((person) => (
              <option key={person.id} value={person.id}>
                {person.full_name}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="Reported by"
            value={draft.reporterId}
            onChange={(event) => {
              set("reporterId", event.target.value);
            }}
          >
            <option value="">Anyone</option>
            {directory.data?.map((person) => (
              <option key={person.id} value={person.id}>
                {person.full_name}
              </option>
            ))}
          </SelectField>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <SelectField
            label="Sort by"
            value={draft.sortBy}
            onChange={(event) => {
              set("sortBy", event.target.value as Schemas["SortField"]);
            }}
          >
            <option value="created_at">Reported date</option>
            <option value="priority">Priority</option>
            <option value="status">Status</option>
            <option value="id">Incident ID</option>
          </SelectField>
          <SelectField
            label="Order"
            value={draft.descending ? "desc" : "asc"}
            onChange={(event) => {
              set("descending", event.target.value === "desc");
            }}
          >
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </SelectField>
        </div>
      </FilterBar>

      <QueryView
        query={result}
        loadingLabel="Searching"
        isEmpty={(page) => page.total === 0}
        empty={
          <EmptyState
            title="No incidents match these filters"
            hint="Remove a filter or widen the dates."
          />
        }
      >
        {(page) => (
          <>
            <p className="mb-2 text-sm text-muted" data-testid="result-count">
              {String(page.total)} incident{page.total === 1 ? "" : "s"} · page{" "}
              {String(page.page_number)} of {String(page.page_count)}
            </p>
            <IncidentTable
              caption="Search results"
              incidents={page.items}
              hrefFor={(id) => incidentPath(portal, id)}
              show={["category", "assignee"]}
              sortable={false}
            />
            <div className="mt-3 flex items-center gap-2">
              <Button
                disabled={page.offset === 0}
                onClick={() => {
                  setOffset(Math.max(0, page.offset - PAGE_SIZE));
                }}
              >
                Previous
              </Button>
              <Button
                disabled={!page.has_more}
                onClick={() => {
                  setOffset(page.offset + PAGE_SIZE);
                }}
              >
                Next
              </Button>
            </div>
          </>
        )}
      </QueryView>
    </>
  );
}
