import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SingleFilePreparation, preparationKey } from "./single-file-preparation";
import { invalidateSessionRequests, sessionOwner, setSessionOwner } from "@/lib/api/session-events";
import type { DriveFileRead, IndexingJobRead } from "@/lib/api/types";

const owner = "00000000-0000-0000-0000-000000000065";
const other = "00000000-0000-0000-0000-000000000066";
const fileA = "00000000-0000-0000-0001-000000000001";
const fileB = "00000000-0000-0000-0001-000000000002";
const key = preparationKey(owner);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const proof = () => json({ user_id: owner, csrf_token: "synthetic" });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
let files: DriveFileRead[], latest: IndexingJobRead | null, jobs: Map<string, IndexingJobRead>;
let values: Map<string, string>, counter: number;
let intercept: (path: string, init: RequestInit) => Promise<Response> | undefined;
const inventory = () => json({ files, total: files.length });
const record = () => JSON.parse(values.get(key)!);
const posts = () => vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
const targets = () => posts().map(([path]) => String(path));
function complete() {
  Object.assign(latest!, { status: "completed", processed: 1, succeeded: 1 });
  files.find(f => f.id === latest!.file_id)!.status = latest!.operation === "BUILD" ? "indexed" : "indexing";
}
async function controller(file = fileA) { const c = new SingleFilePreparation(owner, file); await c.check(); return c; }
function delayPreflight() {
  const entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p.endsWith("/auth/session") ? (entered.resolve(), response.promise) : undefined;
  return { entered, response };
}
beforeEach(() => {
  setSessionOwner(owner); values = new Map(); latest = null; jobs = new Map(); counter = 0; intercept = () => undefined;
  files = [fileA, fileB].map((id, n) => ({ id, user_id: owner, drive_file_id: `synthetic-${n}`, name: `Synthetic ${n}.txt`, mime_type: "text/plain", status: "discovered", modified_at: "2026-01-01", indexed_at: null, folder_path: null, created_at: "", updated_at: "" }));
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) } });
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_key: string, fn: () => unknown) => fn() } });
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit = {}) => {
    const custom = intercept(path, init); if (custom) return custom;
    const url = new URL(path, "http://localhost");
    if (url.pathname === "/api/v1/files") return inventory();
    if (url.pathname === "/api/v1/auth/session") return proof();
    if (url.pathname === "/api/v1/index/status") return json({ connected: true, job: url.searchParams.has("job_id") ? jobs.get(url.searchParams.get("job_id")!) : latest });
    expect(init.method).toBe("POST");
    expect(url.pathname).toMatch(/^\/api\/v1\/index\/(ingest|chunk|build)$/);
    const target = files.find(f => f.id === url.searchParams.get("file_id"));
    expect(target).toBeDefined(); expect(init.headers).toMatchObject({ "X-CSRF-Token": "synthetic" });
    latest = { id: `00000000-0000-0002-0000-${String(++counter).padStart(12, "0")}`, user_id: owner, file_id: target!.id, operation: url.pathname.split("/").at(-1)!.toUpperCase() as IndexingJobRead["operation"], status: "running", recovery_required: false, total: 1, processed: 0, succeeded: 0, skipped: 0, failed: 0, started_at: null, completed_at: null, error: null, created_at: "", updated_at: "" };
    jobs.set(latest.id, latest); target!.status = "indexing";
    return json({ job_id: latest.id, status: "queued" }, 202);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); setSessionOwner(null); });

