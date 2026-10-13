/** In-memory request fencing; no cookies, credentials or OAuth state are stored. */
export const SESSION_INVALID_EVENT = "drivemind:session-invalid";
let revision = 0;
let owner: string | null = null;
export const sessionOwner = () => owner;
export const setSessionOwner = (value: string | null) => { owner = value; };
export const sessionRevision = () => revision;
export function invalidateSessionRequests(): void { revision += 1; }
export function notifySessionInvalid(): void {
  invalidateSessionRequests();
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event(SESSION_INVALID_EVENT));
}
