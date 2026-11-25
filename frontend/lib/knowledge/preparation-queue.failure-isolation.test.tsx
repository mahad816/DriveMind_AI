import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PreparationQueue } from "./preparation-queue";
import { readPreparationGate } from "./preparation-queue-store";
import { preparationKey } from "./single-file-preparation";
import { setSessionOwner } from "@/lib/api/session-events";
import type { DriveFileRead, IndexingJobRead } from "@/lib/api/types";
const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
const owner = "00000000-0000-0000-0000-000000000065", other = "00000000-0000-0000-0000-000000000066";
const key = preparationKey(owner);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
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

// Checkpoint A queue contract (owner-approved 2026-11-25; docs/tickets/ux-checkpoint-a/01-queue-failure-isolation.md).
// A confirmed FILE-SPECIFIC terminal outcome (job failed with the backend's "document" class, or completed-as-skipped, exact job and owner, no
// recovery flag, Drive connected) is recorded with its receipt and the cursor moves on in ONE atomic write; the next
// document still needs its own explicit confirmation. Anything uncertain or global keeps the queue paused.
// A definite file-specific failure also needs the backend's own structured evidence (failure_class "document", exactly one
// processed file, exactly one failed). Without it, or with any other class, the queue pauses.
// Retry is deliberately NOT part of this contract (backend retry safety is not established; see the ticket).
// A canceled job is not an outcome that may continue: it carries no evidence about the document (see the pause cases).
type Outcome = "failed" | "skipped";
/** Make the most recently submitted job end the way the backend would report it. */
function end(outcome: Outcome, file: DriveFileRead) {
  if (outcome === "failed") { complete({ status: "failed", failed: 1, succeeded: 0, failure_class: "document" }); file.status = "failed"; }
  else { complete({ skipped: 1, succeeded: 0 }); file.status = "skipped"; }
}
/** Confirm the current document, let it end with `outcome`, and observe it. */
async function failCurrent(q: PreparationQueue, index: number, outcome: Outcome = "failed") {
  await q.confirm(); end(outcome, files[index]); await q.check();
}
type Rec = { schemaVersion: number; current: number; entries: { result: string; receipts: unknown[] }[] };
const results = () => stored().entries.map((e: { result: string }) => e.result);
const forFile = (n: number) => targets().filter(t => t.includes(files[n].id));
const statusOf = (path: string) => { const u = new URL(path, "http://localhost"); return u.pathname === "/api/v1/index/status"; };

