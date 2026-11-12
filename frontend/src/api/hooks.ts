/**
 * Every server read and write the three portals make, as TanStack Query hooks over the
 * generated client. Screens never call `fetch` or build URLs themselves.
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "./client";
import { liveInterval, POLL_MS } from "../lib/live";

export type Incident = Schemas["IncidentResponse"];
export type IncidentSummary = Schemas["IncidentSummaryResponse"];
export type Service = Schemas["ServiceResponse"];
export type Category = Schemas["CategoryResponse"];
export type SearchFilters = Schemas["SearchFilters"];
export type UserRow = Schemas["UserResponse"];

/** How often open screens re-read live data: slowly while pushes arrive (P4.8). */
export const LIVE_MS = POLL_MS;

// ------------------------------------------------------------------ catalogue and names
export function useServices(includeInactive = false) {
  return useQuery({
    queryKey: ["services", includeInactive],
    queryFn: () =>
      unwrap(
        api.GET("/catalogue/services", {
          params: { query: { include_inactive: includeInactive } },
        }),
      ),
    staleTime: 60_000,
  });
}

export function useCategories(includeInactive = false) {
  return useQuery({
    queryKey: ["categories", includeInactive],
    queryFn: () =>
      unwrap(
        api.GET("/catalogue/categories", {
          params: { query: { include_inactive: includeInactive } },
        }),
      ),
    staleTime: 60_000,
  });
}

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: () => unwrap(api.GET("/catalogue/skills")),
    staleTime: 300_000,
  });
}

export function useTeams() {
  return useQuery({
    queryKey: ["teams"],
    queryFn: () => unwrap(api.GET("/catalogue/teams")),
    staleTime: 60_000,
  });
}

export function useDirectory() {
  return useQuery({
    queryKey: ["directory"],
    queryFn: () => unwrap(api.GET("/users/directory")),
    staleTime: 60_000,
  });
}

/** Lookups that turn the ids in an incident into words. Missing data reads as a dash. */
export function useNames() {
  // Retired rows included: an incident reported before a service was retired still has a name.
  const services = useServices(true);
  const categories = useCategories(true);
  const directory = useDirectory();
  const find = <T extends { id: number }>(rows: T[] | undefined, id: number | null) =>
    id === null ? undefined : rows?.find((row) => row.id === id);
  return {
    // "…" while a list is still loading: a name we do not know yet is not "Uncategorised".
    service: (id: number | null) =>
      services.data === undefined ? "…" : (find(services.data, id)?.name ?? "—"),
    category: (id: number | null) => {
      if (id === null) return "Uncategorised";
      return categories.data === undefined ? "…" : (find(categories.data, id)?.name ?? "—");
    },
    person: (id: number | null) => {
      if (id === null) return "Unassigned";
      // A name that has not arrived yet is not "User 11": say nothing until we know.
      if (directory.data === undefined) return "…";
      return find(directory.data, id)?.full_name ?? `User ${String(id)}`;
    },
  };
}

// ------------------------------------------------------------------ incidents
export function useMyIncidents() {
  return useQuery({
    queryKey: ["incidents", "mine"],
    queryFn: () => unwrap(api.GET("/incidents/mine")),
    refetchInterval: liveInterval,
  });
}

export function useQueue() {
  return useQuery({
    queryKey: ["incidents", "queue"],
    queryFn: () => unwrap(api.GET("/incidents/queue", { params: { query: { limit: 100 } } })),
    refetchInterval: liveInterval,
  });
}

export function useIncident(id: string) {
  return useQuery({
    queryKey: ["incident", id],
    queryFn: () =>
      unwrap(api.GET("/incidents/{incident_id}", { params: { path: { incident_id: id } } })),
    refetchInterval: liveInterval,
  });
}

export function useSearch(filters: SearchFilters, live = false) {
  return useQuery({
    queryKey: ["incidents", "search", filters],
    queryFn: () => unwrap(api.POST("/incidents/search", { body: filters })),
    placeholderData: keepPreviousData,
    refetchInterval: live ? liveInterval : false,
  });
}

