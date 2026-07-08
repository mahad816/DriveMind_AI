/**
 * API configuration for DriveMind frontend.
 *
 * Browser requests use the same-origin proxy path (`/api/v1`) configured in
 * `next.config.ts`. Server Components may use `serverApiBaseUrl` when needed.
 */

const DEFAULT_BROWSER_API_BASE = "/api/v1";
const DEFAULT_SERVER_API_BASE = "http://localhost:8000/api/v1";

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? DEFAULT_BROWSER_API_BASE;

export const serverApiBaseUrl =
  process.env.API_URL?.replace(/\/$/, "") ?? DEFAULT_SERVER_API_BASE;

export const backendUrl = process.env.BACKEND_URL?.replace(/\/$/, "") ?? "http://localhost:8000";