it.each(["failed", "skipped"] as Outcome[])("first document %s: its result and receipt are kept and the later documents continue, one confirmation each", async outcome => {
  const q = await queue(3); await failCurrent(q, 0, outcome);
  expect(results()).toEqual([outcome, "pending", "pending"]);
  expect(stored().current).toBe(1); expect(stored().entries[0].receipts.at(-1).jobId).toBeTruthy();
  expect(q.getSnapshot().phase).toBe("awaiting_next"); expect(posts()).toHaveLength(1);       // nothing starts by itself
  await q.confirm(); expect(posts()).toHaveLength(2); expect(posts().at(-1)![0]).toContain(`file_id=${files[1].id}`);
  await ready(q); expect(q.getSnapshot().phase).toBe("awaiting_next");
  await q.confirm(); await ready(q);
  expect(q.getSnapshot().phase).toBe("complete"); expect(stored().current).toBe(3);
  expect(results()).toEqual([outcome, "ready", "ready"]);
  expect([forFile(0).length, forFile(1).length, forFile(2).length]).toEqual([1, 3, 3]);        // no replay, no repeat
});
it("middle document fails: the final document is still offered and prepared", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); await failCurrent(q, 1);
  expect(results()).toEqual(["ready", "failed", "pending"]); expect(q.getSnapshot().phase).toBe("awaiting_next");
  await q.confirm(); expect(posts().at(-1)![0]).toContain(`file_id=${files[2].id}`); await ready(q);
  expect(results()).toEqual(["ready", "failed", "ready"]); expect(q.getSnapshot().phase).toBe("complete");
  expect(files[0].status).toBe("indexed"); expect(files[2].status).toBe("indexed");
});
it("last document fails: the queue completes with the failure shown honestly and can be closed", async () => {
  const q = await queue(2); await q.confirm(); await ready(q); await failCurrent(q, 1);
  expect(results()).toEqual(["ready", "failed"]); expect(stored().current).toBe(2);
  expect(q.getSnapshot().phase).toBe("complete"); expect(q.getSnapshot().message).not.toMatch(/All selected documents are confirmed ready/);
  expect(q.getSnapshot().message).toMatch(/1 ready.*1 could not be prepared/);
  expect(posts()).toHaveLength(4); expect(await q.finish()).toBe(true); expect(values.has(key)).toBe(false);
});
it("several independent failures are all recorded and every remaining document still runs", async () => {
  const q = await queue(4); await failCurrent(q, 0);
  await q.confirm(); await ready(q); await failCurrent(q, 2, "skipped"); await q.confirm(); await ready(q);
  expect(results()).toEqual(["failed", "ready", "skipped", "ready"]); expect(q.getSnapshot().phase).toBe("complete");
  expect(q.getSnapshot().message).toMatch(/2 ready.*2 could not be prepared/);
});
it("a skipped document followed by a valid one", async () => {
  const q = await queue(2); await failCurrent(q, 0, "skipped"); await q.confirm(); await ready(q);
  expect(results()).toEqual(["skipped", "ready"]); expect(q.getSnapshot().phase).toBe("complete");
});
it("an all-failed batch completes and can be closed", async () => {
  const q = await queue(2); await failCurrent(q, 0); await failCurrent(q, 1);
  expect(results()).toEqual(["failed", "failed"]); expect(q.getSnapshot().phase).toBe("complete"); expect(await q.finish()).toBe(true);
});
it("a browser refresh or navigation after a failure restores the same state and repeats nothing", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); await failCurrent(q, 1); const saved = values.get(key), count = posts().length;
  q.dispose(); const again = new PreparationQueue(owner); await again.check(); await again.check();
  expect(values.get(key)).toBe(saved); expect(posts()).toHaveLength(count); expect(again.getSnapshot().phase).toBe("awaiting_next");
  expect(results()).toEqual(["ready", "failed", "pending"]);
  await again.confirm(); expect(posts()).toHaveLength(count + 1); expect(posts().at(-1)![0]).toContain(`file_id=${files[2].id}`);
  expect([forFile(0).length, forFile(1).length]).toEqual([3, 1]);
});
it("two tabs observing the same failure advance once and submit the next document once", async () => {
  const q = await queue(3); await q.confirm(); end("failed", files[0]);
  const other = new PreparationQueue(owner);
  await Promise.all([q.check(), other.check()]); await Promise.all([q.check(), other.check()]);
  expect(stored().current).toBe(1); expect(results()).toEqual(["failed", "pending", "pending"]);
  await Promise.all([q.confirm(), other.confirm()]);
  expect(forFile(1)).toHaveLength(1); expect(forFile(2)).toHaveLength(0); expect(stored().current).toBe(1);
});
it("a queue record advanced by another tab during the check is never advanced twice, and the next check recovers", async () => {
  const q = await queue(3); await q.confirm(); end("failed", files[0]);
  let advanced = false;
  intercept = p => {
    if (!advanced && statusOf(p) && p.includes("job_id")) {
      advanced = true; const r = stored(); r.schemaVersion = 3; r.current = 1; r.entries[0].result = "failed"; values.set(key, JSON.stringify(r));
    }
    return undefined;
  };
  await q.check();
  expect(stored().current).toBe(1); expect(results()).toEqual(["failed", "pending", "pending"]);   // not 2: no double advance
  expect(q.getSnapshot().phase).toBe("blocked"); expect(posts()).toHaveLength(1);
  intercept = () => undefined; await q.check();
  expect(q.getSnapshot().phase).toBe("awaiting_next"); expect(stored().current).toBe(1); expect(posts()).toHaveLength(1);
});
it("a record edited elsewhere between the read and the write is never overwritten", async () => {
  const q = await queue(3); await q.confirm(); end("failed", files[0]);
  let edited = false;
  intercept = p => { if (!edited && statusOf(p) && p.includes("job_id")) { edited = true; const r = stored(); r.entries[2].frame = "changed elsewhere"; values.set(key, JSON.stringify(r)); } return undefined; };
  await q.check();
  expect(stored().current).toBe(0); expect(results()).toEqual(["pending", "pending", "pending"]); expect(stored().entries[2].frame).toBe("changed elsewhere"); expect(posts()).toHaveLength(1);
});
it("a changed session owner after a failure does not advance the queue", async () => {
  const q = await queue(3); await q.confirm(); end("failed", files[0]); setSessionOwner(other);
  await q.check(); setSessionOwner(owner);
  expect(stored().current).toBe(0); expect(results()).toEqual(["pending", "pending", "pending"]); expect(posts()).toHaveLength(1);
});
it("Drive disconnected at the moment of failure pauses without recording, then advances after reconnection", async () => {
  const q = await queue(3); await q.confirm(); end("failed", files[0]);
  intercept = p => statusOf(p) ? Promise.resolve(json({ connected: false, job: new URL(p, "http://localhost").searchParams.has("job_id") ? jobs.get(new URL(p, "http://localhost").searchParams.get("job_id")!) : latest })) : undefined;
  await q.check(); const n = posts().length;
  expect(stored().current).toBe(0); expect(results()).toEqual(["pending", "pending", "pending"]); expect(q.getSnapshot().phase).toBe("blocked");
  await q.confirm(); expect(posts()).toHaveLength(n);
  intercept = () => undefined; await q.check();
  expect(stored().current).toBe(1); expect(results()).toEqual(["failed", "pending", "pending"]); expect(q.getSnapshot().phase).toBe("awaiting_next");
});
it("a failed job that carries a recovery flag never advances", async () => {
  const q = await queue(3); await q.confirm(); complete({ status: "failed", failed: 1, succeeded: 0, recovery_required: true }); files[0].status = "failed";
  await q.check(); const n = posts().length; await q.confirm();
  expect(posts()).toHaveLength(n); expect(q.getSnapshot().phase).toBe("blocked"); expect(stored().current).toBe(0);
  // Superseded: a paused queue can now be ended locally (see the exit tests below); it is still never advanced or resubmitted.
  expect(await q.finish()).toBe(true); expect(posts()).toHaveLength(n);
});
it("a lost acknowledgement on a later document keeps its tail untouched after an earlier failure", async () => {
  const q = await queue(3); await failCurrent(q, 0);
  intercept = (_p, i) => i.method === "POST" ? Promise.reject(new TypeError("Lost")) : undefined;
  await q.confirm(); intercept = () => undefined; const n = posts().length;
  await q.check(); await q.confirm();
  expect(posts()).toHaveLength(n); expect(stored().current).toBe(1); expect(stored().entries[1].receipts.at(-1).jobId).toBeNull(); expect(stored().entries[2].receipts).toEqual([]);
  // Superseded: ending is a local action, so an uncertain tail can be dismissed. Nothing is submitted by it.
  expect(await q.finish()).toBe(true); expect(posts()).toHaveLength(n);
});
it("a failed document is never re-selected or re-submitted: retry stays deferred until backend safety is proven", async () => {
  const q = await queue(2); await failCurrent(q, 0); await q.confirm(); await ready(q); const n = posts().length;
  const next = new PreparationQueue(owner); expect(await next.reserve([files[0]])).toBe(false); expect(posts()).toHaveLength(n);
  expect(await q.finish()).toBe(true);
  expect(await new PreparationQueue(owner).reserve([files[0]])).toBe(false);
  expect(posts()).toHaveLength(n);
});
it("a finished queue whose history no longer matches the backend is not trusted", async () => {
  const q = await queue(3); await failCurrent(q, 0); const failedJob = stored().entries[0].receipts.at(-1).jobId;
  jobs.get(failedJob)!.status = "completed"; Object.assign(jobs.get(failedJob)!, { failed: 0, succeeded: 1, processed: 1 });
  await q.check(); const n = posts().length; await q.confirm();
  expect(q.getSnapshot().phase).toBe("blocked"); expect(posts()).toHaveLength(n);
});