it.each(["pause", "dispose", "dispose and reconnect"] as const)("%s during CHUNK session preflight prevents POST and restores only the completed ingest receipt", async interruption => {
  const c = await controller(); await c.confirm(); const before = values.get(key); complete();
  const gate = delayPreflight(); const pending = c.check(); await gate.entered.promise;
  expect(record().receipts).toHaveLength(2); expect(record().receipts[1].jobId).toBeNull();
  if (interruption === "pause") c.pause(); else { c.dispose(); if (interruption === "dispose and reconnect") c.connect(); }
  gate.response.resolve(proof()); await pending;
  expect(targets()).toEqual([`/api/v1/index/ingest?file_id=${fileA}`]); expect(values.get(key)).toBe(before);
  intercept = () => undefined;
  const remount = await controller(); expect(remount.getSnapshot().phase).toBe("continue"); expect(posts()).toHaveLength(1);
  await remount.confirm(); expect(targets().at(-1)).toBe(`/api/v1/index/chunk?file_id=${fileA}`);
});
it("pause during BUILD preflight prevents build without erasing either accepted earlier stage", async () => {
  const c = await controller(); await c.confirm(); complete(); await c.check(); const before = values.get(key); complete();
  const gate = delayPreflight(), pending = c.check(); await gate.entered.promise; c.pause(); gate.response.resolve(proof()); await pending;
  expect(posts()).toHaveLength(2); expect(values.get(key)).toBe(before); expect(record().receipts).toHaveLength(2);
});
it.each(["pause", "dispose", "dispose and reconnect"] as const)("%s during confirmation metadata refresh cannot grant fresh permission", async interruption => {
  const c = await controller(), entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p === "/api/v1/files" ? (entered.resolve(), response.promise) : undefined;
  const pending = c.confirm(); await entered.promise;
  if (interruption === "pause") c.pause(); else { c.dispose(); if (interruption === "dispose and reconnect") c.connect(); }
  response.resolve(inventory()); await pending; expect(posts()).toHaveLength(0); expect(values.has(key)).toBe(false);
});
it.each(["pause", "dispose", "dispose and reconnect"] as const)("%s while waiting for intent Web Lock prevents POST", async interruption => {
  const c = await controller(), entered = deferred<void>(), release = deferred<void>(); let first = true;
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_key: string, fn: () => unknown) => {
    if (first) { first = false; entered.resolve(); await release.promise; } return fn();
  } } });
  const pending = c.confirm(); await entered.promise;
  if (interruption === "pause") c.pause(); else { c.dispose(); if (interruption === "dispose and reconnect") c.connect(); }
  release.resolve(); await pending; expect(posts()).toHaveLength(0); expect(values.has(key)).toBe(false);
});
it.each(["owner", "revision"] as const)("%s transition during session preflight cancels before POST", async change => {
  const c = await controller(), gate = delayPreflight(), pending = c.confirm(); await gate.entered.promise;
  if (change === "owner") setSessionOwner(other); else invalidateSessionRequests();
  gate.response.resolve(proof()); await pending; expect(posts()).toHaveLength(0); expect(values.has(key)).toBe(false);
});
it("pre-POST cancellation cannot clear a newer matching-owner intent or another owner's state", async () => {
  const c = await controller(), gate = delayPreflight(), pending = c.confirm(); await gate.entered.promise;
  const newer = JSON.stringify({ ...record(), runId: other }); values.set(key, newer);
  values.set(preparationKey(other), "unrelated synthetic marker"); c.pause(); gate.response.resolve(proof()); await pending;
  expect(posts()).toHaveLength(0); expect(values.get(key)).toBe(newer); expect(values.get(preparationKey(other))).toBe("unrelated synthetic marker");
});
it("intent replacement during preflight without lifecycle interruption also prevents the old POST", async () => {
  const c = await controller(), gate = delayPreflight(), pending = c.confirm(); await gate.entered.promise;
  const newer = JSON.stringify({ ...record(), runId: other }); values.set(key, newer); gate.response.resolve(proof()); await pending;
  expect(posts()).toHaveLength(0); expect(values.get(key)).toBe(newer);
});
it.each(["pause", "dispose"] as const)("%s after fetch invocation retains the accepted CHUNK receipt and stops further automatic stages", async interruption => {
  const c = await controller(); await c.confirm(); complete();
  const entered = deferred<void>(), response = deferred<Response>();
  // This is after the submission boundary: fetch has been invoked for CHUNK.
  const jobId = "00000000-0000-0002-0000-000000000099";
  intercept = (p, i) => i.method === "POST" && p.includes("/chunk?") ? (entered.resolve(), response.promise) : undefined;
  const pending = c.check(); await entered.promise; const ingest = jobs.get(record().receipts[0].jobId)!;
  latest = { ...ingest, id: jobId, operation: "CHUNK", status: "completed" }; jobs.set(jobId, latest);
  if (interruption === "pause") c.pause(); else c.dispose();
  response.resolve(json({ job_id: jobId, status: "queued" }, 202)); await pending;
  expect(record().receipts[1].jobId).toBe(jobId); expect(posts()).toHaveLength(2);
  intercept = () => undefined; const remount = await controller(); expect(remount.getSnapshot().phase).toBe("continue"); expect(remount.getSnapshot().job!.id).toBe(jobId); expect(posts()).toHaveLength(2);
});
it.each(["pause", "dispose"] as const)("%s after potentially sent POST cannot turn a lost response into rejection", async interruption => {
  const c = await controller(), entered = deferred<void>(), response = deferred<Response>();
  intercept = (_p, i) => i.method === "POST" ? (entered.resolve(), response.promise) : undefined;
  const pending = c.confirm(); await entered.promise; const reserved = values.get(key);
  if (interruption === "pause") c.pause(); else c.dispose();
  response.reject(new TypeError("Response lost after fetch invocation")); await pending;
  expect(values.get(key)).toBe(reserved); expect(record().receipts[0].jobId).toBeNull();
  const remount = await controller(); await remount.confirm(); expect(remount.getSnapshot().phase).toBe("unknown"); expect(posts()).toHaveLength(1);
});

