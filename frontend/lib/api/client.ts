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
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { parseJson = true, headers, ...init } = options;
  const url = joinUrl(path);

  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
  });

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  if (!parseJson || response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
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
