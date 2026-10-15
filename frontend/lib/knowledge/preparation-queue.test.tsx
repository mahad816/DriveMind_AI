import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PreparationQueue } from "./preparation-queue";
import { readPreparationGate } from "./preparation-queue-store";
import { SingleFilePreparation, preparationKey } from "./single-file-preparation";
import { DiscoveryController } from "./discovery";
import { invalidateSessionRequests, SESSION_INVALID_EVENT, setSessionOwner } from "@/lib/api/session-events";
import type { DriveFileRead, IndexingJobRead } from "@/lib/api/types";
const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
const owner = "00000000-0000-0000-0000-000000000065", other = "00000000-0000-0000-0000-000000000066";
const key = preparationKey(owner);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
let files: DriveFileRead[], latest: IndexingJobRead | null, jobs: Map<string, IndexingJobRead>, values: Map<string, string>, counter: number;
let intercept: (path: string, init: RequestInit) => Promise<Response> | undefined;
const inventory = () => json({ files, total: files.length });
const proof = () => json({ user_id: owner, csrf_token: "synthetic" });
const stored = () => JSON.parse(values.get(key)!);
const posts = () => vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
const targets = () => posts().map(([path]) => String(path));
function complete(extra: Partial<IndexingJobRead> = {}) {
  Object.assign(latest!, { status: "completed", processed: 1, succeeded: 1, ...extra });
  files.find(f => f.id === latest!.file_id)!.status = latest!.operation === "BUILD" ? "indexed" : "indexing";
}
async function queue(count = 2) {
  const q = new PreparationQueue(owner);
  expect(await q.reserve(files.slice(0, count))).toBe(true); expect(posts()).toHaveLength(0); return q;
}
async function ready(q: PreparationQueue) { complete(); await q.check(); complete(); await q.check(); complete(); await q.check(); }
function delayPreflight() {
  const entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p.endsWith("/auth/session") ? (entered.resolve(), response.promise) : undefined;
  return { entered, response };
}
beforeEach(() => {
  mode.demo = false; setSessionOwner(owner); values = new Map(); jobs = new Map(); latest = null; counter = 0; intercept = () => undefined;
  files = Array.from({ length: 6 }, (_, n) => ({ id: `00000000-0000-0000-0001-${String(n + 1).padStart(12, "0")}`, user_id: owner, drive_file_id: `synthetic-${n}`, name: `Synthetic ${n}.txt`, mime_type: "text/plain", status: "discovered", modified_at: "2026-01-01", indexed_at: null, folder_path: null, created_at: "", updated_at: "" }));
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) } });
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_key: string, fn: () => unknown) => fn() } });
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit = {}) => {
    const custom = intercept(path, init); if (custom) return custom;
    const url = new URL(path, "http://localhost");
    if (url.pathname === "/api/v1/files") return inventory();
    if (url.pathname === "/api/v1/auth/session") return proof();
    if (url.pathname === "/api/v1/index/status") return json({ connected: true, job: url.searchParams.has("job_id") ? jobs.get(url.searchParams.get("job_id")!) : latest });
    expect(init.method).toBe("POST"); expect(url.pathname).toMatch(/^\/api\/v1\/index\/(ingest|chunk|build)$/);
    expect(latest === null || !["queued", "running"].includes(latest.status)).toBe(true);
    const file = files.find(f => f.id === url.searchParams.get("file_id"));
    expect(file).toBeDefined(); expect(init.headers).toMatchObject({ "X-CSRF-Token": "synthetic" });
    latest = { id: `00000000-0000-0002-0000-${String(++counter).padStart(12, "0")}`, user_id: owner, file_id: file!.id, operation: url.pathname.split("/").at(-1)!.toUpperCase() as IndexingJobRead["operation"], status: "running", recovery_required: false, total: 1, processed: 0, succeeded: 0, skipped: 0, failed: 0, started_at: null, completed_at: null, error: null, created_at: "", updated_at: "" };
    jobs.set(latest.id, latest); file!.status = "indexing"; return json({ job_id: latest.id, status: "queued" }, 202);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); setSessionOwner(null); });

