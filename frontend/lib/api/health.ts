import { apiFetch } from "@/lib/api/client";
import type { HealthResponse, ReadinessResponse } from "@/lib/api/types";

export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

export async function getReadiness(): Promise<ReadinessResponse> {
  return apiFetch<ReadinessResponse>("/health/ready");
}