export function useAssignmentAdvice(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["incident", id, "advice"],
    queryFn: () =>
      unwrap(
        api.GET("/incidents/{incident_id}/assignment-advice", {
          params: { path: { incident_id: id } },
        }),
      ),
    enabled,
  });
}

function refreshIncidents(client: QueryClient, incident?: Incident) {
  if (incident !== undefined) client.setQueryData(["incident", incident.id], incident);
  void client.invalidateQueries({ queryKey: ["incidents"] });
  void client.invalidateQueries({ queryKey: ["notifications"] });
  void client.invalidateQueries({ queryKey: ["workload"] });
}

export function useReportIncident() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ReportIncidentRequest"]) =>
      unwrap(api.POST("/incidents", { body })),
    onSuccess: (reported) => {
      refreshIncidents(client, reported.incident);
    },
  });
}

/** §6.2: open incidents like the one being typed. Advice only; never links anything. */
export function useSimilar() {
  return useMutation({
    mutationFn: (body: Schemas["SimilarRequest"]) =>
      unwrap(api.POST("/incidents/similar", { body })),
  });
}

/** §6.2: what an open incident may duplicate, for the technician to confirm. */
export function usePossibleDuplicates(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["incident", id, "duplicates"],
    queryFn: () =>
      unwrap(
        api.GET("/incidents/{incident_id}/possible-duplicates", {
          params: { path: { incident_id: id } },
        }),
      ),
    enabled,
  });
}

/** §6.1: past fixes like this incident, and an AI summary citing only them (staff only). */
export function useSuggestedResolution(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["incident", id, "suggested-resolution"],
    queryFn: () =>
      unwrap(
        api.GET("/incidents/{incident_id}/suggested-resolution", {
          params: { path: { incident_id: id } },
        }),
      ),
    enabled,
  });
}

/** §6.3: the predicted breach risk; null when there is nothing to forecast. */
export function useRisk(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["incident", id, "risk"],
    queryFn: () =>
      unwrap(api.GET("/incidents/{incident_id}/risk", { params: { path: { incident_id: id } } })),
    enabled,
    refetchInterval: liveInterval,
  });
}

/** §6.2: the likely root cause and what this incident may be causing (staff only). */
export function useCorrelation(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["incident", id, "correlation"],
    queryFn: () =>
      unwrap(
        api.GET("/incidents/{incident_id}/correlation", {
          params: { path: { incident_id: id } },
        }),
      ),
    enabled,
    refetchInterval: liveInterval,
  });
}

export function useClassify() {
  return useMutation({
    mutationFn: (text: string) => unwrap(api.POST("/incidents/classify", { body: { text } })),
  });
}

/** Everything that can be done to one incident (the twelve lifecycle actions, §4). */
export type IncidentAction =
  | { kind: "acknowledge" | "start" | "resume" | "close" }
  | { kind: "note" | "request-information" | "information"; text: string }
  | { kind: "resolve"; summary: string }
  | { kind: "reject"; reason: string }
  | { kind: "verify"; rating: number; comment: string }
  | { kind: "cancel" }
  | { kind: "reassign"; technicianId: number }
  | { kind: "priority"; priority: Schemas["Priority"]; reason: string }
  | { kind: "category"; categoryId: number }
  | { kind: "confirm-duplicate"; parentId: string };