// ---- Persistence and migration ----
it("a saved v2 queue that had stopped on a failed document is advanced on the next check, losing nothing", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); await q.confirm(); end("failed", files[1]);
  const record = stored(); record.schemaVersion = 2; record.entries[1].result = "failed"; values.set(key, JSON.stringify(record)); q.dispose();
  const fresh = new PreparationQueue(owner); await fresh.check();
  expect(stored().schemaVersion).toBe(3); expect(stored().current).toBe(2); expect(results()).toEqual(["ready", "failed", "pending"]);
  expect(stored().entries[1].receipts).toEqual(record.entries[1].receipts); expect(fresh.getSnapshot().phase).toBe("awaiting_next");
  expect(forFile(2)).toHaveLength(0);
});
it("a saved v2 queue with only ready history and a pending cursor is still read as is", async () => {
  const q = await queue(2); await q.confirm(); await ready(q); const record = stored(); record.schemaVersion = 2; values.set(key, JSON.stringify(record));
  const fresh = new PreparationQueue(owner); await fresh.check(); expect(fresh.getSnapshot().phase).toBe("awaiting_next"); expect(stored().entries[0].result).toBe("ready");
});
it.each([
  ["a failed entry before the cursor without its terminal receipt", (r: Rec) => { r.current = 1; r.entries[0].result = "failed"; r.entries[0].receipts = []; }],
  ["a pending entry before the cursor", (r: Rec) => { r.current = 1; }],
  ["a ready entry at or after the cursor", (r: Rec) => { r.entries[0].result = "ready"; }],
  ["a failed entry after the cursor", (r: Rec) => { r.entries[1].result = "failed"; }],
  ["a v3 cursor sitting on a failed entry", (r: Rec) => { r.schemaVersion = 3; r.entries[0].result = "failed"; }],
])("rejects %s and leaves the saved record untouched", async (_name, corrupt) => {
  const q = await queue(2); await q.confirm(); const r = stored(); corrupt(r); values.set(key, JSON.stringify(r)); const raw = values.get(key);
  expect(() => readPreparationGate(owner)).toThrow(); await new PreparationQueue(owner).check(); expect(values.get(key)).toBe(raw); expect(posts()).toHaveLength(1);
  void q;
});

