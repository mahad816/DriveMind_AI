import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApplicationSessionProvider, useApplicationSession } from "./application-session-provider";
import { apiFetch } from "@/lib/api/client";
import { sessionRevision } from "@/lib/api/session-events";
import { useEffect } from "react";
const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
const a = "00000000-0000-0000-0000-000000000065", b = "00000000-0000-0000-0000-000000000066";
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const who = (id = a) => json({ kind: "GOOGLE_ACCOUNT", user_id: id, csrf_token: "synthetic" });
function Private() { const s = useApplicationSession(); return <><p>Private account {s.userId}</p><button onClick={() => void s.logout()}>logout</button><button onClick={() => void s.refresh()}>inspect</button></>; }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); mode.demo = false; });
it("missing session renders sign-in, not private children", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(json({ detail: "Sign in" }, 401))));
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  expect(await screen.findByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Ask questions about your Drive documents." })).toBeInTheDocument();
});
it("verifies identity despite forged callback hints", async () => {
  window.history.replaceState({}, "", "/settings?login=success&connected=true&email=A_SECRET&user_id=forged");
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(who(b))));
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  expect(await screen.findByText(`Private account ${b}`)).toBeInTheDocument();
  expect(screen.queryByText(/A_SECRET|forged/)).not.toBeInTheDocument();
});
it("logout hides private state before waiting and requires real logout response", async () => {
  let finish!: (r: Response) => void;
  const fetch = vi.fn().mockImplementation((url: string) => url.endsWith("/logout") ? new Promise(r => { finish = r; }) : Promise.resolve(who()));
  vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "logout" }));
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
  await waitFor(() => expect(finish).toBeDefined());
  await act(async () => finish(new Response(null, { status: 204 })));
  expect(await screen.findByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
});
it("a private request 401 clears mounted state", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(who()).mockResolvedValueOnce(json({ detail: "Session expired" }, 401)); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`);
  await act(async () => { await expect(apiFetch("/files")).rejects.toMatchObject({ status: 401 }); });
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
});
it("failed logout does not claim server sign-out or expose private state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith("/logout") ? json({ detail: "Unavailable" }, 503) : who())));
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "logout" }));
  expect(await screen.findByText(/Sign-out could not be confirmed/)).toBeInTheDocument();
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
});
it("demo bypasses normal session creation and inspection", () => {
  mode.demo = true; const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><p>Anonymous demo</p></ApplicationSessionProvider>);
  expect(screen.getByText("Anonymous demo")).toBeInTheDocument(); expect(fetch).not.toHaveBeenCalled();
});
it("configuration failure is explicit and never opens private state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "Not found" }, 404)));
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  expect(await screen.findByText(/Sign-in is temporarily unavailable/)).toBeInTheDocument();
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
});
it("focus inspection cannot reopen private state while logout is pending", async () => {
  let finish!: (r: Response) => void;
  const fetch = vi.fn().mockImplementation((url: string) => url.endsWith("/logout") ? new Promise(r => { finish = r; }) : Promise.resolve(who()));
  vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "logout" }));
  await waitFor(() => expect(finish).toBeDefined());
  const calls = fetch.mock.calls.length;
  fireEvent(window, new Event("focus"));
  expect(fetch).toHaveBeenCalledTimes(calls);
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
  await act(async () => finish(new Response(null, { status: 204 })));
});
it("an old request's delayed 401 cannot sign out a newly verified owner", async () => {
  let owner = a;
  let finish!: (r: Response) => void;
  const fetch = vi.fn().mockImplementation((url: string) => url.endsWith("/session") ? Promise.resolve(who(owner)) : new Promise(r => { finish = r; }));
  vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`);
  const old = apiFetch("/files");
  owner = b; fireEvent.click(screen.getByRole("button", { name: "inspect" }));
  await screen.findByText(`Private account ${b}`);
  await act(async () => { finish(json({ detail: "old session expired" }, 401)); await expect(old).rejects.toMatchObject({ status: 409 }); });
  expect(screen.getByText(`Private account ${b}`)).toBeInTheDocument();
});
it("indexing cannot move to a different cookie owner while the UI still represents A", async () => {
  const { buildVectorIndex } = await import("@/lib/api/indexing");
  const fetch = vi.fn().mockResolvedValueOnce(who(a)).mockResolvedValueOnce(who(b)); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`);
  await act(async () => { await expect(buildVectorIndex()).rejects.toMatchObject({ status: 409 }); });
  expect(fetch.mock.calls.every(([url]) => url === "/api/v1/auth/session")).toBe(true);
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
});
it("focus verification cannot cancel a pending LOGIN; failure remains retryable", async () => {
  let finish!: (r: Response) => void;
  const fetch = vi.fn().mockImplementation((url: string) => url.endsWith("/session/google") ? new Promise(r => { finish = r; }) : Promise.resolve(json({ detail: "Missing session" }, 401)));
  vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Sign in with Google" }));
  await waitFor(() => expect(finish).toBeDefined());
  const calls = fetch.mock.calls.length;
  fireEvent(window, new Event("focus"));
  expect(fetch).toHaveBeenCalledTimes(calls);
  await act(async () => finish(json({ detail: "synthetic login unavailable" }, 503)));
  expect(await screen.findByText(/Google sign-in could not be started/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
  expect(fetch.mock.calls.some(([url]) => url === "/api/v1/auth/google")).toBe(false);
});

// Checkpoint A (A5): returning to the tab must revalidate silently. Before this change the focus
// handler cleared the session to "checking", which unmounted the whole app (the visible blink),
// aborted in-flight requests, bumped the session revision and wiped selection and drafts.
const mounts = { n: 0 };
function Counted() { const s = useApplicationSession(); useEffect(() => { mounts.n += 1; }, []); return <p>Private account {s.userId}</p>; }
function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
  Object.defineProperty(document, "visibilityState", { configurable: true, value: hidden ? "hidden" : "visible" });
}
it("returning to the tab keeps private content mounted, does not invalidate requests, and verifies once", async () => {
  mounts.n = 0; let release!: (r: Response) => void; let calls = 0;
  const fetch = vi.fn().mockImplementation(() => ++calls === 1 ? Promise.resolve(who()) : new Promise(r => { release = r; }));
  vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Counted /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`);
  const revision = sessionRevision();
  fireEvent(window, new Event("focus")); document.dispatchEvent(new Event("visibilitychange"));
  expect(screen.getByText(`Private account ${a}`)).toBeInTheDocument();
  expect(screen.queryByText("Checking your sign-in…")).not.toBeInTheDocument();
  expect(sessionRevision()).toBe(revision);
  expect(fetch).toHaveBeenCalledTimes(2);
  await act(async () => release(who()));
  expect(screen.getByText(`Private account ${a}`)).toBeInTheDocument();
  expect(sessionRevision()).toBe(revision); expect(mounts.n).toBe(1);
});
it("a hidden tab does not verify, and becoming hidden never signs out", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(who())); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`); const calls = fetch.mock.calls.length;
  setHidden(true);
  try { document.dispatchEvent(new Event("visibilitychange")); } finally { setHidden(false); }
  expect(fetch).toHaveBeenCalledTimes(calls); expect(screen.getByText(`Private account ${a}`)).toBeInTheDocument();
});
it("an expired session found on return hides private content and says so", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(who()).mockResolvedValueOnce(json({ detail: "Session expired" }, 401)); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`);
  fireEvent(window, new Event("focus"));
  expect(await screen.findByText(/Your session expired/)).toBeInTheDocument();
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
});
it("a different owner found on return invalidates requests and gives the new owner a fresh mount", async () => {
  mounts.n = 0; const fetch = vi.fn().mockResolvedValueOnce(who(a)).mockResolvedValueOnce(who(b)); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Counted /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`); const revision = sessionRevision();
  fireEvent(window, new Event("focus"));
  expect(await screen.findByText(`Private account ${b}`)).toBeInTheDocument();
  expect(sessionRevision()).toBeGreaterThan(revision); expect(mounts.n).toBe(2);
  expect(screen.queryByText(`Private account ${a}`)).not.toBeInTheDocument();
});
// Decision D2 (authorized in the Phase 2 brief): a transient failure keeps already-authorized content visible,
// read-only. The server still authorizes every request, and any 401 hides private content immediately.
function Degraded() { const s = useApplicationSession(); useEffect(() => { mounts.n += 1; }, []); return <p>Private account {s.userId} degraded={String(s.degraded)} canMutate={String(s.canMutate)}</p>; }
it("a transient failure on return keeps private content mounted but read-only", async () => {
  mounts.n = 0;
  const fetch = vi.fn().mockResolvedValueOnce(who()).mockResolvedValueOnce(json({ detail: "down" }, 503)); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Degraded /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a} degraded=false canMutate=true`);
  const revision = sessionRevision();
  fireEvent(window, new Event("focus"));
  expect(await screen.findByText(`Private account ${a} degraded=true canMutate=false`)).toBeInTheDocument();
  expect(sessionRevision()).toBe(revision); expect(mounts.n).toBe(1);
  expect(screen.queryByRole("button", { name: "Sign in with Google" })).not.toBeInTheDocument();
});
it("a 401 while degraded hides private content immediately", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(who()).mockResolvedValueOnce(json({ detail: "down" }, 503))
    .mockResolvedValueOnce(json({ detail: "Session expired" }, 401)); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Degraded /></ApplicationSessionProvider>);
  await screen.findByText(/degraded=false/);
  fireEvent(window, new Event("focus"));
  await screen.findByText(/degraded=true/);
  await act(async () => { await expect(apiFetch("/files")).rejects.toMatchObject({ status: 401 }); });
  expect(screen.queryByText(/Private account/)).not.toBeInTheDocument();
  expect(await screen.findByText(/Your session expired/)).toBeInTheDocument();
});
it("recovery after a transient failure restores writes without remounting", async () => {
  mounts.n = 0;
  const fetch = vi.fn().mockResolvedValueOnce(who()).mockResolvedValueOnce(json({ detail: "down" }, 503)).mockResolvedValue(who()); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Degraded /></ApplicationSessionProvider>);
  await screen.findByText(/degraded=false/);
  fireEvent(window, new Event("focus"));
  await screen.findByText(/degraded=true/);
  fireEvent(window, new Event("focus"));
  expect(await screen.findByText(`Private account ${a} degraded=false canMutate=true`)).toBeInTheDocument();
  expect(mounts.n).toBe(1);
});
it("a different owner after a transient failure still gets a fresh mount, never the old content", async () => {
  mounts.n = 0;
  const fetch = vi.fn().mockResolvedValueOnce(who(a)).mockResolvedValueOnce(json({ detail: "down" }, 503)).mockResolvedValue(who(b)); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Degraded /></ApplicationSessionProvider>);
  await screen.findByText(/degraded=false/);
  fireEvent(window, new Event("focus")); await screen.findByText(/degraded=true/);
  fireEvent(window, new Event("focus"));
  expect(await screen.findByText(`Private account ${b} degraded=false canMutate=true`)).toBeInTheDocument();
  expect(screen.queryByText(new RegExp(a))).not.toBeInTheDocument(); expect(mounts.n).toBe(2);
});
it("a sign-in notice from another tab re-checks silently and does not remount the same owner", async () => {
  mounts.n = 0;
  const fetch = vi.fn().mockResolvedValue(who()); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Counted /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`);
  const calls = fetch.mock.calls.length;
  await act(async () => { window.dispatchEvent(new StorageEvent("storage", { key: "drivemind:session-transition:v1", newValue: "other-tab-nonce" })); });
  await waitFor(() => expect(fetch.mock.calls.length).toBe(calls + 1));
  expect(screen.getByText(`Private account ${a}`)).toBeInTheDocument();
  expect(screen.queryByText("Checking your sign-in…")).not.toBeInTheDocument(); expect(mounts.n).toBe(1);
});
it("a sign-out in another tab is confirmed by the server and hides private content", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(who()).mockResolvedValue(json({ detail: "Signed out" }, 401)); vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><Private /></ApplicationSessionProvider>);
  await screen.findByText(`Private account ${a}`);
  await act(async () => { window.dispatchEvent(new StorageEvent("storage", { key: "drivemind:session-transition:v1", newValue: "logout-nonce" })); });
  await waitFor(() => expect(screen.queryByText(/Private account/)).not.toBeInTheDocument());
});
