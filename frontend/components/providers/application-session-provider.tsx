"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { inspectApplicationSession, logoutApplicationSession, startGoogleSession } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { invalidateSessionRequests, setSessionOwner, sessionRevision, SESSION_INVALID_EVENT } from "@/lib/api/session-events";
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
  const logoutPending = useRef(false);
  const loginPending = useRef(false);
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
    const invalid = () => clear("signed_out");
    const verify = () => { void refresh(); };
    window.addEventListener(SESSION_INVALID_EVENT, invalid);
    window.addEventListener("focus", verify);
    const timer = setInterval(verify, 30000);
    void refresh();
    return () => { sequence.current += 1; setSessionOwner(null); invalidateSessionRequests(); clearInterval(timer); window.removeEventListener(SESSION_INVALID_EVENT, invalid); window.removeEventListener("focus", verify); };
  }, [clear, refresh]);
  const login = async () => {
    loginPending.current = true;
    clear("checking");
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
    }
  };
  return (
    <Context.Provider value={{ ...state, refresh, login, connectDrive, logout }}>
      {state.status === "ready" ? (
        <div key={state.userId} className="contents">{children}</div>
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
