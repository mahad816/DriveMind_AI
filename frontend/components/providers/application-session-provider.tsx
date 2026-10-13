"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { inspectApplicationSession, logoutApplicationSession, startGoogleSession } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { invalidateSessionRequests, setSessionOwner, sessionRevision, SESSION_INVALID_EVENT, broadcastSessionTransition, SESSION_TRANSITION_KEY, SESSION_BROADCAST_EVENT } from "@/lib/api/session-events";
import { DEMO_MODE } from "@/lib/demo";
import { Button } from "@/components/ui/button";
type State = {
  status: "checking" | "signed_out" | "ready" | "unavailable";
  userId: string | null;
  error: string | null;
};
type SessionContext = State & {
  refresh: () => Promise<boolean>;
  login: () => Promise<void>;
  connectDrive: () => Promise<void>;
  logout: () => Promise<void>;
};
const Context = createContext<SessionContext | null>(null);
export function useApplicationSession() {
  const value = useContext(Context);
  if (!value)
    throw new Error("ApplicationSessionProvider is required");
  return value;
}
function NormalSessionProvider({ children }: {
  children: ReactNode;
}) {
  const [state, setState] = useState<State>({ status: "checking", userId: null, error: null });
  const currentOwner = useRef<string | null>(null);
  const sequence = useRef(0);
  const announcedOwner = useRef<string | null>(null);
  const logoutPending = useRef(false);
  const loginPending = useRef(false);
  const reverifyPending = useRef(false);
  const clear = useCallback((status: State["status"], error: string | null = null) => {
    sequence.current += 1;
    currentOwner.current = null;
    setSessionOwner(null);
    invalidateSessionRequests();
    setState({ status, userId: null, error });
  }, []);
  const refresh = useCallback(async () => {
    if (logoutPending.current || loginPending.current)
      return false;
    const attempt = ++sequence.current;
    try {
      const session = await inspectApplicationSession();
      if (attempt !== sequence.current)
        return false;
      if (currentOwner.current !== session.user_id)
        invalidateSessionRequests();
      currentOwner.current = session.user_id;
      setSessionOwner(session.user_id);
      if (announcedOwner.current !== session.user_id) {
        announcedOwner.current = session.user_id;
        broadcastSessionTransition();
      }
      setState({ status: "ready", userId: session.user_id, error: null });
      return true;
    }
    catch (err) {
      if (attempt !== sequence.current)
        return false;
      clear(err instanceof ApiError && err.status === 401 ? "signed_out" : "unavailable", err instanceof ApiError && err.status === 401 ? null : "Application sign-in is unavailable. Verify the login configuration or try again.");
      return false;
    }
  }, [clear]);
  useEffect(() => {
    const invalid = () => { const hadOwner = currentOwner.current !== null; clear("signed_out"); if (hadOwner) broadcastSessionTransition(); };
    const verify = () => { void refresh(); };
    const focus = () => { if (logoutPending.current || loginPending.current) return; clear("checking"); void refresh(); };
    let channel: BroadcastChannel | null = null;
    try { if (typeof BroadcastChannel !== "undefined") channel = new BroadcastChannel("drivemind:application-session:v1"); } catch { /* Storage events and focus verification remain available. */ }
    let seen: string | null = null;
    const receive = (nonce: unknown) => {
      if (typeof nonce !== "string" || nonce === seen) return;
      seen = nonce;
      reverifyPending.current = logoutPending.current || loginPending.current;
      clear("checking");
      void refresh();
    };
    const storage = (event: StorageEvent) => {
      if (event.key === SESSION_TRANSITION_KEY) receive(event.newValue);
    };
    const broadcast = (event: Event) => channel?.postMessage((event as CustomEvent<string>).detail);
    if (channel) channel.onmessage = event => receive(event.data);
    window.addEventListener(SESSION_BROADCAST_EVENT, broadcast);
    window.addEventListener("storage", storage);
    window.addEventListener(SESSION_INVALID_EVENT, invalid);
    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", focus);
    const timer = setInterval(verify, 30000);
    void refresh();
    return () => {
      sequence.current += 1; setSessionOwner(null); invalidateSessionRequests(); clearInterval(timer);
      window.removeEventListener(SESSION_INVALID_EVENT, invalid); window.removeEventListener("focus", focus);
      window.removeEventListener("storage", storage); window.removeEventListener(SESSION_BROADCAST_EVENT, broadcast);
      document.removeEventListener("visibilitychange", focus); channel?.close();
    };
  }, [clear, refresh]);
  const login = async () => {
    loginPending.current = true;
    clear("checking");
    broadcastSessionTransition();
    const revision = sessionRevision();
    try {
      const url = await startGoogleSession("LOGIN");
      if (revision === sessionRevision())
        window.location.assign(url);
    }
    catch {
      if (revision !== sessionRevision())
        return;
      clear("signed_out", "Google sign-in could not be started. Please try again.");
    } finally {
      loginPending.current = false;
      if (reverifyPending.current) { reverifyPending.current = false; void refresh(); }
    }
  };
  const connectDrive = async () => {
    const owner = currentOwner.current;
    if (!owner) {
      clear("signed_out");
      return;
    }
    const revision = sessionRevision();
    try {
      const url = await startGoogleSession("CONNECT_DRIVE", owner);
      if (revision === sessionRevision() && currentOwner.current === owner)
        window.location.assign(url);
    }
    catch (err) {
      if (revision !== sessionRevision())
        return;
      if (err instanceof ApiError && [401, 409].includes(err.status))
        clear("unavailable", "Your session changed. Verify your account before reconnecting Drive.");
      else
        setState(s => ({ ...s, error: "Google Drive connection could not be started. Verify your session and try again." }));
    }
  };
  const logout = async () => {
    const owner = currentOwner.current;
    logoutPending.current = true;
    clear("checking"); // Unmount private state before any network wait.
    broadcastSessionTransition();
    try {
      if (owner)
        await logoutApplicationSession(owner);
      clear("signed_out");
    }
    catch (err) {
      if (err instanceof ApiError && err.status === 401)
        clear("signed_out");
      else
        clear("unavailable", "Sign-out could not be confirmed. Private content is hidden; verify your session before continuing.");
    }
    finally {
      logoutPending.current = false;
      broadcastSessionTransition();
      if (reverifyPending.current) { reverifyPending.current = false; void refresh(); }
    }
  };
  return (
    <Context.Provider value={{ ...state, refresh, login, connectDrive, logout }}>
      {state.status === "ready" ? (
        <div key={`${state.userId}:${sessionRevision()}`} className="contents">{children}</div>
      ) : (
        <section className="mx-auto max-w-lg space-y-4 p-8" aria-label="Application sign-in">
          <h1>{state.status === "checking" ? "Checking application session…" : "Sign in to DriveMind"}</h1>
          {state.error ? <p role="alert">{state.error}</p> : null}
          {state.status === "signed_out" ? (
            <Button onClick={() => void login()}>Sign in with Google</Button>
          ) : null}
          {state.status === "unavailable" ? (
            <Button onClick={() => void refresh()}>Verify session again</Button>
          ) : null}
        </section>
      )}
    </Context.Provider>
  );
}

export function ApplicationSessionProvider({ children }: {
  children: ReactNode;
}) {
  return DEMO_MODE ? <>{children}</> : <NormalSessionProvider>{children}</NormalSessionProvider>;
}