// ---- Exit: a user must never be trapped in a half-finished queue (the old "stopped" state offered End preparation) ----
it("the user can explicitly end a queue that is waiting between documents; nothing in flight, nothing is touched", async () => {
  const q = await queue(3); await failCurrent(q, 0); expect(q.getSnapshot().phase).toBe("awaiting_next"); const n = posts().length;
  expect(await q.finish()).toBe(true); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(n);
  expect(files[1].status).toBe("discovered"); expect(files[2].status).toBe("discovered");
  expect(await new PreparationQueue(owner).reserve([files[1], files[2]])).toBe(true);   // the unstarted files can be selected again
});
it("a queue that has not started yet can be ended", async () => {
  const q = await queue(2); expect(await q.finish()).toBe(true); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(0);
});
it("a queue with a stage in flight cannot be ended", async () => {
  const q = await queue(3); await q.confirm(); expect(await q.finish()).toBe(false); expect(values.has(key)).toBe(true);
});


// ---- Checkpoint A review fix: only positively document-specific failures may continue ----
// The backend records a structured failure_class on every failed job. "document" is written only for extraction
// failures. Every other class, a missing class (older records) and implausible counters pause the queue.
const pausedCases: [string, Partial<IndexingJobRead>][] = [
  ["server restart or lease expiry (infrastructure, nothing processed)", { failed: 0, processed: 0, failure_class: "infrastructure" } as never],
  ["heartbeat failure", { failed: 0, processed: 0, failure_class: "infrastructure" } as never],
  ["unexpected stage exception", { failed: 0, processed: 0, failure_class: "unknown" } as never],
  ["Drive, embedding or Qdrant outage reported as a file failure", { failure_class: "provider" } as never],
  ["authentication expired", { failure_class: "authentication" } as never],
  ["configuration error, for example a missing OCR engine", { failure_class: "configuration" } as never],
  ["unknown classification", { failure_class: "unknown" } as never],
  ["an older job with no classification", { failure_class: undefined } as never],
  ["a null classification", { failure_class: null } as never],
  ["a classification that is not in the vocabulary", { failure_class: "document " } as never],
  ["document class but nothing was processed", { processed: 0 }],
  ["document class but no file was counted failed", { failed: 0 }],
  ["document class but more than one file", { total: 2, processed: 2, succeeded: 1 }],
  ["document class but a file also succeeded", { succeeded: 1 }],
  ["document class on a canceled job", { status: "canceled" as IndexingJobRead["status"] }],
];
it.each(pausedCases)("pauses, records nothing and submits nothing: %s", async (_name, extra) => {
  const q = await queue(3); await q.confirm();
  complete({ status: "failed", failed: 1, succeeded: 0, failure_class: "document", ...extra } as Partial<IndexingJobRead>); files[0].status = "failed";
  const before = values.get(key); const n = posts().length;
  await q.check(); await q.check();
  expect(q.getSnapshot().phase).toBe("blocked"); expect(values.get(key)).toBe(before); expect(stored().current).toBe(0);
  expect(results()).toEqual(["pending", "pending", "pending"]); expect(posts()).toHaveLength(n);
  await q.confirm(); expect(posts()).toHaveLength(n);                                    // confirmation cannot start anything either
  expect(q.getSnapshot().message).toMatch(/could not be confirmed|paused|system/i);
});
it("a skip needs the same exact evidence: one processed file, one skipped, nothing failed or succeeded", async () => {
  const q = await queue(3); await q.confirm();
  complete({ skipped: 1, succeeded: 0, failed: 1 }); files[0].status = "skipped"; await q.check();
  expect(q.getSnapshot().phase).not.toBe("awaiting_next"); expect(stored().current).toBe(0);
});
it("a document failure with exact evidence still advances (the one safe case)", async () => {
  const q = await queue(3); await failCurrent(q, 0);
  expect(results()).toEqual(["failed", "pending", "pending"]); expect(q.getSnapshot().phase).toBe("awaiting_next");
});
it("a saved v2 queue that stopped on a failed job with no classification fails closed on upgrade", async () => {
  const q = await queue(3); await q.confirm(); complete({ status: "failed", failed: 1, succeeded: 0 }); files[0].status = "failed";
  const record = stored(); record.schemaVersion = 2; record.entries[0].result = "failed"; values.set(key, JSON.stringify(record)); q.dispose();
  const fresh = new PreparationQueue(owner); await fresh.check();
  expect(["blocked", "stopped"]).toContain(fresh.getSnapshot().phase); expect(stored().schemaVersion).toBe(2); expect(stored().current).toBe(0); expect(posts()).toHaveLength(1);
});
it("a recorded failure whose job the backend now describes as another class is not trusted", async () => {
  const q = await queue(3); await failCurrent(q, 0); const jobId = stored().entries[0].receipts.at(-1).jobId;
  (jobs.get(jobId) as unknown as { failure_class: string }).failure_class = "provider";
  await q.check(); const n = posts().length; await q.confirm();
  expect(q.getSnapshot().phase).toBe("blocked"); expect(posts()).toHaveLength(n);
});
it("a recorded failure with no class on the saved job is not trusted either", async () => {
  const q = await queue(3); await failCurrent(q, 0); const jobId = stored().entries[0].receipts.at(-1).jobId;
  delete (jobs.get(jobId) as unknown as { failure_class?: string }).failure_class;
  await q.check(); expect(q.getSnapshot().phase).toBe("blocked");
});