function perform(id: string, action: IncidentAction): Promise<Incident> {
  const params = { path: { incident_id: id } };
  switch (action.kind) {
    case "acknowledge":
      return unwrap(api.POST("/incidents/{incident_id}/acknowledge", { params }));
    case "start":
      return unwrap(api.POST("/incidents/{incident_id}/start", { params }));
    case "resume":
      return unwrap(api.POST("/incidents/{incident_id}/resume", { params }));
    case "close":
      return unwrap(api.POST("/incidents/{incident_id}/close", { params }));
    case "note":
      return unwrap(
        api.POST("/incidents/{incident_id}/notes", { params, body: { text: action.text } }),
      );
    case "request-information":
      return unwrap(
        api.POST("/incidents/{incident_id}/request-information", {
          params,
          body: { text: action.text },
        }),
      );
    case "information":
      return unwrap(
        api.POST("/incidents/{incident_id}/information", { params, body: { text: action.text } }),
      );
    case "resolve":
      return unwrap(
        api.POST("/incidents/{incident_id}/resolve", { params, body: { summary: action.summary } }),
      );
    case "reject":
      return unwrap(
        api.POST("/incidents/{incident_id}/reject", { params, body: { reason: action.reason } }),
      );
    case "verify":
      return unwrap(
        api.POST("/incidents/{incident_id}/verify", {
          params,
          body: { rating: action.rating, comment: action.comment },
        }),
      );
    case "cancel":
      return unwrap(
        api.POST("/incidents/{incident_id}/cancel", { params, body: { reason: "withdrawn" } }),
      );
    case "reassign":
      return unwrap(
        api.POST("/incidents/{incident_id}/reassign", {
          params,
          body: { technician_id: action.technicianId },
        }),
      );
    case "priority":
      return unwrap(
        api.POST("/incidents/{incident_id}/priority", {
          params,
          body: { priority: action.priority, reason: action.reason },
        }),
      );
    case "category":
      return unwrap(
        api.POST("/incidents/{incident_id}/category", {
          params,
          body: { category_id: action.categoryId },
        }),
      );
    case "confirm-duplicate":
      return unwrap(
        api.POST("/incidents/{incident_id}/confirm-duplicate", {
          params,
          body: { parent_id: action.parentId },
        }),
      );
  }
}

export function useIncidentAction(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: IncidentAction) => perform(id, action),
    onSuccess: (incident) => {
      refreshIncidents(client, incident);
      void client.invalidateQueries({ queryKey: ["incident", id, "advice"] });
      void client.invalidateQueries({ queryKey: ["incident", id, "duplicates"] });
      void client.invalidateQueries({ queryKey: ["incident", id, "risk"] });
      void client.invalidateQueries({ queryKey: ["violations"] });
    },
  });
}

// ------------------------------------------------------------------ notifications
export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () => unwrap(api.GET("/notifications", { params: { query: { limit: 20 } } })),
    refetchInterval: liveInterval,
    enabled,
  });
}

export function useMarkRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.POST("/notifications/{notification_id}/read", {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

// ------------------------------------------------------------------ reports and SLA
export function useWorkload() {
  return useQuery({
    queryKey: ["workload"],
    queryFn: () => unwrap(api.GET("/reports/workload")),
    refetchInterval: liveInterval,
  });
}

export function useDashboard(windowDays: number) {
  return useQuery({
    queryKey: ["dashboard", windowDays],
    queryFn: () =>
      unwrap(api.GET("/reports/dashboard", { params: { query: { window_days: windowDays } } })),
    refetchInterval: () => liveInterval() * 3,
    placeholderData: keepPreviousData,
  });
}

export function useViolations() {
  return useQuery({
    queryKey: ["violations"],
    queryFn: () => unwrap(api.GET("/sla/violations", { params: { query: { limit: 100 } } })),
    refetchInterval: liveInterval,
  });
}

export function useIncidentViolations(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["violations", id],
    queryFn: () =>
      unwrap(api.GET("/sla/violations/{incident_id}", { params: { path: { incident_id: id } } })),
    enabled,
  });
}

