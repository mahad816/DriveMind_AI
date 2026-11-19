/**
 * Executable registry of KNOWN, UNFIXED browser-side defects (see docs/KNOWN_ISSUES.md).
 *
 * Pattern per issue:
 *  - a normal test that pins today's behaviour, proving the scenario is set up correctly;
 *  - an `it.fails` test that states the CORRECT behaviour. It passes while the bug exists
 *    and turns RED the moment a fix lands, so whoever fixes it must change `it.fails` to
 *    `it` and update the registry. Nothing rots.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
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

const receipts = (jobs: (number | null)[]) =>
  (["INGEST", "CHUNK", "BUILD"] as const).slice(0, jobs.length).map((stage, i) => ({ stage, submissionId: id(500 + i), jobId: jobs[i] === null ? null : id(jobs[i]!) }));
const entry = (n: number, result: "pending" | "ready", jobs: (number | null)[]) => ({ fileId: id(n), runId: id(n + 50), frame: "frame", receipts: receipts(jobs), result });
const seedPreparation = (record: unknown) => values.set(preparationKey(owner), JSON.stringify(record));
const queueRecord = (current: number, entries: ReturnType<typeof entry>[]) => ({ schemaVersion: 2, owner, batchId: id(200), current, entries });

beforeEach(() => {
  vi.clearAllMocks(); setSessionOwner(owner); values = new Map();
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_n: string, cb: () => unknown) => cb() } });
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) } });
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: null });
  vi.mocked(syncDriveMetadata).mockResolvedValue({ job_id: id(900), status: "queued", message: "Accepted" });
});
afterEach(() => setSessionOwner(null));

// --- KI-012: "Check status" can be silently dropped ----------------------------------------

function slowHistoryQueue() {
  // Two documents: the first is ready (history needs a network re-check), the second pending.
  seedPreparation(queueRecord(1, [entry(1, "ready", [11, 12, 13]), entry(2, "pending", [])]));
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  vi.mocked(listDriveFiles).mockImplementation(async () => { await gate; return { files: [], total: 0 }; });
  return { queue: new PreparationQueue(owner), release };
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

it("KI-012 (today): a second check() during an in-flight check returns immediately", async () => {
  const { queue, release } = slowHistoryQueue();
  const first = queue.check(); await tick();
  let secondDone = false;
  await queue.check().then(() => { secondDone = true; });
  expect(secondDone).toBe(true); // Dropped: no new check happened and nothing waited.
  expect(listDriveFiles).toHaveBeenCalledOnce();
  release(); await first;
});
it.fails("KI-012 (correct): a Check status click mid-check waits for, or joins, the real check", async () => {
  const { queue, release } = slowHistoryQueue();
  const first = queue.check(); await tick();
  let secondDone = false;
  const second = queue.check().then(() => { secondDone = true; });
  await tick();
  expect(secondDone).toBe(false); // Must not claim completion while the real check still runs.
  release(); await Promise.all([first, second]);
});