// ---- Exit: a paused queue can always be ended locally, whatever the backend or Drive is doing ----
const fetched = () => vi.mocked(fetch).mock.calls.length;
it("a paused queue can be ended while Drive is disconnected, with no request of any kind", async () => {
  const q = await queue(3); await q.confirm(); end("failed", files[0]);
  intercept = p => statusOf(p) ? Promise.resolve(json({ connected: false, job: latest })) : undefined;
  await q.check(); expect(q.getSnapshot().phase).toBe("blocked");
  const calls = fetched(), n = posts().length;
  expect(await q.finish()).toBe(true);
  expect(fetched()).toBe(calls); expect(posts()).toHaveLength(n); expect(values.has(key)).toBe(false);
  // The last job is known to have ended, so the message must not suggest it may still run.
  expect(q.getSnapshot().message).toMatch(/already ended/i); expect(q.getSnapshot().message).not.toMatch(/may still finish/i);
});
it("ending after a lost acknowledgement is local, never resubmits, and says the server job was not cancelled", async () => {
  const q = await queue(3); await failCurrent(q, 0);
  intercept = (_p, i) => i.method === "POST" ? Promise.reject(new TypeError("Lost")) : undefined;
  await q.confirm(); intercept = () => undefined; await q.check();
  const calls = fetched(), n = posts().length;
  expect(await q.finish()).toBe(true); expect(fetched()).toBe(calls); expect(posts()).toHaveLength(n);
  expect(values.has(key)).toBe(false); expect(q.getSnapshot().message).toMatch(/not cancelled|was not cancelled|may still finish/i);
});
it("ending a queue that needs recovery review is local and never touches the backend", async () => {
  const q = await queue(3); await q.confirm(); complete({ status: "failed", failed: 1, succeeded: 0, recovery_required: true }); files[0].status = "failed"; await q.check();
  const calls = fetched(); expect(await q.finish()).toBe(true); expect(fetched()).toBe(calls); expect(values.has(key)).toBe(false);
});
it("ending a paused queue keeps the backend facts: earlier ready and failed files keep their states", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); await failCurrent(q, 1);
  intercept = p => statusOf(p) ? Promise.resolve(json({ connected: false, job: latest })) : undefined; await q.check();
  expect(await q.finish()).toBe(true);
  expect(files.map(f => f.status).slice(0, 3)).toEqual(["indexed", "failed", "discovered"]);
});
it("ending is refused while a stage is observed running, and a changed queue record is never closed", async () => {
  const q = await queue(2); await q.confirm(); expect(q.getSnapshot().phase).toBe("progress"); expect(await q.finish()).toBe(false); expect(values.has(key)).toBe(true);
  intercept = p => statusOf(p) ? Promise.resolve(json({ connected: false, job: latest })) : undefined; await q.check();
  const r = stored(); r.entries[1].frame = "changed elsewhere"; values.set(key, JSON.stringify(r));
  expect(await q.finish()).toBe(false); expect(values.has(key)).toBe(true);
});

