"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { inspectApplicationSession, logoutApplicationSession, startGoogleSession } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import {
  invalidateSessionRequests, setSessionOwner, sessionRevision, SESSION_INVALID_EVENT, broadcastSessionTransition,
  SESSION_TRANSITION_KEY, SESSION_BROADCAST_EVENT,
} from "@/lib/api/session-events";
import { DEMO_MODE } from "@/lib/demo";
import { SignInScreen } from "@/components/session/sign-in-screen";
import { clearAllDrafts, clearReturnPath, rememberReturnPath } from "@/lib/state/browser-memory";

type Status = "checking" | "signed_out" | "ready" | "unavailable";
type State = {
  status: Status;
  userId: string | null;
  error: string | null;
  /** Workspace stays visible but read-only: the last session check failed for a reason other than 401 (decision D2). */
  degraded: boolean;
};
export type SessionContext = State & {
  offline: boolean;
  /** UI gate for writes. The server still authorizes every request; this only avoids actions that cannot succeed. */
  canMutate: boolean;
  refresh: () => Promise<boolean>;
  login: () => Promise<void>;
  connectDrive: () => Promise<void>;
  logout: () => Promise<void>;
};
const Context = createContext<SessionContext | null>(null);
export function useApplicationSession() {
  const value = useContext(Context);
  if (!value) throw new Error("ApplicationSessionProvider is required");
  return value;
}

const EXPIRED = "Your session expired. Sign in again to continue where you left off.";
const UNAVAILABLE = "Sign-in is temporarily unavailable. DriveMind will keep trying. Nothing is lost.";
const BACKOFF = [2000, 5000, 10000, 30000];
const VERIFY_EVERY = 60_000;

function NormalSessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "checking", userId: null, error: null, degraded: false });
  const [offline, setOffline] = useState(false);
  const stateRef = useRef(state);
  stateRef.current = state;
  const currentOwner = useRef<string | null>(null);
  const sequence = useRef(0);
  const announcedOwner = useRef<string | null>(null);
  const logoutPending = useRef(false);
  const loginPending = useRef(false);
  const reverifyPending = useRef(false);
  const revalidating = useRef<Promise<boolean> | null>(null);
  const retry = useRef<{ timer: ReturnType<typeof setTimeout> | null; attempt: number }>({ timer: null, attempt: 0 });

  // Publish only real changes: an identical successful check must not re-render the workspace.
  const set = useCallback((next: State) => {
    const prev = stateRef.current;
    if (prev.status === next.status && prev.userId === next.userId && prev.error === next.error && prev.degraded === next.degraded) return;
    stateRef.current = next;
    setState(next);
  }, []);
  const stopRetry = useCallback(() => {
    if (retry.current.timer) clearTimeout(retry.current.timer);
    retry.current = { timer: null, attempt: 0 };
  }, []);
  const clear = useCallback((status: Status, error: string | null = null) => {
    sequence.current += 1;
    currentOwner.current = null;
    setSessionOwner(null);
    invalidateSessionRequests();
    set({ status, userId: null, error, degraded: false });
  }, [set]);

  const refresh = useCallback(async (): Promise<boolean> => {
    if (logoutPending.current || loginPending.current) return false;
    const attempt = ++sequence.current;
    const hadOwner = currentOwner.current !== null;
    try {
      const session = await inspectApplicationSession();
      if (attempt !== sequence.current) return false;
      if (currentOwner.current !== session.user_id) invalidateSessionRequests();
      currentOwner.current = session.user_id;
      setSessionOwner(session.user_id);
      if (announcedOwner.current !== session.user_id) {
        announcedOwner.current = session.user_id;
        broadcastSessionTransition();
      }
      if (retry.current.timer) stopRetry(); else retry.current.attempt = 0;
      set({ status: "ready", userId: session.user_id, error: null, degraded: false });
      return true;
    } catch (err) {
      if (attempt !== sequence.current) return false;
      if (err instanceof ApiError && err.status === 401) {
        clear("signed_out", hadOwner ? EXPIRED : null);
        return false;
      }
      if (hadOwner && stateRef.current.status === "ready") {
        // D2: the owner is still known and nothing proved the session ended. Keep authorized content visible,
        // read-only; any private request that now returns 401 still hides everything immediately.
        set({ ...stateRef.current, degraded: true });
      } else {
        clear("unavailable", UNAVAILABLE);
      }
      scheduleRetry();
      return false;
    }
  }, [clear, set, stopRetry]);

  const silent = useCallback(() => {
    if (logoutPending.current || loginPending.current || document.hidden) return revalidating.current ?? Promise.resolve(false);
    if (revalidating.current) return revalidating.current;
    const run = refresh().finally(() => { if (revalidating.current === run) revalidating.current = null; });
    revalidating.current = run;
    return run;
  }, [refresh]);

  const silentRef = useRef(silent);
  silentRef.current = silent;
  function scheduleRetry() {
    if (retry.current.timer || document.hidden) return;
    const delay = BACKOFF[Math.min(retry.current.attempt, BACKOFF.length - 1)];
    retry.current.attempt += 1;
    retry.current.timer = setTimeout(() => { retry.current.timer = null; void silentRef.current(); }, delay);
  }

  useEffect(() => {
    const invalid = () => {
      const hadOwner = currentOwner.current !== null;
      stopRetry();
      clear("signed_out", hadOwner ? EXPIRED : null);
      if (hadOwner) broadcastSessionTransition();
    };
    // Returning to the tab revalidates silently and at most once at a time; it never unmounts the workspace.
    const visible = () => {
      if (document.hidden) { if (retry.current.timer) { clearTimeout(retry.current.timer); retry.current.timer = null; } return; }
      void silent();
    };
    let channel: BroadcastChannel | null = null;
    try { if (typeof BroadcastChannel !== "undefined") channel = new BroadcastChannel("drivemind:application-session:v1"); } catch { /* storage events still signal */ }
    let seen: string | null = null;
    // Another tab signed in or out. Check the server's answer; a 401 or a different owner hides private content.
    const receive = (nonce: unknown) => {
      if (typeof nonce !== "string" || nonce === seen) return;
      seen = nonce;
      if (logoutPending.current || loginPending.current) { reverifyPending.current = true; return; }
      if (stateRef.current.status === "ready") void silent(); else void refresh();
    };
    const storage = (event: StorageEvent) => { if (event.key === SESSION_TRANSITION_KEY) receive(event.newValue); };
    const broadcast = (event: Event) => { const nonce = (event as CustomEvent<string>).detail; seen = nonce; channel?.postMessage(nonce); };
    const online = () => { setOffline(false); void silent(); };
    const offlineEvent = () => setOffline(true);
    if (channel) channel.onmessage = event => receive(event.data);
    window.addEventListener(SESSION_BROADCAST_EVENT, broadcast);
    window.addEventListener("storage", storage);
    window.addEventListener(SESSION_INVALID_EVENT, invalid);
    window.addEventListener("focus", visible);
    window.addEventListener("online", online);
    window.addEventListener("offline", offlineEvent);
    document.addEventListener("visibilitychange", visible);
    setOffline(typeof navigator !== "undefined" && navigator.onLine === false);
    const timer = setInterval(() => { if (!document.hidden) void silent(); }, VERIFY_EVERY);
    void refresh();
    return () => {
      sequence.current += 1; setSessionOwner(null); invalidateSessionRequests(); clearInterval(timer); stopRetry();
      window.removeEventListener(SESSION_INVALID_EVENT, invalid); window.removeEventListener("focus", visible);
      window.removeEventListener("storage", storage); window.removeEventListener(SESSION_BROADCAST_EVENT, broadcast);
      window.removeEventListener("online", online); window.removeEventListener("offline", offlineEvent);
      document.removeEventListener("visibilitychange", visible); channel?.close();
    };
  }, [clear, refresh, silent, stopRetry]);

  const login = useCallback(async () => {
    loginPending.current = true;
    stopRetry();
    rememberReturnPath();
    clear("checking");
    broadcastSessionTransition();
    const revision = sessionRevision();
    try {
      const url = await startGoogleSession("LOGIN");
      if (revision === sessionRevision()) window.location.assign(url);
    } catch {
      if (revision !== sessionRevision()) return;
      clear("signed_out", "Google sign-in could not be started. Check your connection and try again.");
    } finally {
      loginPending.current = false;
      if (reverifyPending.current) { reverifyPending.current = false; void refresh(); }
    }
  }, [clear, refresh, stopRetry]);

  const connectDrive = useCallback(async () => {
    const owner = currentOwner.current;
    if (!owner) { clear("signed_out"); return; }
    const revision = sessionRevision();
    try {
      const url = await startGoogleSession("CONNECT_DRIVE", owner);
      if (revision === sessionRevision() && currentOwner.current === owner) {
        try { window.sessionStorage.setItem("drivemind:connect-intent:v1", owner); } catch { /* discovery can still be started by hand */ }
        window.location.assign(url);
      }
    } catch (err) {
      if (revision !== sessionRevision()) return;
      if (err instanceof ApiError && [401, 409].includes(err.status)) clear("signed_out", "Your session changed. Sign in again before connecting Google Drive.");
      else throw new Error("Google Drive connection could not be started. Check your connection and try again.");
    }
  }, [clear]);

  const logout = useCallback(async () => {
    const owner = currentOwner.current;
    logoutPending.current = true;
    stopRetry();
    clear("checking"); // Unmount private state before any network wait.
    broadcastSessionTransition();
    clearAllDrafts(); clearReturnPath();
    try {
      if (owner) await logoutApplicationSession(owner);
      clear("signed_out", "Signed out. Your prepared documents and Drive permission are kept.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) clear("signed_out");
      else clear("unavailable", "Sign-out could not be confirmed. Private content is hidden; check your sign-in before continuing.");
    } finally {
      logoutPending.current = false;
      broadcastSessionTransition();
      if (reverifyPending.current) { reverifyPending.current = false; void refresh(); }
    }
  }, [clear, refresh, stopRetry]);

  const value = useMemo<SessionContext>(() => ({
    ...state, offline, canMutate: state.status === "ready" && !state.degraded && !offline, refresh, login, connectDrive, logout,
  }), [state, offline, refresh, login, connectDrive, logout]);

  return (
    <Context.Provider value={value}>
      {state.status === "ready"
        // Keyed by owner only: a silent check, a transient failure or a request revision never remounts the workspace.
        ? <div key={state.userId} className="contents">{children}</div>
        : <SignInScreen status={state.status} error={state.error} onLogin={() => void login()} onRetry={() => void refresh()} />}
    </Context.Provider>
  );
}

const DEMO_CONTEXT: SessionContext = {
  status: "ready", userId: null, error: null, degraded: false, offline: false, canMutate: false,
  refresh: async () => false, login: async () => {}, connectDrive: async () => {}, logout: async () => {},
};
export function ApplicationSessionProvider({ children }: { children: ReactNode }) {
  return DEMO_MODE ? <Context.Provider value={DEMO_CONTEXT}>{children}</Context.Provider> : <NormalSessionProvider>{children}</NormalSessionProvider>;
}