it.each([1, 5])("reserves %i ordered files without processing, targets all stages and requires explicit next confirmation", async count => {
  const q = await queue(count), batch = stored().batchId;
  for (let i = 0; i < count; i++) {
    expect(stored().current).toBe(i); expect(stored().entries[i].receipts).toEqual([]);
    await q.check(); await q.check(); expect(posts()).toHaveLength(i * 3);
    await q.confirm(); await ready(q);
    expect(stored().batchId).toBe(batch); expect(stored().current).toBe(i + 1); expect(posts()).toHaveLength((i + 1) * 3);
    expect(q.getSnapshot().phase).toBe(i + 1 === count ? "complete" : "awaiting_next");
  }
  expect(targets()).toEqual(files.slice(0, count).flatMap(f => ["ingest", "chunk", "build"].map(s => `/api/v1/index/${s}?file_id=${f.id}`)));
  await q.check(); expect(q.getSnapshot().phase).toBe("complete"); expect(await q.finish()).toBe(true); expect(values.has(key)).toBe(false);
});
it.each(["empty", "six", "duplicate", "indexed", "failed", "skipped", "unsupported", "foreign"])("rejects %s selection without reserving or submitting", async kind => {
  let selected = files.slice(0, 2);
  if (kind === "empty") selected = []; else if (kind === "six") selected = files; else if (kind === "duplicate") selected = [files[0], files[0]];
  else if (kind === "unsupported") files[0].mime_type = "application/zip"; else if (kind === "foreign") files[0].user_id = other;
  else files[0].status = kind as DriveFileRead["status"];
  const q = new PreparationQueue(owner); expect(await q.reserve(selected)).toBe(false); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(0);
});
it("freezes reviewed metadata across reservation and revalidates before initial POST", async () => {
  const entered = deferred<void>(), response = deferred<Response>(), reviewed = files.map(f => ({ ...f }));
  intercept = p => p === "/api/v1/files" ? (entered.resolve(), response.promise) : undefined;
  const q = new PreparationQueue(owner), pending = q.reserve(reviewed.slice(0, 2)); await entered.promise;
  files[0].modified_at = "changed"; reviewed[0].modified_at = "changed"; response.resolve(inventory());
  expect(await pending).toBe(false); expect(posts()).toHaveLength(0);
  intercept = () => undefined; expect(await q.reserve(files.slice(0, 2))).toBe(true); files[0].modified_at = "changed again";
  await q.confirm(); expect(posts()).toHaveLength(0); expect(q.getSnapshot().phase).toBe("blocked");
});
it.each(["INGEST", "CHUNK", "BUILD"])("refresh during accepted %s observes its exact job and requires continuation", async stage => {
  const q = await queue(); await q.confirm();
  if (stage !== "INGEST") { complete(); await q.check(); } if (stage === "BUILD") { complete(); await q.check(); }
  const receipt = stored().entries[0].receipts.at(-1), count = posts().length; q.dispose();
  const remount = new PreparationQueue(owner); await remount.check(); expect(remount.getSnapshot().child!.job!.id).toBe(receipt.jobId); expect(posts()).toHaveLength(count);
  complete(); await remount.check(); expect(posts()).toHaveLength(count);
  if (stage !== "BUILD") { await remount.confirm(); expect(posts()).toHaveLength(count + 1); } else expect(remount.getSnapshot().phase).toBe("awaiting_next");
});
it("refresh between files preserves historical success when a later job becomes latest", async () => {
  const q = await queue(); await q.confirm(); await ready(q); const first = stored().entries[0]; q.dispose();
  const remount = new PreparationQueue(owner); await remount.check(); await remount.check(); expect(posts()).toHaveLength(3);
  expect(remount.getSnapshot().phase).toBe("awaiting_next"); await remount.confirm(); expect(latest!.file_id).toBe(files[1].id);
  await remount.check(); expect(remount.getSnapshot().phase).toBe("progress"); expect(stored().entries[0]).toEqual(first); expect(posts()).toHaveLength(4);
});
it("completion and cursor handoff are one write and never release the discovery gate", async () => {
  const q = await queue(); await q.confirm(); complete(); await q.check(); complete(); await q.check(); complete(); const writes: string[] = [];
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => { if (k === key) writes.push(v); values.set(k, v); }, removeItem: () => { throw new Error("Must not release gate"); } } });
  await q.check(); expect(writes).toHaveLength(1); expect(JSON.parse(writes[0]).entries[0].result).toBe("ready"); expect(JSON.parse(writes[0]).current).toBe(1);
  const discovery = new DiscoveryController(owner, vi.fn()); await discovery.check(); await discovery.start();
  expect(posts()).toHaveLength(3); expect(values.has(key)).toBe(true); expect(discovery.getSnapshot().phase).toBe("blocked");
});
it.each(["pause", "dispose"] as const)("%s during CHUNK preflight prevents POST and restores just that intent", async action => {
  const q = await queue(); await q.confirm(); const before = values.get(key); complete();
  const gate = delayPreflight(), pending = q.check(); await gate.entered.promise; q[action](); gate.response.resolve(proof()); await pending;
  expect(posts()).toHaveLength(1); expect(values.get(key)).toBe(before);
});
it("pause during BUILD preflight cannot submit BUILD", async () => {
  const q = await queue(); await q.confirm(); complete(); await q.check(); complete();
  const before = values.get(key), gate = delayPreflight(), pending = q.check(); await gate.entered.promise; q.pause(); gate.response.resolve(proof()); await pending;
  expect(posts()).toHaveLength(2); expect(values.get(key)).toBe(before);
});
it("pause while awaiting intent lock prevents POST", async () => {
  const q = await queue(), entered = deferred<void>(), release = deferred<void>(); let first = true;
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_k: string, fn: () => unknown) => {
    if (first) { first = false; entered.resolve(); await release.promise; } return fn();
  } } });
  const pending = q.confirm(); await entered.promise; q.pause(); release.resolve(); await pending;
  expect(posts()).toHaveLength(0); expect(stored().entries[0].receipts).toEqual([]);
});
it("accepted receipt persists after navigation and session fencing", async () => {
  const q = await queue(), entered = deferred<void>(), response = deferred<Response>(), jobId = "00000000-0000-0002-0000-000000000099";
  intercept = (_p, i) => i.method === "POST" ? (entered.resolve(), response.promise) : undefined;
  const pending = q.confirm(); await entered.promise; q.dispose(); invalidateSessionRequests(); setSessionOwner(other); values.set(preparationKey(other), "other owner's marker");
  response.resolve(json({ job_id: jobId, status: "queued" }, 202)); await pending;
  expect(stored().entries[0].receipts[0].jobId).toBe(jobId); expect(values.get(preparationKey(other))).toBe("other owner's marker"); expect(posts()).toHaveLength(1);
});
it.each(["lost acknowledgement", "timeout", "generic 503"])("%s blocks later stages/files without replay", async failure => {
  const q = await queue();
  intercept = (_p, i) => i.method === "POST" ? failure === "generic 503" ? Promise.resolve(json({}, 503)) : Promise.reject(failure === "timeout" ? new DOMException("Timed out", "TimeoutError") : new TypeError("Connection reset")) : undefined;
  await q.confirm(); const before = values.get(key); q.dispose(); const remount = new PreparationQueue(owner); await remount.check(); await remount.confirm();
  expect(posts()).toHaveLength(1); expect(stored().current).toBe(0); expect(stored().entries[0].receipts[0].jobId).toBeNull(); expect(values.get(key)).toBe(before); expect(await remount.finish()).toBe(false);
});
it.each(["failed", "skipped", "recovery"])("%s on second file stops queue and preserves previous success", async outcome => {
  const q = await queue(3); await q.confirm(); await ready(q); const first = stored().entries[0]; await q.confirm();
  complete(outcome === "failed" ? { status: "failed", failed: 1, succeeded: 0 } : outcome === "skipped" ? { skipped: 1, succeeded: 0 } : { recovery_required: true });
  if (outcome === "failed" || outcome === "skipped") files[1].status = outcome;
  await q.check(); await q.confirm(); await q.check(); expect(posts()).toHaveLength(4); expect(stored().current).toBe(1); expect(stored().entries[0]).toEqual(first); expect(stored().entries[2].receipts).toEqual([]);
  expect(q.getSnapshot().phase).toBe(outcome === "recovery" ? "blocked" : "stopped"); if (outcome === "recovery") expect(await q.finish()).toBe(false);
});
it("BUILD completion without indexed inventory cannot advance", async () => {
  const q = await queue(); await q.confirm(); complete(); await q.check(); complete(); await q.check(); complete(); files[0].status = "indexing";
  await q.check(); await q.confirm(); expect(stored().current).toBe(0); expect(posts()).toHaveLength(3); expect(q.getSnapshot().phase).toBe("blocked");
});
it.each(["storage", "missing locks", "rejected lock"])("%s fails closed before reservation", async failure => {
  if (failure === "storage") Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: () => { throw new Error("Denied"); } } });
  else Object.defineProperty(navigator, "locks", { configurable: true, value: failure === "missing locks" ? undefined : { request: async () => { throw new Error("Denied"); } } });
  const q = new PreparationQueue(owner); expect(await q.reserve(files.slice(0, 2))).toBe(false); expect(posts()).toHaveLength(0);
});
it.each(["receipt storage", "receipt lock"])("%s failure after accepted POST stays uncertain", async failure => {
  const q = await queue(); let locks = 0;
  if (failure === "receipt lock") Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_k: string, fn: () => unknown) => { if (++locks > 1) throw new Error("Denied"); return fn(); } } });
  else Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => {
    if (JSON.parse(v).entries[0].receipts[0]?.jobId) throw new Error("Denied"); values.set(k, v);
  } } });
  await q.confirm(); await q.check(); await q.confirm(); expect(posts()).toHaveLength(1); expect(stored().entries[0].receipts[0].jobId).toBeNull(); expect(stored().current).toBe(0);
});
it("401 still invalidates the session when queue cleanup loses its lock", async () => {
  const q = await queue(), invalid = vi.fn(); window.addEventListener(SESSION_INVALID_EVENT, invalid); let locks = 0;
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_k: string, fn: () => unknown) => { if (++locks > 1) throw new Error("Denied"); return fn(); } } });
  intercept = (_p, i) => i.method === "POST" ? Promise.resolve(json({ detail: "Your application session is invalid or expired." }, 401)) : undefined;
  try { await q.confirm(); expect(invalid).toHaveBeenCalledTimes(1); expect(posts()).toHaveLength(1); expect(stored().entries[0].receipts[0].jobId).toBeNull(); }
  finally { window.removeEventListener(SESSION_INVALID_EVENT, invalid); }
});
it("definite rejection restores only attempted stage and allows explicit checked retry", async () => {
  const q = await queue(); intercept = (_p, i) => i.method === "POST" ? Promise.resolve(json({ detail: "Application session request could not be verified." }, 403)) : undefined;
  await q.confirm(); expect(stored().entries[0].receipts).toEqual([]); expect(posts()).toHaveLength(1);
  intercept = () => undefined; await q.check(); expect(posts()).toHaveLength(1); await q.confirm(); expect(posts()).toHaveLength(2); expect(stored().entries[0].receipts[0].jobId).toBeTruthy();
});
it("competing controllers cannot reserve or submit duplicate stages", async () => {
  const a = new PreparationQueue(owner), b = new PreparationQueue(owner);
  expect((await Promise.all([a.reserve(files.slice(0, 2)), b.reserve(files.slice(0, 2))])).filter(Boolean)).toHaveLength(1);
  await a.check(); await b.check(); await Promise.all([a.confirm(), b.confirm()]); expect(posts()).toHaveLength(1);
  a.pause(); b.pause(); complete(); await a.check(); await b.check(); await Promise.all([a.confirm(), b.confirm()]); expect(posts()).toHaveLength(2);
});
it.each([false, true])("stale permission/cleanup cannot affect replacement batch (same file=%s)", async sameFile => {
  const a = await queue(1); await a.confirm(); const oldBatch = stored().batchId, closer = new PreparationQueue(owner); await closer.check();
  complete(); await closer.check(); await closer.confirm(); complete(); await closer.check(); complete(); await closer.check(); expect(await closer.finish()).toBe(true);
  if (sameFile) files[0].status = "discovered";
  const b = new PreparationQueue(owner); expect(await b.reserve([files[sameFile ? 0 : 1]])).toBe(true); await b.confirm(); b.pause(); complete();
  expect(stored().batchId).not.toBe(oldBatch); const before = values.get(key), count = posts().length;
  expect(await a.finish()).toBe(false); await a.check(); await a.check(); expect(posts()).toHaveLength(count); expect(values.get(key)).toBe(before);
});
it("delayed old status cannot reactivate permission on a replacement child run", async () => {
  const q = await queue(); await q.confirm(); const old = { ...latest! }, entered = deferred<void>(), response = deferred<Response>(); let once = true;
  intercept = p => p.includes(`job_id=${old.id}`) && once ? (once = false, entered.resolve(), response.promise) : undefined;
  const pending = q.check(); await entered.promise; const newer = stored(); newer.entries[0].runId = crypto.randomUUID(); values.set(key, JSON.stringify(newer)); const before = values.get(key);
  response.resolve(json({ connected: true, job: { ...old, status: "completed", processed: 1, succeeded: 1 } })); await pending; await q.check(); expect(posts()).toHaveLength(1); expect(values.get(key)).toBe(before);
});
it.each(["owner", "revision"])("%s change during preflight prevents queue submission", async change => {
  const q = await queue(), gate = delayPreflight(), pending = q.confirm(); await gate.entered.promise;
  if (change === "owner") setSessionOwner(other); else invalidateSessionRequests(); gate.response.resolve(proof()); await pending;
  expect(posts()).toHaveLength(0); expect(stored().entries[0].receipts).toEqual([]);
});
it("legacy records stay untouched and continue through the original controller", async () => {
  const legacy = new SingleFilePreparation(owner, files[0].id); await legacy.check(); await legacy.confirm(); const before = values.get(key), q = new PreparationQueue(owner);
  await q.check(); expect(q.getSnapshot().phase).toBe("legacy"); expect(readPreparationGate(owner).kind).toBe("legacy");
  expect(await q.reserve([files[1]])).toBe(false); expect(values.get(key)).toBe(before); complete(); await legacy.check(); expect(posts()).toHaveLength(2);
});
it("uncertain legacy record is never migrated, cleared or resubmitted", async () => {
  const legacy = new SingleFilePreparation(owner, files[0].id); await legacy.check(); intercept = (_p, i) => i.method === "POST" ? Promise.reject(new TypeError("Lost")) : undefined; await legacy.confirm();
  const before = values.get(key), q = new PreparationQueue(owner); await q.check(); await q.confirm(); expect(await q.finish()).toBe(false); expect(values.get(key)).toBe(before); expect(posts()).toHaveLength(1);
});
it("Checkpoint B controller cannot parse, overwrite or close a batch", async () => {
  const q = await queue(), before = values.get(key), old = new SingleFilePreparation(owner, files[0].id);
  await old.check(); await old.confirm(); expect(await old.finish()).toBe(false); expect(old.getSnapshot().phase).toBe("unknown"); expect(values.get(key)).toBe(before); expect(posts()).toHaveLength(0);
  await q.confirm(); expect(posts()).toHaveLength(1);
});
it.each(["unknown version", "malformed", "duplicate IDs", "foreign owner", "invalid cursor"])("%s stays blocked and untouched", async kind => {
  await queue(); const value = stored();
  if (kind === "unknown version") value.schemaVersion = 99; if (kind === "malformed") value.entries = null;
  if (kind === "duplicate IDs") value.entries[1].fileId = value.entries[0].fileId; if (kind === "foreign owner") value.owner = other; if (kind === "invalid cursor") value.current = 2;
  values.set(key, JSON.stringify(value)); const before = values.get(key), q = new PreparationQueue(owner);
  await q.check(); await q.confirm(); expect(await q.reserve(files.slice(0, 2))).toBe(false); expect(await q.finish()).toBe(false);
  expect(values.get(key)).toBe(before); expect(posts()).toHaveLength(0); expect(q.getSnapshot().phase).toBe("blocked");
});
it("HarborDesk/demo mode performs no queue storage or network work", async () => {
  mode.demo = true; const q = new PreparationQueue(owner); await q.check(); expect(await q.reserve(files.slice(0, 2))).toBe(false); await q.confirm(); expect(await q.finish()).toBe(false);
  expect(fetch).not.toHaveBeenCalled(); expect(values.size).toBe(0);
});