// ---- Exit after a reload: a queue whose history cannot be verified stays endable (reviewer's probe, now permanent) ----
// A fresh controller starts with no queue loaded. When history verification fails (backend down, or the backend
// disagrees with the saved record) the blocked state must keep the record it read, so End preparation still works,
// still compare-and-sets, never submits and never claims anything about an uncertain job.
const down = () => { intercept = () => Promise.reject(new TypeError("backend down")); };
const reloaded = async () => { const fresh = new PreparationQueue(owner); await fresh.check(); return fresh; };
it("a queue past its first document can be ended after a reload while the backend is down", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); const n = posts().length;
  down(); const fresh = await reloaded();
  expect(fresh.getSnapshot().phase).toBe("blocked"); expect(fresh.getSnapshot().queue).not.toBeNull();
  expect(await fresh.finish()).toBe(true); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(n);
});
it("the same on a later document (cursor 2) with the backend down", async () => {
  const q = await queue(4); await q.confirm(); await ready(q); await q.confirm(); await ready(q); q.dispose(); expect(stored().current).toBe(2);
  down(); const fresh = await reloaded(); expect(fresh.getSnapshot().queue?.current).toBe(2); expect(await fresh.finish()).toBe(true);
});
it("a reload whose saved history the backend contradicts stays blocked, keeps the record and can be ended", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose();
  const jobId = stored().entries[0].receipts.at(-1).jobId; jobs.get(jobId)!.status = "failed"; const n = posts().length, before = values.get(key);
  const fresh = await reloaded();
  expect(fresh.getSnapshot().phase).toBe("blocked"); expect(fresh.getSnapshot().queue).not.toBeNull(); expect(values.get(key)).toBe(before);
  await fresh.confirm(); expect(posts()).toHaveLength(n);                                  // blocked: nothing can be started
  expect(await fresh.finish()).toBe(true); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(n);
});
it("a reload while only the indexing status endpoint fails keeps the queue endable", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose();
  intercept = p => statusOf(p) ? Promise.reject(new TypeError("status down")) : undefined;
  const fresh = await reloaded(); expect(fresh.getSnapshot().queue).not.toBeNull(); expect(await fresh.finish()).toBe(true);
});
it("an unknown job outcome on a later document, reloaded with the backend down, is kept, never resubmitted, and endable", async () => {
  const q = await queue(3); await q.confirm(); await ready(q);
  intercept = (_p, i) => i.method === "POST" ? Promise.reject(new TypeError("Lost")) : undefined; await q.confirm(); q.dispose();
  const n = posts().length; expect(stored().entries[1].receipts.at(-1).jobId).toBeNull();
  down(); const fresh = await reloaded(); await fresh.confirm();
  expect(fresh.getSnapshot().phase).toBe("blocked"); expect(posts()).toHaveLength(n);
  intercept = () => undefined; expect(await fresh.finish()).toBe(true); expect(posts()).toHaveLength(n);
  expect(fresh.getSnapshot().message).toMatch(/not cancelled|may still finish/i); expect(fresh.getSnapshot().message).not.toMatch(/completed|succeeded/i);
});
it("a compare-and-set conflict while ending leaves the other writer's record untouched and the queue blocked", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); down(); const fresh = await reloaded();
  expect(fresh.getSnapshot().queue).not.toBeNull();   // shown first, so only the compare-and-set can be what refuses
  const other = stored(); other.entries[2].frame = "changed by another tab"; values.set(key, JSON.stringify(other)); const edited = values.get(key);
  expect(await fresh.finish()).toBe(false); expect(values.get(key)).toBe(edited); expect(fresh.getSnapshot().phase).toBe("blocked");
});
it("repeated End clicks close once, never throw, and the later ones do nothing", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); down(); const fresh = await reloaded(); const n = posts().length;
  const [a, b] = await Promise.all([fresh.finish(), fresh.finish()]);
  expect([a, b].filter(Boolean)).toHaveLength(1); expect(values.has(key)).toBe(false);
  expect(await fresh.finish()).toBe(false); expect(posts()).toHaveLength(n);
});
it("after a successful exit normal navigation works: a new selection reserves without submitting anything", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); down(); const fresh = await reloaded(); const n = posts().length;
  expect(await fresh.finish()).toBe(true); intercept = () => undefined;
  expect(readPreparationGate(owner).kind).toBe("empty");
  const next = new PreparationQueue(owner); expect(await next.reserve([files[2]])).toBe(true);
  expect(posts()).toHaveLength(n); expect(next.getSnapshot().phase).toBe("review");              // consent still has to be given
  expect(await new PreparationQueue(owner).reserve([files[0]])).toBe(false);                   // the ready file is not selectable again
});
it("a dismissed queue does not make an in-progress file selectable again", async () => {
  const q = await queue(3); await q.confirm(); await ready(q);
  intercept = (_p, i) => i.method === "POST" ? Promise.reject(new TypeError("Lost")) : undefined; await q.confirm(); q.dispose(); intercept = () => undefined;
  down(); const fresh = await reloaded(); expect(await fresh.finish()).toBe(true); intercept = () => undefined;
  files[1].status = "indexing";                                                                  // the backend's own state for the uncertain file
  expect(await new PreparationQueue(owner).reserve([files[1]])).toBe(false);
});

