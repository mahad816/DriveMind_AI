import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { DiscoveryController } from "./discovery";
import { getDriveSyncStatus, syncDriveMetadata } from "@/lib/api/indexing";
import { setSessionOwner, invalidateSessionRequests } from "@/lib/api/session-events";
import type { IndexingJobRead } from "@/lib/api/types";
vi.mock("@/lib/api/indexing", async original => ({ ...await original<typeof import("@/lib/api/indexing")>(), getDriveSyncStatus: vi.fn(), syncDriveMetadata: vi.fn() }));
const owner = "00000000-0000-0000-0000-000000000065";
const id = "00000000-0000-0000-0000-000000000123";
const key = `drivemind:discovery:v1:${owner}`;
const job = (status: IndexingJobRead["status"], extra = {}): IndexingJobRead => ({ id, user_id: owner, status, operation: "SYNC", recovery_required: false, processed: 7, total: 7, started_at: null, completed_at: null, error: null, created_at: "", updated_at: "", ...extra });
let values: Map<string, string>;
beforeEach(() => {
  Object.defineProperty(navigator, "locks", { configurable: true, value: {
    request: async (_name: string, callback: () => unknown) => callback(),
  } });
  vi.clearAllMocks(); setSessionOwner(owner); values = new Map();
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) } });
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: null });
  vi.mocked(syncDriveMetadata).mockResolvedValue({ job_id: id, status: "queued", message: "Accepted" });
});
afterEach(() => setSessionOwner(null));
it("only submits explicit metadata SYNC, once, and follows the exact accepted job", async () => {
  const done = vi.fn(), c = new DiscoveryController(owner, done);
  await c.check();
  vi.mocked(getDriveSyncStatus).mockResolvedValueOnce({ connected: true, job: null }).mockResolvedValue({ connected: true, job: job("running") });
  await c.start(); await c.start();
  expect(syncDriveMetadata).toHaveBeenCalledExactlyOnceWith(false, expect.any(AbortSignal), expect.any(Function));
  expect(getDriveSyncStatus).toHaveBeenLastCalledWith(id, expect.any(AbortSignal));
  expect(JSON.parse(values.get(key)!)).toMatchObject({ jobId: id, submissionId: expect.any(String), revision: expect.any(Number) });
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: job("completed") });
  await c.check(); await c.check();
  expect(c.getSnapshot().message).toContain("7 metadata updates"); expect(done).toHaveBeenCalledOnce();
});
it("observes an existing active sync after navigation without mutation", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: job("running") });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(c.getSnapshot().phase).toBe("active"); expect(syncDriveMetadata).not.toHaveBeenCalled();
  const next = new DiscoveryController(owner, vi.fn()); await next.check();
  expect(getDriveSyncStatus).toHaveBeenLastCalledWith(id, expect.any(AbortSignal));
});
it("lost acceptance stays uncertain across reload even if latest job completed", async () => {
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  vi.mocked(syncDriveMetadata).mockRejectedValue(new Error("timeout")); await c.start();
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: job("completed") });
  const next = new DiscoveryController(owner, vi.fn()); await next.check(); await next.start();
  expect(next.getSnapshot().phase).toBe("unknown"); expect(syncDriveMetadata).toHaveBeenCalledOnce();
});
it("blocks recovery-required and non-sync active work", async () => {
  for (const current of [job("failed", { recovery_required: true }), job("running", { operation: "BUILD" })]) {
    const c = new DiscoveryController(owner, vi.fn());
    vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: current });
    await c.check(); await c.start(); expect(syncDriveMetadata).not.toHaveBeenCalled();
  }
});
it("does not submit for disconnected Drive or unavailable status", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: false, job: null });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start(); expect(syncDriveMetadata).not.toHaveBeenCalled();
  vi.mocked(getDriveSyncStatus).mockRejectedValue(new Error("offline")); await c.check(); expect(c.getSnapshot().phase).toBe("unknown");
});
it("storage failure prevents a mutation", async () => {
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  window.localStorage.setItem = () => { throw new Error("denied"); };
  await c.start(); expect(syncDriveMetadata).not.toHaveBeenCalled();
});
it("fences late responses and future actions on account or session changes", async () => {
  let finish!: (v: { connected: boolean; job: null }) => void;
  vi.mocked(getDriveSyncStatus).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const c = new DiscoveryController(owner, vi.fn()); const pending = c.check();
  setSessionOwner("other"); invalidateSessionRequests(); finish({ connected: true, job: null }); await pending; await c.start();
  expect(c.getSnapshot().phase).toBe("checking"); expect(syncDriveMetadata).not.toHaveBeenCalled();
});
it("rejects an exact-job mismatch without clearing its record or retrying", async () => {
  values.set(key, JSON.stringify({ jobId: id }));
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: job("completed", { id: "different" }) });
  const c = new DiscoveryController(owner, vi.fn()); await c.check(); await c.start();
  expect(c.getSnapshot().phase).toBe("unknown"); expect(values.has(key)).toBe(true); expect(syncDriveMetadata).not.toHaveBeenCalled();
});
it("does not adopt a different owner's browser discovery record", async () => {
  values.set(`drivemind:discovery:v1:other`, JSON.stringify({ jobId: id }));
  const c = new DiscoveryController(owner, vi.fn()); await c.check();
  expect(getDriveSyncStatus).toHaveBeenCalledWith(undefined, expect.any(AbortSignal)); expect(c.getSnapshot().phase).toBe("idle");
});
