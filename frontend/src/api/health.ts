import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "./client";
import type { components } from "./schema";

export type Health = components["schemas"]["HealthResponse"];

export async function fetchHealth(): Promise<Health> {
  const { data, response } = await api.GET("/health");
  if (!response.ok || data === undefined) {
    throw new ApiError(response.status, `Health check failed (${String(response.status)})`);
  }
  return data;
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: false });
}