it("a reload while Drive reports disconnected keeps the queue visible, inert and endable", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); const n = posts().length;
  intercept = p => statusOf(p) ? Promise.resolve(json({ connected: false, job: null })) : undefined;
  const fresh = await reloaded();
  expect(fresh.getSnapshot().phase).toBe("blocked"); expect(fresh.getSnapshot().queue).not.toBeNull();
  await fresh.confirm(); expect(posts()).toHaveLength(n);
  expect(await fresh.finish()).toBe(true); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(n);
});

// ---- Queue state lifecycle: the displayed record must be the persisted one, or dismissal can be refused for no reason ----
it("PROBE: the backend goes down during the next document's submission, with no reload, and End still works", async () => {
  const q = await queue(3); await q.confirm(); await ready(q);
  expect(q.getSnapshot().phase).toBe("awaiting_next"); expect(stored().current).toBe(1);
  intercept = (_p, i) => { if (i.method === "POST") { down(); return Promise.reject(new TypeError("Lost")); } return undefined; };
  await q.confirm(); const n = posts().length;
  expect(stored().entries[1].receipts.at(-1).jobId).toBeNull();                    // the unknown submission is recorded
  expect(q.getSnapshot().phase).toBe("blocked");
  expect(JSON.stringify(q.getSnapshot().queue)).toBe(values.get(key));             // what is shown is what is stored
  await q.confirm(); expect(posts()).toHaveLength(n);                              // still inert: no resubmission
  expect(await q.finish()).toBe(true); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(n);
  expect(q.getSnapshot().message).toMatch(/not cancelled and may still finish/i);
});
it("PROBE: a record corrupted after it was read is never deleted", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); down(); const fresh = await reloaded();
  values.set(key, JSON.stringify({ ...stored(), current: 99 })); const bad = values.get(key);
  expect(await fresh.finish()).toBe(false); expect(values.get(key)).toBe(bad); expect(fresh.getSnapshot().phase).toBe("blocked");
});
it("a tab that fell behind shows the other tab's newer record when its check fails, and can end it", async () => {
  const a = await queue(3); await a.confirm(); await ready(a);                       // tab A rests at cursor 1
  const b = new PreparationQueue(owner); await b.check(); await b.confirm();          // tab B submits document 2
  const newer = values.get(key); const n = posts().length; expect(stored().entries[1].receipts.length).toBeGreaterThan(0);
  down(); await a.check();                                                           // tab A's history check now fails
  expect(a.getSnapshot().phase).toBe("blocked"); expect(JSON.stringify(a.getSnapshot().queue)).toBe(newer);
  expect(await a.finish()).toBe(true); expect(values.has(key)).toBe(false); expect(posts()).toHaveLength(n);
  b.dispose();
});
it("a blocked tab whose queue another tab already ended cannot delete anything, and its next check releases it", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); down();
  const x = await reloaded(), y = await reloaded();
  expect(x.getSnapshot().queue).not.toBeNull(); expect(y.getSnapshot().queue).not.toBeNull();
  expect(await y.finish()).toBe(true); expect(values.has(key)).toBe(false);          // tab Y ends it
  expect(await x.finish()).toBe(false); expect(values.has(key)).toBe(false);         // tab X's End is refused: nothing left to delete
  await x.check(); expect(x.getSnapshot().phase).toBe("idle"); expect(x.getSnapshot().queue).toBeNull();
});
it("a blocked tab never overwrites or deletes a record another controller wrote after the screen last showed it", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); down(); const fresh = await reloaded();
  const first = stored(); first.entries[2].frame = "written by another controller"; values.set(key, JSON.stringify(first));
  await fresh.check(); await fresh.confirm();                                         // re-reading, and an inert confirm, write nothing
  expect(values.get(key)).toBe(JSON.stringify(first)); expect(JSON.stringify(fresh.getSnapshot().queue)).toBe(values.get(key));
  const second = stored(); second.entries[2].frame = "written again, not yet displayed"; values.set(key, JSON.stringify(second)); const theirs = values.get(key);
  expect(await fresh.finish()).toBe(false); expect(values.get(key)).toBe(theirs);     // the compare-and-set refuses what it never displayed
  expect(await fresh.finish(second)).toBe(false); expect(values.get(key)).toBe(theirs);
});
it("ending a paused queue never claims prepared documents remain available; with nothing sent it says so", async () => {
  const none = await queue(3); none.dispose(); down(); const a = await reloaded(); expect(a.getSnapshot().queue?.current).toBe(0);
  expect(await a.finish()).toBe(true); expect(a.getSnapshot().message).toMatch(/nothing was sent for the remaining documents/i); expect(a.getSnapshot().message).not.toMatch(/remain available/i);
  intercept = () => undefined;
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); jobs.get(stored().entries[0].receipts.at(-1).jobId)!.status = "failed";
  const b = await reloaded(); expect(await b.finish()).toBe(true); expect(b.getSnapshot().message).not.toMatch(/remain available/i);
});