it.each(["pause", "dispose"] as const)("%s during reservation refresh or its lock never reserves stale consent", async action => {
  const q = new PreparationQueue(owner), entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p === "/api/v1/files" ? (entered.resolve(), response.promise) : undefined;
  const pending = q.reserve(files.slice(0, 2)); await entered.promise; q[action](); response.resolve(inventory());
  expect(await pending).toBe(false); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(0);
});
it.each(["pause", "dispose"] as const)("%s during next-file confirmation refresh cannot grant permission", async action => {
  const q = await queue(); await q.confirm(); await ready(q); await q.check();
  const entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p === "/api/v1/files" ? (entered.resolve(), response.promise) : undefined;
  const pending = q.confirm(); await entered.promise; q[action](); response.resolve(inventory()); await pending;
  expect(posts()).toHaveLength(3); expect(stored().entries[1].receipts).toEqual([]);
});
it("pause while reservation waits for its lock leaves no queue", async () => {
  const q = new PreparationQueue(owner), entered = deferred<void>(), release = deferred<void>();
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_k: string, fn: () => unknown) => { entered.resolve(); await release.promise; return fn(); } } });
  const pending = q.reserve(files.slice(0, 2)); await entered.promise; q.pause(); release.resolve();
  expect(await pending).toBe(false); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(0);
});
it("canceled preflight cleanup cannot overwrite a newer batch or another owner", async () => {
  const q = await queue(), gate = delayPreflight(), pending = q.confirm(); await gate.entered.promise;
  const newer = stored(); newer.batchId = crypto.randomUUID(); const replacement = JSON.stringify(newer);
  values.set(key, replacement); values.set(preparationKey(other), "unrelated marker"); q.pause(); gate.response.resolve(proof()); await pending;
  expect(posts()).toHaveLength(0); expect(values.get(key)).toBe(replacement); expect(values.get(preparationKey(other))).toBe("unrelated marker");
});
it("late accepted receipt cannot overwrite a newer same-file batch", async () => {
  const q = await queue(), entered = deferred<void>(), response = deferred<Response>();
  intercept = (_p, i) => i.method === "POST" ? (entered.resolve(), response.promise) : undefined;
  const pending = q.confirm(); await entered.promise; q.dispose();
  const newer = stored(); newer.batchId = crypto.randomUUID(); newer.entries[0].runId = crypto.randomUUID(); const replacement = JSON.stringify(newer); values.set(key, replacement);
  response.resolve(json({ job_id: "00000000-0000-0002-0000-000000000099", status: "queued" }, 202)); await pending;
  expect(values.get(key)).toBe(replacement); expect(posts()).toHaveLength(1);
});
it("historical results are reverified before next-file permission", async () => {
  const q = await queue(); await q.confirm(); await ready(q); const before = values.get(key);
  jobs.get(stored().entries[0].receipts[2].jobId)!.recovery_required = true;
  await q.confirm(); expect(posts()).toHaveLength(3); expect(values.get(key)).toBe(before); expect(q.getSnapshot().phase).toBe("blocked");
});
it("changed or removed next file blocks without repeating completed work", async () => {
  const q = await queue(); await q.confirm(); await ready(q); files.splice(1, 1);
  await q.check(); await q.confirm(); expect(posts()).toHaveLength(3); expect(stored().current).toBe(1); expect(stored().entries[0].result).toBe("ready"); expect(q.getSnapshot().phase).toBe("blocked");
});
it("failed atomic handoff retains the completed child and cannot start another file", async () => {
  const q = await queue(); await q.confirm(); complete(); await q.check(); complete(); await q.check(); complete(); const before = values.get(key);
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: () => { throw new Error("Denied"); } } });
  await q.check(); await q.confirm(); expect(values.get(key)).toBe(before); expect(posts()).toHaveLength(3); expect(q.getSnapshot().phase).toBe("blocked");
});
it("unknown acknowledgement on a later file preserves successful entries and blocks its tail", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); const first = stored().entries[0];
  intercept = (_p, i) => i.method === "POST" ? Promise.reject(new TypeError("Lost")) : undefined;
  await q.confirm(); q.dispose(); const remount = new PreparationQueue(owner); await remount.check(); await remount.confirm();
  expect(posts()).toHaveLength(4); expect(stored().entries[0]).toEqual(first); expect(stored().current).toBe(1); expect(stored().entries[2].receipts).toEqual([]); expect(await remount.finish()).toBe(false);
});
it("missing CSRF before POST restores the empty active child and requires explicit retry", async () => {
  const q = await queue(); intercept = p => p.endsWith("/auth/session") ? Promise.resolve(json({ user_id: owner })) : undefined;
  await q.confirm(); expect(posts()).toHaveLength(0); expect(stored().entries[0].receipts).toEqual([]);
  intercept = () => undefined; await q.check(); expect(posts()).toHaveLength(0); await q.confirm(); expect(posts()).toHaveLength(1);
});
it("discovery intent blocks reservation, and recovery-required legacy work keeps its exact receipt", async () => {
  const discoveryKey = `drivemind:discovery:v1:${owner}`; values.set(discoveryKey, JSON.stringify({ jobId: null }));
  const q = new PreparationQueue(owner); expect(await q.reserve(files.slice(0, 2))).toBe(false); expect(posts()).toHaveLength(0); values.delete(discoveryKey);
  const legacy = new SingleFilePreparation(owner, files[0].id); await legacy.check(); await legacy.confirm(); complete({ recovery_required: true }); const before = values.get(key);
  await q.check(); expect(q.getSnapshot().phase).toBe("legacy"); expect(await q.reserve([files[1]])).toBe(false);
  await legacy.check(); expect(legacy.getSnapshot().phase).toBe("blocked"); expect(await legacy.finish()).toBe(false); expect(values.get(key)).toBe(before);
});
it("an active backend job prevents a fresh reservation even without a local gate", async () => {
  const legacy = new SingleFilePreparation(owner, files[0].id); await legacy.check(); await legacy.confirm(); values.delete(key);
  const q = new PreparationQueue(owner); expect(await q.reserve([files[1]])).toBe(false); expect(posts()).toHaveLength(1); expect(values.has(key)).toBe(false);
});
it("an older controller with retained permission fails closed on a new queue envelope", async () => {
  const old = new SingleFilePreparation(owner, files[0].id); await old.check(); await old.confirm();
  const closer = new SingleFilePreparation(owner, files[0].id); await closer.check(); complete(); await closer.check(); await closer.confirm(); complete(); await closer.check(); complete(); await closer.check(); expect(await closer.finish()).toBe(true);
  const q = new PreparationQueue(owner); expect(await q.reserve(files.slice(1, 3))).toBe(true); const before = values.get(key);
  await old.check(); await old.confirm(); expect(await old.finish()).toBe(false); expect(values.get(key)).toBe(before); expect(posts()).toHaveLength(3);
});
it("known failed queue can be explicitly closed without retrying the unstarted tail", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); await q.confirm(); complete({ status: "failed", failed: 1, succeeded: 0 }); files[1].status = "failed";
  await q.check(); expect(stored().entries[0].result).toBe("ready"); expect(await q.finish()).toBe(true); expect(values.has(key)).toBe(false); expect(files[0].status).toBe("indexed"); expect(posts()).toHaveLength(4);
});

