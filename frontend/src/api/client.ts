/**
 * The single typed API client. Every call goes through it (AGENTS.md: Frontend).
 * Types come from schema.d.ts, generated from the backend's OpenAPI document by `make gen-client`.
 */
import createClient from "openapi-fetch";

import type { paths } from "./schema";

const configuredBaseUrl = import.meta.env.VITE_API_URL;

/**
 * Where the API lives: VITE_API_URL when set (a separately hosted API), otherwise `/api` on the
 * page's own origin, which the Vite dev proxy and nginx both forward with the prefix removed.
 */
export const apiBaseUrl =
  configuredBaseUrl !== undefined && configuredBaseUrl !== ""
    ? configuredBaseUrl
    : `${window.location.origin}/api`;

// fetch is looked up per call (not captured at import) so tests can stub it.
export const api = createClient<paths>({
  baseUrl: apiBaseUrl,
  fetch: (request) => globalThis.fetch(request),
});

/** Raised for any non-2xx response so TanStack Query surfaces it as an error state. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
