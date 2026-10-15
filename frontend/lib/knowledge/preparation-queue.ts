import { listDriveFiles } from "@/lib/api/files";
import { getDriveSyncStatus } from "@/lib/api/indexing";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import type { DriveFileRead } from "@/lib/api/types";
import { DEMO_MODE } from "@/lib/demo";
import {
  SingleFilePreparation, preparationEligibility, preparationFrame, type PreparationState,
} from "./single-file-preparation";
import {
  readPreparationGate, replaceQueue, queueChildStore,
  type PreparationQueueRecord,
} from "./preparation-queue-store";

export type PreparationQueueState = {
  phase: "checking" | "idle" | "legacy" | "review" | "awaiting_next" | "progress" | "complete" | "stopped" | "blocked";
  queue: PreparationQueueRecord | null;
  child: PreparationState | null;
  message: string;
};
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
export type QueueConfirmation = { batchId: string; current: number; runId: string; fileId: string };
export function queueConfirmation(queue: PreparationQueueRecord): QueueConfirmation | undefined {
  const entry = queue.entries[queue.current];
  return entry ? { batchId: queue.batchId, current: queue.current, runId: entry.runId, fileId: entry.fileId } : undefined;
}

/** Sequential queue; automatic stage permission never crosses documents. */
export class PreparationQueue {
  private revision = sessionRevision();
  private generation = 0;
  private disposed = false;
  private busy = false;
  private child: SingleFilePreparation | null = null;
  private binding: string | null = null;
  private listeners = new Set<() => void>();
  private state: PreparationQueueState = { phase: "checking", queue: null, child: null, message: "Checking preparation queue…" };
  constructor(private owner: string) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  pause = () => { this.generation += 1; this.child?.pause(); };
  dispose = () => { this.disposed = true; this.pause(); };
  // React Strict Mode may reconnect observation; it never revives permission.
  connect = () => { this.disposed = false; };
  private live = () => !DEMO_MODE && !this.disposed && sessionOwner() === this.owner && sessionRevision() === this.revision;
  private publish(value: PreparationQueueState) {
    if (this.live()) { this.state = value; this.listeners.forEach(listener => listener()); }
  }
  private blocked() {
    this.pause();
    this.publish({ ...this.state, phase: "blocked", message: "Queue status could not be verified. Check status; do not repeat uncertain work. Ask the beta owner for help if this persists." });
  }
  private bind(queue: PreparationQueueRecord) {
    const entry = queue.entries[queue.current];
    const binding = entry ? JSON.stringify([queue.batchId, queue.current, entry.runId, entry.fileId]) : null;
    if (binding !== this.binding) {
      this.child?.dispose(); this.child = null; this.binding = binding;
      if (entry) this.child = new SingleFilePreparation(this.owner, entry.fileId, queueChildStore(this.owner, queue));
    }
  }
  /** Historical BUILD receipts stay exact, but need not be the owner's latest job. */
  private async verifyHistory(queue: PreparationQueueRecord) {
    const completed = queue.entries.slice(0, queue.current);
    if (!completed.length) return;
    const [inventory, ...results] = await Promise.all([
      listDriveFiles(AbortSignal.timeout(15_000)),
      ...completed.map(e => getDriveSyncStatus(e.receipts[2].jobId!, AbortSignal.timeout(15_000))),
    ]);
    completed.forEach((entry, index) => {
      const result = results[index], job = result.job;
      const file = inventory.files.find(f => f.id === entry.fileId);
      if (result.demo_mode === true || !job || job.user_id !== this.owner || job.id !== entry.receipts[2].jobId ||
          job.file_id !== entry.fileId || job.operation !== "BUILD" || job.status !== "completed" || job.recovery_required ||
          job.total !== 1 || job.processed !== 1 || job.succeeded !== 1 || job.failed !== 0 || job.skipped !== 0 ||
          !file || file.user_id !== this.owner || file.status !== "indexed" || preparationFrame(file) !== entry.frame) {
        throw new Error("Historical result not confirmed");
      }
    });
  }
  /** Reserve reviewed metadata only. This never submits a content-processing request. */
  reserve = async (reviewed: readonly DriveFileRead[], startFirst = false): Promise<boolean> => {
    if (this.busy || !this.live()) return false;
    const generation = this.generation;
    // Capture only the reviewed IDs/frames before any await; caller objects are not authority.
    const selection = reviewed.map(f => ({ fileId: f.id, frame: preparationFrame(f) }));
    this.busy = true;
    let reserved = false;
    let confirmed: QueueConfirmation | undefined;
    try {
      if (selection.length < 1 || selection.length > 5 || new Set(selection.map(f => f.fileId)).size !== selection.length) throw new Error("Invalid selection");
      const [inventory, latest] = await Promise.all([
        listDriveFiles(AbortSignal.timeout(15_000)), getDriveSyncStatus(undefined, AbortSignal.timeout(15_000)),
      ]);
      if (!this.live() || generation !== this.generation) return false;
      if (latest.demo_mode === true || latest.connected !== true ||
          (latest.job && (latest.job.user_id !== this.owner || latest.job.recovery_required || ["queued", "running"].includes(latest.job.status)))) throw new Error("Owner work blocked");
      const entries = selection.map(selected => {
        const file = inventory.files.find(f => f.id === selected.fileId);
        if (!file || file.user_id !== this.owner || preparationEligibility(file) || preparationFrame(file) !== selected.frame) throw new Error("Selection changed");
        return { ...selected, runId: crypto.randomUUID(), receipts: [], result: "pending" as const };
      });
      const queue: PreparationQueueRecord = { schemaVersion: 2, owner: this.owner, batchId: crypto.randomUUID(), entries, current: 0 };
      confirmed = queueConfirmation(queue);
      reserved = await replaceQueue(this.owner, null, queue, () => this.live() && generation === this.generation);
      if (!reserved) throw new Error("Preparation gate occupied");
    } catch { this.blocked(); }
    finally { this.busy = false; }
    if (reserved && this.live()) {
      await this.check();
      // Only the original deliberate reservation action can start its exact first
      // child. A pause, replacement or stale callback cannot authorize another run.
      if (startFirst && generation === this.generation && confirmed) await this.confirm(confirmed);
    }
    return reserved;
  };
  check = async () => {
    if (this.busy || !this.live()) return;
    this.busy = true;
    try {
      const gate = readPreparationGate(this.owner);
      if (gate.kind !== "queue") {
        this.child?.dispose(); this.child = null; this.binding = null;
        this.publish({ phase: gate.kind === "legacy" ? "legacy" : "idle", queue: null, child: null,
          message: gate.kind === "legacy" ? "An existing single-document preparation must be reviewed through its original progress screen." : "No preparation queue is reserved." });
        return;
      }
      const queue = gate.record;
      this.bind(queue);
      await this.verifyHistory(queue);
      if (!this.live()) return;
      const unchanged = readPreparationGate(this.owner);
      if (unchanged.kind !== "queue" || !same(unchanged.record, queue)) throw new Error("Queue changed");
      if (queue.current === queue.entries.length) {
        this.publish({ phase: "complete", queue, child: null, message: "All selected documents are confirmed ready for chat." });
        return;
      }
      await this.child!.check();
      if (!this.live()) return;
      const child = this.child!.getSnapshot(), current = readPreparationGate(this.owner);
      if (current.kind !== "queue" || current.record.batchId !== queue.batchId || current.record.current !== queue.current ||
          current.record.entries[queue.current].runId !== queue.entries[queue.current].runId) throw new Error("Queue changed");
      let saved = current.record;
      const entry = saved.entries[saved.current];
      if (child.phase === "ready" && entry.result === "pending") {
        // A check that also submitted a stage must be observed again before handoff.
        if (!same(saved, queue)) return;
        this.child!.pause();
        const next: PreparationQueueRecord = {
          ...saved, current: saved.current + 1,
          entries: saved.entries.map((v, i) => i === saved.current ? { ...v, result: "ready" } : v),
        };
        if (!await replaceQueue(this.owner, saved, next, () => this.live())) throw new Error("Handoff changed");
        saved = next; this.bind(next);
        this.publish({ phase: next.current === next.entries.length ? "complete" : "awaiting_next", queue: next, child: null,
          message: next.current === next.entries.length ? "All selected documents are confirmed ready for chat." : "Document ready. Explicitly confirm before preparing the next document." });
        return;
      }
      if (["failed", "skipped"].includes(child.phase) && entry.result === "pending") {
        const next: PreparationQueueRecord = { ...saved, entries: saved.entries.map((v, i) => i === saved.current ? { ...v, result: child.phase as "failed" | "skipped" } : v) };
        if (!await replaceQueue(this.owner, saved, next, () => this.live())) throw new Error("Result changed");
        saved = next;
      }
      const stopped = ["failed", "skipped"].includes(saved.entries[saved.current].result);
      if (stopped || ["unknown", "blocked", "ineligible"].includes(child.phase)) this.child!.pause();
      this.publish({ queue: saved, child,
        phase: stopped ? "stopped" : ["unknown", "blocked", "ineligible"].includes(child.phase) ? "blocked" :
          child.phase === "review" ? (saved.current === 0 ? "review" : "awaiting_next") : "progress",
        message: child.message });
    } catch { this.blocked(); }
    finally { this.busy = false; }
  };
  /** Explicit action for this exact batch/child. Permission never crosses a cursor. */
  confirm = async (expected?: QueueConfirmation) => {
    if (this.busy || !this.live() || !this.state.queue || !["review", "awaiting_next", "progress"].includes(this.state.phase)) return;
    if (expected && !same(queueConfirmation(this.state.queue), expected)) return;
    const reviewed = this.state.queue, generation = this.generation;
    await this.check();
    if (!this.live() || generation !== this.generation || !same(this.state.queue, reviewed) ||
        !["review", "awaiting_next", "progress"].includes(this.state.phase) ||
        !this.child || !["review", "continue"].includes(this.child.getSnapshot().phase)) return;
    this.busy = true;
    try { await this.child.confirm(); }
    finally { this.busy = false; }
    if (this.live()) await this.check();
  };
  /** Close only an all-ready or known failed/skipped queue, never uncertain work. */
  finish = async (expected?: PreparationQueueRecord): Promise<boolean> => {
    if (expected && !same(this.state.queue, expected)) return false;
    const reviewed = this.state.queue;
    this.pause();
    if (this.busy || !this.live() || !reviewed) return false;
    await this.check();
    if (!this.live() || !same(reviewed, this.state.queue) ||
        !(this.state.phase === "complete" || (this.state.phase === "stopped" && this.state.child?.canRelease))) return false;
    this.busy = true;
    try {
      const closed = await replaceQueue(this.owner, reviewed, null, () => this.live());
      if (closed) {
        this.child?.dispose(); this.child = null; this.binding = null;
        this.publish({ phase: "idle", queue: null, child: null, message: "Preparation queue closed. Prepared documents remain available." });
      }
      return closed;
    } catch { this.blocked(); return false; }
    finally { this.busy = false; }
  };
}
