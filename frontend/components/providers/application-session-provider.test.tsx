import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApplicationSessionProvider, useApplicationSession } from "./application-session-provider";
import { apiFetch } from "@/lib/api/client";
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
