import { notifySessionInvalid, sessionRevision } from "@/lib/api/session-events";
import { apiBaseUrl } from "@/lib/api/config";
import { ApiError } from "@/lib/api/errors";
import type { FastApiErrorBody } from "@/lib/api/types";

type ApiFetchOptions = RequestInit & {
  /** Skip JSON parsing for empty or non-JSON success responses. */
  parseJson?: boolean;
};

function joinUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${apiBaseUrl}${normalizedPath}`;
}

export function formatApiErrorDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") {
    return fallback;
  }

  const detail = (body as FastApiErrorBody).detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((item) => item.msg).join("; ");
  }

  return fallback;
}

async function parseErrorResponse(response: Response): Promise<ApiError> {
  const fallback = `Request failed with status ${response.status}`;
  try {
    const body = await response.json();
    return new ApiError(response.status, formatApiErrorDetail(body, fallback), body);
  } catch {
    return new ApiError(response.status, fallback);
  }
}

/**
 * Fetch JSON from the DriveMind backend API.
 *
 * Browser calls use the same-origin `/api/v1` proxy configured in `next.config.ts`.
 */
export async function apiFetchWithStatus<T>(
  path: string, options: ApiFetchOptions = {},
): Promise<{ status: number; data: T }> {
  const { parseJson = true, headers, ...init } = options;
  const url = joinUrl(path);

  const revision = sessionRevision();
  const response = await fetch(url, {
    credentials: "include",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
  });

  if (revision !== sessionRevision()) {
    throw new ApiError(409, "Your application session changed. Please try again.");
  }
  if (response.status === 401) notifySessionInvalid();
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  if (!parseJson || response.status === 204) {
    return { status: response.status, data: undefined as T };
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return { status: response.status, data: undefined as T };
  }

  const body = await response.json() as T;
  if (revision !== sessionRevision()) throw new ApiError(409, "Your application session changed. Please try again.");
  return { status: response.status, data: body };
}

/** Preserve the existing data-only API for all current callers. */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  return (await apiFetchWithStatus<T>(path, options)).data;
}

export function buildQueryString(
  params: Record<string, string | number | boolean | null | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined) {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}
