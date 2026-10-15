import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { ApplicationSessionProvider } from "@/components/providers/application-session-provider";
import { DiscoveryController } from "./discovery";
import { setSessionOwner, sessionOwner, SESSION_INVALID_EVENT, invalidateSessionRequests } from "@/lib/api/session-events";
const owner = "00000000-0000-0000-0000-000000000065", id = "00000000-0000-0000-0000-000000000123";
beforeEach(() => {
  Object.defineProperty(navigator, "locks", { configurable: true, value: {
    request: async (_name: string, callback: () => unknown) => callback(),
  } });
  setSessionOwner(owner);
  const stored = new Map<string, string>();
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => stored.get(k) ?? null, setItem: (k: string, v: string) => stored.set(k, v), removeItem: (k: string) => stored.delete(k) } });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setSessionOwner(null); });
it("real API transport submits only SYNC with fresh CSRF, never ingest/chunk/build or content downloads", async () => {
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  vi.stubGlobal("fetch", vi.fn(async (path: string, options: RequestInit = {}) => {
    if (path === "/api/v1/auth/session") return json({ user_id: owner, csrf_token: "synthetic-csrf" });
    if (path === "/api/v1/index/sync?full=false") {
      expect(options.method).toBe("POST"); expect(options.headers).toMatchObject({ "X-CSRF-Token": "synthetic-csrf" });
      return json({ job_id: id, status: "queued", message: "Accepted" }, 202);
    }
    if (path === `/api/v1/index/status?job_id=${id}`) return json({ connected: true, job: { id, user_id: owner, operation: "SYNC", status: "completed", processed: 3 } });
    if (path === "/api/v1/index/status") return json({ connected: true, job: null });
    throw new Error("Unexpected API request");
  }));
  const completed = vi.fn(), c = new DiscoveryController(owner, completed);
  await c.check(); await c.start();
  expect(c.getSnapshot().phase).toBe("complete"); expect(completed).toHaveBeenCalledOnce();
  const writes = vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST");
  expect(writes).toHaveLength(1); expect(writes[0][0]).toBe("/api/v1/index/sync?full=false");
  expect(vi.mocked(fetch).mock.calls.every(([path]) => !/ingest|chunk|build|content/.test(String(path)))).toBe(true);
});

