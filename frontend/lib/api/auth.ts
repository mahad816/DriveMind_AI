import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
export type ApplicationSession = {
  kind: "GOOGLE_ACCOUNT";
  user_id: string;
  csrf_token: string;
};
export type GoogleAuthIntent = "LOGIN" | "CONNECT_DRIVE";
export async function inspectApplicationSession(): Promise<ApplicationSession> {
  const value = await apiFetch<ApplicationSession>("/auth/session", { cache: "no-store", signal: AbortSignal.timeout(15000) });
  if (!value || value.kind !== "GOOGLE_ACCOUNT" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.user_id) ||
    typeof value.csrf_token !== "string" || !value.csrf_token) {
    throw new ApiError(503, "Application session verification is unavailable.");
  }
  return value;
}
async function csrfForOwner(owner: string): Promise<string> {
  const session = await inspectApplicationSession();
  if (session.user_id !== owner)
    throw new ApiError(409, "Your account changed. Verify your session again.");
  return session.csrf_token;
}
export async function startGoogleSession(intent: GoogleAuthIntent, owner?: string): Promise<string> {
  const headers: Record<string, string> = { "X-DriveMind-Auth": "1" };
  if (intent === "CONNECT_DRIVE") {
    if (!owner)
      throw new ApiError(401, "Sign in before connecting Google Drive.");
    headers["X-CSRF-Token"] = await csrfForOwner(owner);
  }
  const result = await apiFetch<{
    authorization_url: string;
  }>("/auth/session/google", {
    signal: AbortSignal.timeout(15000), method: "POST", headers, body: JSON.stringify({ intent }),
  });
  const url = new URL(result?.authorization_url);
  if (url.protocol !== "https:" || url.hostname !== "accounts.google.com" || url.username || url.password) {
    throw new ApiError(503, "Google sign-in could not be started.");
  }
  return url.href;
}
export async function logoutApplicationSession(owner: string): Promise<void> {
  const csrf = await csrfForOwner(owner);
  await apiFetch<void>("/auth/session/logout", { method: "POST", signal: AbortSignal.timeout(15000), headers: { "X-CSRF-Token": csrf } });
}
