import { apiBaseUrl } from "@/lib/api/config";

/**
 * Full-page redirect URL to start Google OAuth.
 * OAuth must not be initiated via `fetch` — the browser follows redirects to Google.
 */
export function getGoogleAuthUrl(): string {
  return `${apiBaseUrl}/auth/google`;
}
