/**
 * The single typed API client. Every call goes through it (AGENTS.md: Frontend).
 * Types come from schema.d.ts, generated from the backend's OpenAPI document by `make gen-client`.
 */
import createClient, { type Middleware } from "openapi-fetch";

import { syncServerTime } from "../lib/serverTime";
import { getToken, setToken } from "../lib/session";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

const configuredBaseUrl = import.meta.env.VITE_API_URL;

/**
 * Where the API lives: VITE_API_URL when set (a separately hosted API), otherwise `/api` on the
 * page's own origin, which the Vite dev proxy and nginx both forward with the prefix removed.
 */
export const apiBaseUrl =
  configuredBaseUrl !== undefined && configuredBaseUrl !== ""
    ? configuredBaseUrl
    : `${window.location.origin}/api`;

/** Raised for any failed call so TanStack Query surfaces it as an error state. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: Readonly<Record<string, string>>;

  constructor(
    status: number,
    message: string,
    code = "error",
    fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
  }

  /** True when the server could not be reached at all (offline, or the API is down). */
  get offline(): boolean {
    return this.status === 0;
  }
}

const session: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token !== null) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ request, response }) {
    syncServerTime(response.headers.get("X-Server-Time"), response.headers.get("X-Clock-Rate"));
    // An expired or revoked token: forget it, and the auth provider sends the user to sign in.
    if (response.status === 401 && request.headers.has("Authorization")) setToken(null);
    return response;
  },
};

// fetch is looked up per call (not captured at import) so tests can stub it.
export const api = createClient<paths>({
  baseUrl: apiBaseUrl,
  fetch: (request) => globalThis.fetch(request),
});
api.use(session);

interface Result<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringRecord(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  const out: Record<string, string> = {};
  for (const [key, problem] of Object.entries(value)) {
    if (typeof problem === "string") out[key] = problem;
  }
  return out;
}

/** Turn the API's one error shape (blueprint §8) into an ApiError. */
export function toApiError(status: number, body: unknown): ApiError {
  const error = isRecord(body) && isRecord(body.error) ? body.error : null;
  if (error === null) return new ApiError(status, `The request failed (${String(status)}).`);
  const message = typeof error.message === "string" ? error.message : "The request failed.";
  const code = typeof error.code === "string" ? error.code : "error";
  const details = isRecord(error.details) ? error.details : {};
  const fields = { ...stringRecord(details.fields), ...stringRecord(details.field_errors) };
  return new ApiError(status, message, code, fields);
}

/** Await a client call and return its data, or throw an ApiError. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await call;
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection and try again.");
  }
  if (!result.response.ok) throw toApiError(result.response.status, result.error);
  return result.data as T;
}

/** A sentence for any thrown value, for error states and toasts. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const fields = Object.values(error.fieldErrors);
    return fields.length > 0 ? `${error.message} ${fields.join(" ")}` : error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}