it("an explicit reserve-and-start action submits only its first exact child", async () => {
  const q = new PreparationQueue(owner); expect(await q.reserve(files.slice(0, 2), true)).toBe(true);
  expect(targets()).toEqual([`/api/v1/index/ingest?file_id=${files[0].id}`]);
  await ready(q); await q.check(); expect(posts()).toHaveLength(3); expect(q.getSnapshot().phase).toBe("awaiting_next");
});
it("pause during reserve-and-start metadata refresh cannot grant initial submission permission", async () => {
  const q = new PreparationQueue(owner), entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p === "/api/v1/files" ? (entered.resolve(), response.promise) : undefined;
  const pending = q.reserve(files.slice(0, 2), true); await entered.promise; q.pause(); response.resolve(inventory());
  expect(await pending).toBe(false); expect(posts()).toHaveLength(0); expect(values.has(key)).toBe(false);
});
it("reserve-and-start cannot follow a replacement batch adopted during reservation observation", async () => {
  const q = new PreparationQueue(owner); let reads = 0;
  intercept = p => {
    if (p === "/api/v1/files" && ++reads === 2) {
      const newer = stored(); newer.batchId = crypto.randomUUID(); newer.entries[0].runId = crypto.randomUUID(); values.set(key, JSON.stringify(newer));
    }
    return undefined;
  };
  expect(await q.reserve(files.slice(0, 2), true)).toBe(true); expect(posts()).toHaveLength(0);
});
it("a confirmation bound to the rendered child cannot authorize a different current batch", async () => {
  const q = await queue(), old = stored();
  const expected = { batchId: old.batchId, current: 0, fileId: old.entries[0].fileId, runId: old.entries[0].runId };
  const newer = stored(); newer.batchId = crypto.randomUUID(); values.set(key, JSON.stringify(newer)); await q.check();
  await q.confirm(expected); expect(posts()).toHaveLength(0);
});
it("reconnecting a disposed observer never revives automatic stage permission", async () => {
  const q = await queue(); await q.confirm(); q.dispose(); q.connect(); complete(); await q.check();
  expect(posts()).toHaveLength(1); expect(q.getSnapshot().child?.phase).toBe("continue");
});

it("a stale displayed close action cannot close a newer completed batch already observed by the controller", async () => {
  const q = await queue(1); await q.confirm(); await ready(q); const displayed = q.getSnapshot().queue!;
  const closer = new PreparationQueue(owner); await closer.check(); expect(await closer.finish()).toBe(true);
  const next = new PreparationQueue(owner); expect(await next.reserve([files[1]], true)).toBe(true); await ready(next);
  const before = values.get(key); await q.check(); expect(q.getSnapshot().phase).toBe("complete");
  expect(await q.finish(displayed)).toBe(false); expect(values.get(key)).toBe(before); expect(posts()).toHaveLength(6);
});