// ---- Multi-tab consistency: child progress and job identity must belong to the record that is displayed ----
it("PROBE2-A: End never claims nothing is running when another tab submitted the next stage", async () => {
  const q = await queue(3); await q.confirm(); complete(); q.dispose();
  const a = await reloaded(); expect(a.getSnapshot().child?.phase).toBe("continue");
  const b = new PreparationQueue(owner); await b.check(); await b.confirm();
  const r = stored().entries[0].receipts.at(-1); expect(r.stage).toBe("CHUNK"); expect(jobs.get(r.jobId)!.status).toBe("running");
  const n = posts().length; down(); await a.check(); expect(a.getSnapshot().phase).toBe("blocked");
  expect(await a.finish()).toBe(true);
  expect(a.getSnapshot().message).not.toMatch(/nothing was left running/i);
  expect(a.getSnapshot().message).toMatch(/not cancelled and may still finish/i); expect(posts()).toHaveLength(n);
  b.dispose();
});
it("PROBE2-B: blocked() never shows a newer record with an older document's child", async () => {
  const q = await queue(3); await q.confirm(); end("failed", files[0]);
  intercept = p => statusOf(p) ? Promise.resolve(json({ connected: false, job: new URL(p, "http://localhost").searchParams.has("job_id") ? jobs.get(new URL(p, "http://localhost").searchParams.get("job_id")!) : latest })) : undefined;
  await q.check(); expect(q.getSnapshot().child?.phase).toBe("failed"); intercept = () => undefined;
  const b = new PreparationQueue(owner); await b.check(); await b.confirm(); expect(stored().current).toBe(1); expect(stored().entries[1].receipts).toHaveLength(1);
  down(); await q.check(); expect(q.getSnapshot().queue?.current).toBe(1);
  expect(q.getSnapshot().child?.phase).not.toBe("failed");
  expect(await q.finish()).toBe(true);
  expect(q.getSnapshot().message).not.toMatch(/nothing was left running/i);
  b.dispose();
});
it("blocked() shows the record stored at the moment of the failure, not the one read at the start of the check", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); expect(stored().current).toBe(1);
  intercept = p => { if (!statusOf(p)) return undefined; const o = stored(); o.entries[2].frame = "changed while this check was failing"; values.set(key, JSON.stringify(o)); return Promise.reject(new TypeError("down")); };
  await q.check(); expect(q.getSnapshot().phase).toBe("blocked");
  expect(JSON.stringify(q.getSnapshot().queue)).toBe(values.get(key));
});
it("two tabs confirming the same next document at once submit it once", async () => {
  const a = await queue(3); await a.confirm(); await ready(a); const b = new PreparationQueue(owner); await b.check();
  const n = posts().length; await Promise.all([a.confirm(), b.confirm()]);
  expect(posts().length - n).toBe(1); expect(stored().entries[1].receipts).toHaveLength(1); b.dispose();
});
it("a stale tab cannot submit, advance or overwrite what the other tab already moved", async () => {
  const a = await queue(3); await a.confirm(); await ready(a); const b = new PreparationQueue(owner); await b.check(); await b.confirm();
  const stateAfterB = values.get(key); const n = posts().length;
  await a.confirm();                                                                   // A still believes document 2 is unstarted
  expect(posts()).toHaveLength(n); expect(values.get(key)).toBe(stateAfterB); b.dispose();
});
it("a lost acknowledgement stays unknown after a reload with the backend back, and is never resubmitted", async () => {
  const q = await queue(3); await q.confirm(); await ready(q);
  intercept = (_p, i) => i.method === "POST" ? Promise.reject(new TypeError("Lost")) : undefined; await q.confirm(); q.dispose(); intercept = () => undefined;
  const n = posts().length; const fresh = await reloaded(); await fresh.confirm();
  expect(fresh.getSnapshot().phase).toBe("blocked"); expect(posts()).toHaveLength(n); expect(stored().entries[1].receipts.at(-1).jobId).toBeNull();
});
it("a new queue after ending one carries no progress from the earlier queue", async () => {
  const q = await queue(3); await q.confirm(); await ready(q); q.dispose(); down(); const fresh = await reloaded(); expect(await fresh.finish()).toBe(true); intercept = () => undefined;
  expect(fresh.getSnapshot().child).toBeNull();
  expect(await fresh.reserve([files[2]])).toBe(true);
  expect(fresh.getSnapshot().queue?.batchId).not.toBe(undefined); expect(fresh.getSnapshot().queue?.entries).toHaveLength(1);
  expect(fresh.getSnapshot().child?.job ?? null).toBeNull(); expect(fresh.getSnapshot().child?.file?.id ?? files[2].id).toBe(files[2].id);
});