const key = `drivemind:discovery:v1:${owner}`;
const other = "00000000-0000-0000-0000-000000000066";
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const accepted = () => json({ job_id: id, status: "queued", message: "Accepted" }, 202);
const running = () => ({ connected: true, job: { id, user_id: owner, operation: "SYNC", status: "running" } });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
function server(options: { session?: () => Promise<Response>; post?: () => Promise<Response> } = {}) {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path === "/api/v1/auth/session") return options.session ? options.session() : json({ kind: "GOOGLE_ACCOUNT", user_id: owner, csrf_token: "synthetic" });
    if (path === "/api/v1/index/sync?full=false") return options.post ? options.post() : accepted();
    if (path === `/api/v1/index/status?job_id=${id}`) return json(running());
    if (path === "/api/v1/index/status") return json({ connected: true, job: null });
    throw new Error("Unexpected route");
  }));
}
function posts() { return vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST"); }

it("session inspection failure before POST clears only its own marker and allows explicit retry after status check", async () => {
  let failing = true;
  server({ session: async () => { if (failing) throw new Error("offline"); return json({ kind: "GOOGLE_ACCOUNT", user_id: owner, csrf_token: "synthetic" }); } });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(posts()).toHaveLength(0); expect(window.localStorage.getItem(key)).toBeNull(); expect(c.getSnapshot().phase).toBe("blocked");
  failing = false;
  await c.start(); expect(posts()).toHaveLength(0); // Must reconcile first.
  await c.check(); expect(c.getSnapshot().phase).toBe("idle");
  await c.start(); expect(posts()).toHaveLength(1); expect(c.getSnapshot().phase).toBe("active");
});
it.each([undefined, "", "   ", 123])("invalid CSRF (%s) is pre-submission, not unknown acceptance", async csrf => {
  server({ session: async () => json({ user_id: owner, csrf_token: csrf }) });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(posts()).toHaveLength(0); expect(window.localStorage.getItem(key)).toBeNull(); expect(c.getSnapshot().phase).toBe("blocked");
});
it.each([
  [401, "Your application session is invalid or expired."],
  [403, "Application session request could not be verified."],
  [409, "An unresolved indexing job already exists for this account."],
])("documented rejection %s releases its matching intent without automatic replay", async (status, detail) => {
  server({ post: async () => json({ detail }, Number(status)) });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(posts()).toHaveLength(1); expect(window.localStorage.getItem(key)).toBeNull();
  const next = new DiscoveryController(owner, vi.fn()); await next.check();
  expect(next.getSnapshot().phase).toBe("idle"); expect(posts()).toHaveLength(1);
});
it("explicit retry is possible after admission conflict and fresh authoritative reconciliation", async () => {
  let reject = true;
  server({ post: async () => reject ? json({ detail: "An unresolved indexing job already exists for this account." }, 409) : accepted() });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(c.getSnapshot().phase).toBe("blocked"); reject = false;
  await c.start(); expect(posts()).toHaveLength(1);
  await c.check(); await c.start(); expect(posts()).toHaveLength(2); expect(c.getSnapshot().phase).toBe("active");
});
it.each([500, 502, 503, 504, 409])("generic HTTP %s is not proof of non-acceptance", async status => {
  server({ post: async () => json({ detail: "Response unavailable" }, status) });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(c.getSnapshot().phase).toBe("unknown"); expect(JSON.parse(window.localStorage.getItem(key)!).jobId).toBeNull();
  await c.check(); await c.start(); expect(posts()).toHaveLength(1);
});
it.each([new TypeError("reset"), new DOMException("aborted", "AbortError"), new DOMException("timeout", "TimeoutError")])("transport failure remains blocked: %s", async error => {
  server({ post: async () => { throw error; } });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  const next = new DiscoveryController(owner, vi.fn()); await next.check(); await next.start();
  expect(next.getSnapshot().phase).toBe("unknown"); expect(posts()).toHaveLength(1);
});
it("accepted receipt after navigation persists its exact job without obsolete state publication", async () => {
  const response = deferred<Response>(), sent = deferred<void>();
  server({ post: () => { sent.resolve(); return response.promise; } });
  const done = vi.fn(), listener = vi.fn(), c = new DiscoveryController(owner, done); c.subscribe(listener);
  await c.check(); const pending = c.start(); await sent.promise; c.dispose(); listener.mockClear();
  response.resolve(accepted()); await pending;
  expect(JSON.parse(window.localStorage.getItem(key)!)).toMatchObject({ jobId: id, submissionId: expect.any(String) });
  expect(listener).not.toHaveBeenCalled(); expect(done).not.toHaveBeenCalled();
  const next = new DiscoveryController(owner, done); await next.check();
  expect(fetch).toHaveBeenLastCalledWith(`/api/v1/index/status?job_id=${id}`, expect.anything());
  expect(next.getSnapshot().phase).toBe("active"); expect(posts()).toHaveLength(1);
});
it.each(["account switch", "same-owner revalidation"])("persists the captured owner's receipt during %s while keeping the client fence", async transition => {
  const response = deferred<Response>(), sent = deferred<void>();
  server({ post: () => { sent.resolve(); return response.promise; } });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); const pending = c.start(); await sent.promise;
  const newer = JSON.stringify({ submissionId: "other-owner-intent", jobId: null, revision: 999 });
  window.localStorage.setItem(`drivemind:discovery:v1:${other}`, newer);
  setSessionOwner(null); invalidateSessionRequests();
  setSessionOwner(transition === "account switch" ? other : owner);
  response.resolve(accepted()); await pending;
  expect(JSON.parse(window.localStorage.getItem(key)!).jobId).toBe(id);
  expect(window.localStorage.getItem(`drivemind:discovery:v1:${other}`)).toBe(newer);
  expect(c.getSnapshot().phase).toBe("submitting"); // Obsolete controller never publishes.
  if (transition === "same-owner revalidation") {
    const next = new DiscoveryController(owner, vi.fn()); await next.check();
    expect(next.getSnapshot().job?.id).toBe(id); expect(posts()).toHaveLength(1);
  }
});
it.each(["accepted", "rejected", "preflight failure"])("late %s never overwrites or clears a newer same-owner intent", async outcome => {
  const response = deferred<Response>(), sent = deferred<void>();
  server(outcome === "preflight failure"
    ? { session: () => { sent.resolve(); return response.promise; } }
    : { post: () => { sent.resolve(); return response.promise; } });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); const pending = c.start(); await sent.promise;
  const newer = JSON.stringify({ submissionId: "newer-intent", jobId: null, revision: 999 });
  window.localStorage.setItem(key, newer);
  response.resolve(outcome === "accepted" ? accepted() : json({ detail: "An unresolved indexing job already exists for this account." }, 409));
  await pending; expect(window.localStorage.getItem(key)).toBe(newer);
});
it("an older terminal status read cannot clear a newer intent", async () => {
  window.localStorage.setItem(key, JSON.stringify({ submissionId: "old", jobId: id }));
  const response = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn(() => response.promise));
  const c = new DiscoveryController(owner, vi.fn()); const pending = c.check();
  const newer = JSON.stringify({ submissionId: "newer", jobId: null }); window.localStorage.setItem(key, newer);
  response.resolve(json({ connected: true, job: { ...running().job, status: "completed" } }));
  await pending; expect(window.localStorage.getItem(key)).toBe(newer); expect(c.getSnapshot().phase).toBe("unknown");
});
it("browser coordination unavailability prevents POST without leaving an uncertain marker", async () => {
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined }); server();
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(posts()).toHaveLength(0); expect(window.localStorage.getItem(key)).toBeNull(); expect(c.getSnapshot().phase).toBe("blocked");
});
it("simultaneous controllers use matching locked publication and submit at most once", async () => {
  const response = deferred<Response>(), sent = deferred<void>();
  server({ post: () => { sent.resolve(); return response.promise; } });
  const a = new DiscoveryController(owner, vi.fn()), b = new DiscoveryController(owner, vi.fn());
  await Promise.all([a.check(), b.check()]);
  const starts = Promise.all([a.start(), b.start()]); await sent.promise;
  const intent = JSON.parse(window.localStorage.getItem(key)!);
  expect(intent.jobId).toBeNull(); expect(posts()).toHaveLength(1);
  response.resolve(accepted()); await starts;
  expect(JSON.parse(window.localStorage.getItem(key)!)).toMatchObject({ submissionId: intent.submissionId, jobId: id });
});
it("a successful-looking body without HTTP 202 stays ambiguous", async () => {
  server({ post: async () => json({ job_id: id, status: "queued" }, 200) });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(c.getSnapshot().phase).toBe("unknown"); expect(JSON.parse(window.localStorage.getItem(key)!).jobId).toBeNull();
});

