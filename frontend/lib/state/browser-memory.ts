/**
 * Small, non-authoritative browser memory: unsent drafts, the page to return to after sign-in, and UI preferences.
 * Drafts are the person's own unsent text, kept in sessionStorage (this tab only), keyed by owner and conversation,
 * and wiped on sign-out. Nothing here is a cache of server data or a permission.
 */
const DRAFT_PREFIX = "drivemind:draft:v1:";
const RETURN_KEY = "drivemind:return-to:v1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function session(): Storage | null {
  try { return typeof window === "undefined" ? null : window.sessionStorage; } catch { return null; }
}
const draftKey = (owner: string, conversation: string | null) => `${DRAFT_PREFIX}${owner}:${conversation ?? "new"}`;

export function readDraft(owner: string | null, conversation: string | null): string {
  if (!owner) return "";
  try { return session()?.getItem(draftKey(owner, conversation)) ?? ""; } catch { return ""; }
}
export function writeDraft(owner: string | null, conversation: string | null, text: string): void {
  const store = session();
  if (!owner || !store) return;
  try {
    if (text.trim()) store.setItem(draftKey(owner, conversation), text.slice(0, 8000));
    else store.removeItem(draftKey(owner, conversation));
  } catch { /* storage full or disabled: the draft simply is not remembered */ }
}
/** Drafts belonging to any other owner are dropped when a different account becomes active. */
export function dropOtherOwnersDrafts(owner: string): void {
  const store = session();
  if (!store) return;
  try {
    for (let i = store.length - 1; i >= 0; i--) {
      const key = store.key(i);
      if (key?.startsWith(DRAFT_PREFIX) && !key.startsWith(`${DRAFT_PREFIX}${owner}:`)) store.removeItem(key);
    }
  } catch { /* ignore */ }
}
export function clearAllDrafts(): void {
  const store = session();
  if (!store) return;
  try {
    for (let i = store.length - 1; i >= 0; i--) { const key = store.key(i); if (key?.startsWith(DRAFT_PREFIX)) store.removeItem(key); }
  } catch { /* ignore */ }
}

/** Only same-app paths are remembered; the value is checked again before use. */
export function safeReturnPath(value: string | null): string | null {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return null;
  const path = value.split("?")[0];
  const allowed = path === "/chat" || path === "/files" || path === "/settings" || path === "/welcome"
    || (path.startsWith("/chat/") && UUID.test(path.slice(6))) || (path.startsWith("/sources/") && UUID.test(path.slice(9)));
  return allowed && !value.includes("login=") ? value : null;
}
export function rememberReturnPath(): void {
  if (typeof window === "undefined") return;
  const path = safeReturnPath(window.location.pathname + window.location.search);
  try { if (path) session()?.setItem(RETURN_KEY, path); } catch { /* ignore */ }
}
/** Forgets the remembered page, so a later sign-in (possibly another account) never lands on it. */
export function clearReturnPath(): void {
  try { session()?.removeItem(RETURN_KEY); } catch { /* ignore */ }
}
export function takeReturnPath(): string | null {
  const store = session();
  try {
    const value = safeReturnPath(store?.getItem(RETURN_KEY) ?? null);
    store?.removeItem(RETURN_KEY);
    return value;
  } catch { return null; }
}

const CONNECT_KEY = "drivemind:connect-intent:v1";
/** True once, right after returning from a Drive consent this owner started in this tab. */
export function takeConnectIntent(owner: string): boolean {
  const store = session();
  try {
    const value = store?.getItem(CONNECT_KEY);
    store?.removeItem(CONNECT_KEY);
    return value === owner;
  } catch { return false; }
}

export function readPreference(key: string): string | null {
  try { return typeof window === "undefined" ? null : window.localStorage.getItem(`drivemind:pref:${key}`); } catch { return null; }
}
export function writePreference(key: string, value: string): void {
  try { window.localStorage.setItem(`drivemind:pref:${key}`, value); } catch { /* ignore */ }
}
