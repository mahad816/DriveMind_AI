/**
 * Regression tests for KI-010 (a finished preparation must not block Drive discovery) and
 * KI-011 (a local refusal must name its real cause). They exercise the real controller and the
 * real preparation-store validation; only the network and browser storage are faked.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiscoveryController } from "./discovery";
import { readPreparationGate } from "./preparation-queue-store";
import { preparationKey } from "./single-file-preparation";
import { getDriveSyncStatus, syncDriveMetadata, SyncSubmissionError } from "@/lib/api/indexing";
import { setSessionOwner } from "@/lib/api/session-events";
import type { IndexingJobRead } from "@/lib/api/types";

vi.mock("@/lib/demo", () => ({ DEMO_MODE: false }));
vi.mock("@/lib/api/indexing", async original => ({ ...await original<typeof import("@/lib/api/indexing")>(), getDriveSyncStatus: vi.fn(), syncDriveMetadata: vi.fn() }));

const owner = "00000000-0000-0000-0000-000000000065";
const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const discoveryKey = `drivemind:discovery:v1:${owner}`;
const prepKey = preparationKey(owner);
let values: Map<string, string>;

const receipts = (jobs: (number | null)[]) =>
  (["INGEST", "CHUNK", "BUILD"] as const).slice(0, jobs.length).map((stage, i) => ({ stage, submissionId: id(500 + i), jobId: jobs[i] === null ? null : id(jobs[i]!) }));
const entry = (n: number, result: "pending" | "ready" | "failed" | "skipped", jobs: (number | null)[]) => ({ fileId: id(n), runId: id(n + 50), frame: "frame", receipts: receipts(jobs), result });
const queue = (current: number, entries: ReturnType<typeof entry>[]) => ({ schemaVersion: 2, owner, batchId: id(200), current, entries });
const seed = (record: unknown) => values.set(prepKey, JSON.stringify(record));
const finished = () => queue(2, [entry(1, "ready", [11, 12, 13]), { ...entry(2, "ready", [21, 22, 23]),
  receipts: receipts([21, 22, 23]).map((r, i) => ({ ...r, submissionId: id(600 + i) })) }]);
const syncJob = (status: IndexingJobRead["status"]): IndexingJobRead => ({ id: id(900), user_id: owner, status, operation: "SYNC", recovery_required: false, processed: 3, total: 3, started_at: null, completed_at: null, error: null, created_at: "", updated_at: "" });

beforeEach(() => {
  vi.clearAllMocks(); setSessionOwner(owner); values = new Map();
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_n: string, cb: () => unknown) => cb() } });
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) } });
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: null });
  vi.mocked(syncDriveMetadata).mockResolvedValue({ job_id: id(900), status: "queued", message: "Accepted" });
});
afterEach(() => setSessionOwner(null));

async function tryDiscovery() {
  const c = new DiscoveryController(owner, vi.fn());
  await c.check(); await c.start();
  return c;
}

// --- KI-010 -----------------------------------------------------------------------------

it("the fixtures are valid records (so the blocking tests below are meaningful)", () => {
  seed(finished()); expect(readPreparationGate(owner).kind).toBe("queue");
  seed(queue(0, [entry(1, "pending", [])])); expect(readPreparationGate(owner).kind).toBe("queue");
});

it("KI-010: a fully completed queue no longer blocks discovery; it is cleared and the sync is submitted once", async () => {
  seed(finished());
  // Two idle status reads (check, then start's re-check), then the accepted job.
  vi.mocked(getDriveSyncStatus).mockResolvedValueOnce({ connected: true, job: null }).mockResolvedValueOnce({ connected: true, job: null })
    .mockResolvedValue({ connected: true, job: syncJob("running") });
  const c = await tryDiscovery();
  expect(syncDriveMetadata).toHaveBeenCalledOnce();
  expect(c.getSnapshot().phase).toBe("active");
  expect(values.has(prepKey)).toBe(false);                       // closed, like "Close completed preparation"
  expect(readPreparationGate(owner).kind).toBe("empty");
  expect(JSON.parse(values.get(discoveryKey)!)).toMatchObject({ jobId: id(900) });
});

it.each([
  ["pending first document", () => queue(0, [entry(1, "pending", [])])],
  ["half done: one ready, next pending", () => queue(1, [entry(1, "ready", [11, 12, 13]), entry(2, "pending", [])])],
  ["a failed document", () => queue(0, [entry(1, "failed", [11])])],
  ["a skipped document", () => queue(0, [entry(1, "skipped", [11])])],
])("KI-010: unfinished work still blocks discovery and is left untouched (%s)", async (_name, build) => {
  seed(build()); const before = values.get(prepKey);
  const c = await tryDiscovery();
  expect(c.getSnapshot().phase).toBe("blocked");
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  expect(values.get(prepKey)).toBe(before);                       // never modified
  expect(values.has(discoveryKey)).toBe(false);                   // and no stray discovery intent left behind
});

it.each([
  ["a legacy single-document record", { fileId: id(1), runId: id(51), frame: "frame", receipts: receipts([11]) }],
  ["unreadable text", "not-json{"],
  ["an unknown future schema version", { schemaVersion: 99, owner, batchId: id(200), current: 0, entries: [] }],
  ["a queue owned by someone else", { ...queue(1, [entry(1, "ready", [11, 12, 13])]), owner: id(77) }],
  ["a queue whose cursor lies about completion", queue(1, [entry(1, "pending", [])])],
])("KI-010: uncertain or foreign records keep blocking and are never deleted (%s)", async (_name, record) => {
  values.set(prepKey, typeof record === "string" ? record : JSON.stringify(record)); const before = values.get(prepKey);
  const c = await tryDiscovery();
  expect(c.getSnapshot().phase).toBe("blocked");
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  expect(values.get(prepKey)).toBe(before);
});

it("KI-010: a completed queue of ANOTHER owner is not this owner's business", async () => {
  values.set(preparationKey(id(77)), JSON.stringify({ ...queue(1, [entry(1, "ready", [11, 12, 13])]), owner: id(77) }));
  await tryDiscovery();
  expect(syncDriveMetadata).toHaveBeenCalledOnce();
  expect(values.has(preparationKey(id(77)))).toBe(true);
});

it("KI-010: adopting an already-running sync (started in another tab) also works past a completed queue", async () => {
  seed(finished());
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: syncJob("running") });
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  expect(c.getSnapshot().phase).toBe("active");
  expect(syncDriveMetadata).not.toHaveBeenCalled();               // observed, never resubmitted
  expect(values.has(prepKey)).toBe(false);
});

it("KI-010: after the sync the user can start a fresh preparation (the gate is empty, not stuck)", async () => {
  seed(finished()); await tryDiscovery();
  expect(readPreparationGate(owner)).toEqual({ kind: "empty" });
});

it("KI-010: a rejected submission still leaves a clean state (finished batch already closed, no discovery intent)", async () => {
  seed(finished());
  vi.mocked(syncDriveMetadata).mockRejectedValue(new SyncSubmissionError("not_submitted"));
  const c = await tryDiscovery();
  expect(c.getSnapshot().phase).toBe("blocked");
  expect(values.has(discoveryKey)).toBe(false);
  expect(values.has(prepKey)).toBe(false);
});

// --- KI-011 -----------------------------------------------------------------------------

it("KI-011: unfinished preparation is named as the reason, not the connection", async () => {
  seed(queue(0, [entry(1, "pending", [])]));
  const m = (await tryDiscovery()).getSnapshot().message;
  expect(m).toMatch(/preparation is unfinished/i);
  expect(m).toMatch(/Preparation screen/);
  expect(m).not.toMatch(/connection/i);
  expect(m).toMatch(/not started/i);
});

it("KI-011: an unreadable preparation record says so, and does not say 'unfinished'", async () => {
  values.set(prepKey, "garbage");
  const m = (await tryDiscovery()).getSnapshot().message;
  expect(m).toMatch(/could not be read/i);
  expect(m).not.toMatch(/connection|unfinished/i);
});

it("KI-011: missing browser coordination (no Web Locks) names coordination, not the connection", async () => {
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
  await c.start();
  const m = c.getSnapshot().message;
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  expect(m).toMatch(/coordinate/i);
  expect(m).not.toMatch(/verify your connection/i);
});

it("KI-011: denied browser storage is reported as a browser problem, with an honest 'nothing was sent'", async () => {
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: () => null, setItem: () => { throw new DOMException("denied", "SecurityError"); }, removeItem: () => undefined } });
  await c.start();
  const m = c.getSnapshot().message;
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  expect(m).toMatch(/browser storage/i);
  expect(m).toMatch(/Nothing was sent to Drive/);
  expect(m).not.toMatch(/verify your connection/i);
});

it("KI-011: a discovery already pending (another tab won the lock race) says that", async () => {
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  // The other tab's intent lands in the instant before our own compare-and-set runs under the lock.
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_n: string, cb: () => unknown) => {
    values.set(discoveryKey, JSON.stringify({ jobId: null, submissionId: id(1), revision: 0 })); return cb();
  } } });
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: null });
  await c.start();
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  expect(c.getSnapshot().message).toMatch(/already pending/i);
  expect(values.get(discoveryKey)).toContain(id(1));              // their intent is preserved
});

it("KI-011: a genuine rejection AFTER the request was sent still suggests the connection (that is its real cause)", async () => {
  vi.mocked(syncDriveMetadata).mockRejectedValue(new SyncSubmissionError("not_submitted"));
  const m = (await tryDiscovery()).getSnapshot().message;
  expect(syncDriveMetadata).toHaveBeenCalledOnce();
  expect(m).toMatch(/not accepted/i);
  expect(m).toMatch(/verify your connection/i);
});

it("KI-011: while a sync is running elsewhere and preparation is unfinished, tracking it explains why it cannot", async () => {
  seed(queue(0, [entry(1, "pending", [])]));
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: syncJob("running") });
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  expect(c.getSnapshot().message).toMatch(/preparation/i);
  expect(c.getSnapshot().message).not.toMatch(/Discovery status is unavailable/);
  expect(syncDriveMetadata).not.toHaveBeenCalled();
});