it.each(["storage cleanup", "Web Lock acquisition"])("current-session 401 unmounts private UI despite failed %s", async failure => {
  server({ post: async () => {
    // Preflight and initial publication succeeded. Only rejection bookkeeping fails.
    if (failure === "storage cleanup") {
      window.localStorage.removeItem = () => { throw new Error("Storage denied"); };
    } else {
      Object.defineProperty(navigator, "locks", { configurable: true, value: {
        request: async () => { throw new Error("Lock rejected"); },
      } });
    }
    return json({ detail: "Your application session is invalid or expired." }, 401);
  } });
  const invalid = vi.fn(); window.addEventListener(SESSION_INVALID_EVENT, invalid);
  try {
    render(<ApplicationSessionProvider><p>Private discovery workspace</p></ApplicationSessionProvider>);
    await screen.findByText("Private discovery workspace");
    expect(sessionOwner()).toBe(owner);
    const c = new DiscoveryController(owner, vi.fn());
    await act(async () => { await c.check(); await c.start(); });
    expect(invalid).toHaveBeenCalledOnce(); expect(sessionOwner()).toBeNull();
    expect(screen.queryByText("Private discovery workspace")).toBeNull();
    expect(screen.getByRole("button", { name: "Sign in with Google" })).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(key)!).jobId).toBeNull();
    expect(c.getSnapshot().phase).toBe("submitting"); // No stale private publication after invalidation.
    await c.start(); expect(posts()).toHaveLength(1);
    expect(posts()[0][0]).toBe("/api/v1/index/sync?full=false");
  } finally { window.removeEventListener(SESSION_INVALID_EVENT, invalid); }
});

it.each(["storage write", "Web Lock acquisition"])("202 with failed receipt %s stays unknown and is never replayed", async failure => {
  server({ post: async () => {
    if (failure === "storage write") {
      window.localStorage.setItem = () => { throw new Error("Receipt storage denied"); };
    } else {
      Object.defineProperty(navigator, "locks", { configurable: true, value: {
        request: async () => { throw new Error("Receipt lock rejected"); },
      } });
    }
    return accepted();
  } });
  const completed = vi.fn(), c = new DiscoveryController(owner, completed);
  const phases: string[] = [];
  c.subscribe(() => phases.push(c.getSnapshot().phase));
  await c.check(); await c.start();
  expect(c.getSnapshot().phase).toBe("unknown");
  expect(phases).not.toContain("active");
  expect(phases).not.toContain("complete");
  expect(JSON.parse(window.localStorage.getItem(key)!).jobId).toBeNull();
  expect(completed).not.toHaveBeenCalled();
  const next = new DiscoveryController(owner, completed); await next.check(); await next.start();
  expect(next.getSnapshot().phase).toBe("unknown"); expect(posts()).toHaveLength(1);
  expect(posts()[0][0]).toBe("/api/v1/index/sync?full=false");
});