async function replaceWorkflow(a: SingleFilePreparation, sameFile: boolean) {
  const originalRun = record().runId;
  // A retains its permission while an independent observer finishes and closes A.
  const closer = await controller(); complete(); await closer.check(); await closer.confirm();
  complete(); await closer.check(); complete(); expect(await closer.finish()).toBe(true);
  const target = sameFile ? fileA : fileB;
  if (sameFile) files[0].status = "discovered"; // Synthetic metadata rediscovery.
  const b = await controller(target); await b.confirm(); b.pause(); complete();
  expect(record().runId).not.toBe(originalRun); expect(record().fileId).toBe(target);
  return { b, target, a };
}
it.each([false, true])("automatic permission cannot transfer to a replacement run (same file=%s)", async sameFile => {
  const a = await controller(); await a.confirm();
  const { b, target } = await replaceWorkflow(a, sameFile); const before = values.get(key), count = posts().length;
  await a.check(); await a.check();
  expect(posts()).toHaveLength(count); expect(values.get(key)).toBe(before); expect(a.getSnapshot().phase).toBe("continue");
  await b.check(); await b.confirm(); expect(posts()).toHaveLength(count + 1); expect(targets().at(-1)).toBe(`/api/v1/index/chunk?file_id=${target}`);
});
it.each([false, true])("delayed old job response cannot reactivate permission on a newer run (same file=%s)", async sameFile => {
  const a = await controller(); await a.confirm(); const oldJob = { ...latest! };
  const entered = deferred<void>(), response = deferred<Response>(); let delayOnce = true;
  intercept = p => p.includes(`job_id=${oldJob.id}`) && delayOnce ? (delayOnce = false, entered.resolve(), response.promise) : undefined;
  const pending = a.check(); await entered.promise;
  await replaceWorkflow(a, sameFile); const before = values.get(key), count = posts().length;
  response.resolve(json({ connected: true, job: { ...oldJob, status: "completed", processed: 1, succeeded: 1 } })); await pending;
  await a.check(); expect(posts()).toHaveLength(count); expect(values.get(key)).toBe(before);
});
it("ownership changes fence delayed observations and cannot write or advance another owner's workflow", async () => {
  const a = await controller(); await a.confirm(); complete(); const before = values.get(key);
  const entered = deferred<void>(), response = deferred<Response>(); intercept = p => p === "/api/v1/files" ? (entered.resolve(), response.promise) : undefined;
  const pending = a.check(); await entered.promise; invalidateSessionRequests(); setSessionOwner(other); values.set(preparationKey(other), "other owner's synthetic state");
  response.resolve(inventory()); await pending; await a.confirm();
  expect(posts()).toHaveLength(1); expect(values.get(key)).toBe(before); expect(values.get(preparationKey(other))).toBe("other owner's synthetic state"); expect(sessionOwner()).toBe(other);
});
it("an uninterrupted controller still advances only its own targeted run to authoritative readiness", async () => {
  const a = await controller(); await a.confirm(); const run = record().runId;
  complete(); await a.check(); complete(); await a.check(); complete(); await a.check();
  expect(a.getSnapshot().phase).toBe("ready"); expect(record().runId).toBe(run);
  expect(targets()).toEqual(["ingest", "chunk", "build"].map(s => `/api/v1/index/${s}?file_id=${fileA}`));
});
it.each(["pause", "dispose"] as const)("%s during explicit continuation's metadata refresh cannot rearm the run", async interruption => {
  const c = await controller(); await c.confirm(); c.pause(); complete(); await c.check();
  expect(c.getSnapshot().phase).toBe("continue"); const before = values.get(key);
  const entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p === "/api/v1/files" ? (entered.resolve(), response.promise) : undefined;
  const pending = c.confirm(); await entered.promise;
  if (interruption === "pause") c.pause(); else c.dispose();
  response.resolve(inventory()); await pending;
  expect(targets()).toEqual([`/api/v1/index/ingest?file_id=${fileA}`]); expect(values.get(key)).toBe(before);
});
it("cancellation cleanup that loses its Web Lock preserves the intent and cannot trigger replay", async () => {
  const c = await controller(), gate = delayPreflight(), pending = c.confirm(); await gate.entered.promise;
  c.pause(); Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async () => { throw new Error("Lock unavailable"); } } });
  gate.response.resolve(proof()); await pending;
  expect(posts()).toHaveLength(0); expect(record().receipts[0].jobId).toBeNull();
  const remount = await controller(); await remount.confirm(); expect(remount.getSnapshot().phase).toBe("unknown"); expect(posts()).toHaveLength(0);
});
it.each([false, true])("an old controller cannot close an unseen newer terminal workflow (same file=%s)", async sameFile => {
  const a = await controller(); await a.confirm(); const { b } = await replaceWorkflow(a, sameFile);
  await b.check(); await b.confirm(); complete(); await b.check(); complete(); await b.check();
  expect(b.getSnapshot().phase).toBe("ready"); const before = values.get(key);
  expect(await a.finish()).toBe(false); expect(values.get(key)).toBe(before);
  expect(await b.finish()).toBe(true);
});