function save(text: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * Download one of the API's CSV exports. It goes through the generated client like every
 * other call (the token cannot ride on a plain link), read as text rather than JSON.
 */
export async function downloadCsv(
  path: "/incidents/search/export" | "/reports/workload/export" | "/reports/services/export",
  filename: string,
  body?: SearchFilters,
): Promise<void> {
  const text =
    path === "/incidents/search/export"
      ? await unwrap(api.POST(path, { body: body ?? EVERYTHING, parseAs: "text" }))
      : await unwrap(api.GET(path, { parseAs: "text" }));
  save(typeof text === "string" ? text : "", filename);
}

const EVERYTHING: SearchFilters = { sort_by: "created_at", descending: true, limit: 25, offset: 0 };

// ------------------------------------------------------------------ administration
export function useUsers() {
  return useQuery({ queryKey: ["users"], queryFn: () => unwrap(api.GET("/users")) });
}

function refreshPeople(client: QueryClient) {
  void client.invalidateQueries({ queryKey: ["users"] });
  void client.invalidateQueries({ queryKey: ["directory"] });
  void client.invalidateQueries({ queryKey: ["teams"] });
  void client.invalidateQueries({ queryKey: ["workload"] });
}

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["CreateUserRequest"]) => unwrap(api.POST("/users", { body })),
    onSuccess: () => {
      refreshPeople(client);
    },
  });
}

export function useUpdateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Schemas["UpdateUserRequest"] }) =>
      unwrap(api.PATCH("/users/{user_id}", { params: { path: { user_id: id } }, body })),
    onSuccess: () => {
      refreshPeople(client);
    },
  });
}

export function useSaveCategory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: Schemas["CategoryRequest"] }) =>
      id === null
        ? unwrap(api.POST("/catalogue/categories", { body }))
        : unwrap(
            api.PUT("/catalogue/categories/{category_id}", {
              params: { path: { category_id: id } },
              body,
            }),
          ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["categories"] });
    },
  });
}

export function useSaveService() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: Schemas["ServiceRequest"] }) =>
      id === null
        ? unwrap(api.POST("/catalogue/services", { body }))
        : unwrap(
            api.PUT("/catalogue/services/{service_id}", {
              params: { path: { service_id: id } },
              body,
            }),
          ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["services"] });
    },
  });
}

export function usePolicies() {
  return useQuery({ queryKey: ["policies"], queryFn: () => unwrap(api.GET("/sla/policies")) });
}

export function useSavePolicy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      tier,
      priority,
      body,
    }: {
      tier: Schemas["SLATier"];
      priority: Schemas["Priority"];
      body: Schemas["SLAPolicyRequest"];
    }) =>
      unwrap(
        api.PUT("/sla/policies/{tier}/{priority}", { params: { path: { tier, priority } }, body }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["policies"] });
    },
  });
}

export function useAssignmentSettings() {
  return useQuery({
    queryKey: ["assignment-settings"],
    queryFn: () => unwrap(api.GET("/config/assignment")),
  });
}

export function useSaveAssignmentSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["AssignmentSettingsRequest"]) =>
      unwrap(api.PUT("/config/assignment", { body })),
    onSuccess: (saved) => {
      client.setQueryData(["assignment-settings"], saved);
    },
  });
}

export function useAudit(offset: number, limit: number, incidentId: string) {
  return useQuery({
    queryKey: ["audit", offset, limit, incidentId],
    queryFn: () =>
      unwrap(
        api.GET("/audit", {
          params: {
            query: { offset, limit, ...(incidentId === "" ? {} : { incident_id: incidentId }) },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useVerifyAudit() {
  return useMutation({ mutationFn: () => unwrap(api.POST("/audit/verify")) });
}

export function useRunMonitor() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/sla/tick")),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["violations"] });
      void client.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
}

// ------------------------------------------------------------------ Telegram alerts (P4.9)
export function useTelegramLink() {
  const client = useQueryClient();
  const refreshMe = () => void client.invalidateQueries({ queryKey: ["me"] });
  return {
    link: useMutation({
      mutationFn: (chatId: string) =>
        unwrap(api.PUT("/auth/me/telegram", { body: { chat_id: chatId } })),
      onSuccess: refreshMe,
    }),
    unlink: useMutation({
      mutationFn: () => unwrap(api.DELETE("/auth/me/telegram")),
      onSuccess: refreshMe,
    }),
    test: useMutation({
      mutationFn: () => unwrap(api.POST("/auth/me/telegram/test")),
    }),
  };
}
