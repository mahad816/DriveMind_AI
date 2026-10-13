/** In-memory request fencing; no cookies, credentials or OAuth state are stored. */
export const SESSION_INVALID_EVENT = "drivemind:session-invalid";
let revision = 0;
let owner: string | null = null;
export const sessionOwner = () => owner;
export const setSessionOwner = (value: string | null) => { owner = value; };
export const sessionRevision = () => revision;
export const SESSION_REQUESTS_INVALIDATED_EVENT = "drivemind:requests-invalidated";
export function invalidateSessionRequests(): void {
  revision += 1;
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function")
    window.dispatchEvent(new Event(SESSION_REQUESTS_INVALIDATED_EVENT));
}
export function notifySessionInvalid(): void {
  invalidateSessionRequests();
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event(SESSION_INVALID_EVENT));
}

/** Nonsecret invalidation notice only: receivers must inspect the server session. */
export const SESSION_TRANSITION_KEY = "drivemind:session-transition:v1";
export const SESSION_BROADCAST_EVENT = "drivemind:session-broadcast";
export function broadcastSessionTransition(): void {
  if (typeof window === "undefined") return;
  const nonce = crypto.randomUUID();
  try { window.localStorage.setItem(SESSION_TRANSITION_KEY, nonce); } catch { /* Disabled storage: BroadcastChannel still signals. */ }
  window.dispatchEvent(new CustomEvent(SESSION_BROADCAST_EVENT, { detail: nonce }));
}
