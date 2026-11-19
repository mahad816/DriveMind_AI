/**
 * KI-012: "Check status" used to be silently discarded while the controller was busy.
 * These tests drive the real controllers with controllable network promises.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DiscoveryController } from "./discovery";
import { PreparationQueue } from "./preparation-queue";
import { preparationKey } from "./single-file-preparation";
import { getDriveSyncStatus, syncDriveMetadata } from "@/lib/api/indexing";
import { listDriveFiles } from "@/lib/api/files";
import { setSessionOwner } from "@/lib/api/session-events";

vi.mock("@/lib/demo", () => ({ DEMO_MODE: false }));
vi.mock("@/lib/api/indexing", async original => ({ ...await original<typeof import("@/lib/api/indexing")>(), getDriveSyncStatus: vi.fn(), syncDriveMetadata: vi.fn() }));
vi.mock("@/lib/api/files", async original => ({ ...await original<typeof import("@/lib/api/files")>(), listDriveFiles: vi.fn() }));

const owner = "00000000-0000-0000-0000-000000000065";
const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
let values: Map<string, string>;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const deferred = <T,>() => { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };

const receipts = (jobs: (number | null)[]) =>
  (["INGEST", "CHUNK", "BUILD"] as const).slice(0, jobs.length).map((stage, i) => ({ stage, submissionId: id(500 + i), jobId: jobs[i] === null ? null : id(jobs[i]!) }));
const entry = (n: number, result: "pending" | "ready", jobs: (number | null)[]) => ({ fileId: id(n), runId: id(n + 50), frame: "frame", receipts: receipts(jobs), result });
const seedHistoryQueue = () => values.set(preparationKey(owner), JSON.stringify({ schemaVersion: 2, owner, batchId: id(200), current: 1, entries: [entry(1, "ready", [11, 12, 13]), entry(2, "pending", [])] }));

beforeEach(() => {
  vi.clearAllMocks(); setSessionOwner(owner); values = new Map();
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_n: string, cb: () => unknown) => cb() } });
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) } });
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: null });
  vi.mocked(syncDriveMetadata).mockResolvedValue({ job_id: id(900), status: "queued", message: "Accepted" });
});
afterEach(() => setSessionOwner(null));

// --- PreparationQueue ---------------------------------------------------------------------

function slowQueue() {
  seedHistoryQueue();
  const release = deferred<{ files: never[]; total: number }>();
  vi.mocked(listDriveFiles).mockImplementation(() => release.promise);
  return { queue: new PreparationQueue(owner), release: () => release.resolve({ files: [], total: 0 }) };
}

it("KI-012 queue: a second check() mid-check waits for the real check and shares its network read", async () => {
  const { queue, release } = slowQueue();
  const first = queue.check(); await tick();
  let secondDone = false;
  const second = queue.check().then(() => { secondDone = true; });
  await tick();
  expect(secondDone).toBe(false);                                 // not "done" while the real check still runs
  expect(listDriveFiles).toHaveBeenCalledOnce();                  // joined, not duplicated
  release(); await Promise.all([first, second]);
  expect(secondDone).toBe(true);
  expect(queue.getSnapshot().phase).not.toBe("checking");         // it observed the real outcome
});

it("KI-012 queue: both callers see the same published result, and a later click re-checks for real", async () => {
  const { queue, release } = slowQueue();
  const a = queue.check(), b = queue.check(); release(); await Promise.all([a, b]);
  const reads = vi.mocked(listDriveFiles).mock.calls.length;
  await queue.check();
  expect(vi.mocked(listDriveFiles).mock.calls.length).toBe(reads + 1);   // a finished check is never replayed from cache
});

it("KI-012 queue: a click while the queue is reserving waits for it instead of vanishing", async () => {
  const inventory = deferred<{ files: never[]; total: number }>();
  vi.mocked(listDriveFiles).mockImplementation(() => inventory.promise);
  const queue = new PreparationQueue(owner);
  const reserving = queue.reserve([{ id: id(1), user_id: owner } as never]);   // busy section: awaiting inventory
  await tick();
  let checked = false;
  const click = queue.check().then(() => { checked = true; });
  await tick();
  expect(checked).toBe(false);                                   // waits out the in-progress operation
  inventory.resolve({ files: [], total: 0 }); await reserving; await click;
  expect(checked).toBe(true);
});

it("KI-012 queue: a click after dispose resolves immediately and does nothing", async () => {
  const { queue } = slowQueue(); queue.dispose();
  await expect(queue.check()).resolves.toBeUndefined();
  expect(listDriveFiles).not.toHaveBeenCalled();
});

it("KI-012 queue: a failing check still resolves every joined caller (and reports blocked)", async () => {
  seedHistoryQueue();
  vi.mocked(listDriveFiles).mockRejectedValue(new Error("network"));
  const queue = new PreparationQueue(owner);
  await Promise.all([queue.check(), queue.check()]);
  expect(queue.getSnapshot().phase).toBe("blocked");
});

// --- DiscoveryController ------------------------------------------------------------------

it("KI-012 discovery: a second check() mid-check joins it (one status read) and finishes with it", async () => {
  const c = new DiscoveryController(owner, vi.fn());
  const release = deferred<{ connected: boolean; job: null }>();
  vi.mocked(getDriveSyncStatus).mockImplementation(() => release.promise);
  const first = c.check(); await tick();
  let secondDone = false;
  const second = c.check().then(() => { secondDone = true; });
  await tick();
  expect(secondDone).toBe(false); expect(getDriveSyncStatus).toHaveBeenCalledOnce();
  release.resolve({ connected: true, job: null }); await Promise.all([first, second]);
  expect(secondDone).toBe(true); expect(c.getSnapshot().phase).toBe("idle");
});

it("KI-012 discovery: a status click during an in-progress submission waits for it, then reports the true state", async () => {
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  const accepted = deferred<{ job_id: string; status: "queued"; message: string }>();
  vi.mocked(syncDriveMetadata).mockImplementation(() => accepted.promise);
  const starting = c.start(); await tick(); await tick();
  expect(c.getSnapshot().phase).toBe("submitting");
  vi.mocked(getDriveSyncStatus).mockClear();
  let clicked = false;
  const click = c.check().then(() => { clicked = true; });
  await tick();
  expect(clicked).toBe(false);                                   // used to return instantly with nothing done
  expect(getDriveSyncStatus).not.toHaveBeenCalled();
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: { id: id(900), user_id: owner, status: "running", operation: "SYNC", recovery_required: false, processed: 0, total: 5, started_at: null, completed_at: null, error: null, created_at: "", updated_at: "" } });
  accepted.resolve({ job_id: id(900), status: "queued", message: "Accepted" });
  await Promise.all([starting, click]);
  expect(clicked).toBe(true);
  expect(syncDriveMetadata).toHaveBeenCalledOnce();               // the click never causes a second submission
  expect(c.getSnapshot().phase).toBe("active");
});

it("KI-012 discovery: many rapid clicks never submit anything and cause a single status read", async () => {
  const c = new DiscoveryController(owner, vi.fn());
  const release = deferred<{ connected: boolean; job: null }>();
  vi.mocked(getDriveSyncStatus).mockImplementation(() => release.promise);
  const clicks = Array.from({ length: 10 }, () => c.check()); await tick();
  release.resolve({ connected: true, job: null }); await Promise.all(clicks);
  expect(getDriveSyncStatus).toHaveBeenCalledOnce(); expect(syncDriveMetadata).not.toHaveBeenCalled();
});
