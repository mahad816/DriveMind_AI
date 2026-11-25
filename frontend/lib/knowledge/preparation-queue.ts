import { listDriveFiles } from "@/lib/api/files";
import { getDriveSyncStatus } from "@/lib/api/indexing";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import type { DriveFileRead } from "@/lib/api/types";
import { DEMO_MODE } from "@/lib/demo";
import {
  SingleFilePreparation, isDefiniteDocumentFailure, isDefiniteSkip, preparationEligibility, preparationFrame, type PreparationState,
} from "./single-file-preparation";
import { JoinedCheck } from "./joined-check";
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
/** Honest end-of-batch wording: "all ready" only when every document really is ready. */
function finishedMessage(queue: PreparationQueueRecord) {
  const ready = queue.entries.filter(e => e.result === "ready").length, unprepared = queue.entries.length - ready;
  return unprepared === 0 ? "All selected documents are confirmed ready for chat."
    : `${ready} ready, ${unprepared} could not be prepared. Ready documents are available for chat; your Drive was not changed.`;
}
/** Child progress describes one document and one job. It may be shown or trusted for a queue record only when it is
 *  for the current entry's file AND its job is exactly the entry's latest receipt (both null while nothing is known).
 *  A child computed against an older record (another tab submitted a newer stage, or moved the cursor) never matches. */
export function childBelongsTo(queue: PreparationQueueRecord | null, child: PreparationState | null): boolean {
  const entry = queue?.entries[queue.current];
  if (!entry || !child?.file || child.file.id !== entry.fileId) return false;
  return (child.job?.id ?? null) === (entry.receipts.at(-1)?.jobId ?? null);
}
/** A job counts as ended only with evidence: a terminal job that is exactly the entry's latest receipt. An unknown
 *  submission (no job id), a mismatched job or a missing job is never "ended". */
export function lastJobHasEnded(queue: PreparationQueueRecord | null, child: PreparationState | null): boolean {
  return childBelongsTo(queue, child) && !!child?.job && !!queue?.entries[queue.current]?.receipts.at(-1)?.jobId &&
    ["failed", "canceled", "completed"].includes(child.job.status);
}
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
  private gate = new JoinedCheck();
  private get busy() { return this.gate.busy; }
  private set busy(value: boolean) { this.gate.busy = value; }
  private child: SingleFilePreparation | null = null;
  private binding: string | null = null;
  private listeners = new Set<() => void>();
  private state: PreparationQueueState = { phase: "checking", queue: null, child: null, message: "Checking preparation queue…" };
  /** The newest queue record this controller has safely read from, or written to, this browser's storage. A blocked
   *  state publishes it (never an older published copy), so a queue whose history could not be verified (backend down,
   *  or the backend disagrees) can still be ended locally. It grants no permission to submit and is never written
   *  back: it is only the `expected` value of a compare-and-set. Cleared when the queue is closed or gone. */
  private lastRead: PreparationQueueRecord | null = null;
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
    // Show the record that is actually stored now. A tab that fell behind, or a submission whose acknowledgement was
    // lost, otherwise displays an older copy and the compare-and-set in finish() would refuse a dismissal that is safe.
    let known = this.lastRead ?? this.state.queue;
    if (known) {
      try { const gate = readPreparationGate(this.owner); known = gate.kind === "queue" ? gate.record : null; }
      catch { /* an unreadable record stays untouched and is not offered for deletion beyond what was safely read */ }
    }
    this.lastRead = known;
    // The child snapshot was computed against an earlier record. Keep it only if it still describes this record's
    // current document and job; otherwise show no child rather than another document's or another stage's progress.
    this.publish({ ...this.state, queue: known, child: childBelongsTo(known, this.state.child) ? this.state.child : null, phase: "blocked", message: "Queue status could not be verified. Check status; do not repeat uncertain work. Ask the beta owner for help if this persists." });
  }
  private bind(queue: PreparationQueueRecord) {
    const entry = queue.entries[queue.current];
    const binding = entry ? JSON.stringify([queue.batchId, queue.current, entry.runId, entry.fileId]) : null;
    if (binding !== this.binding) {
      this.child?.dispose(); this.child = null; this.binding = binding;
      if (entry) this.child = new SingleFilePreparation(this.owner, entry.fileId, queueChildStore(this.owner, queue));
    }
  }
  /** Historical receipts stay exact, but need not be the owner's latest job. Each earlier entry is checked
   *  against its own last receipt: a ready entry by its completed BUILD, a failed or skipped entry by the exact
   *  terminal job it was recorded with. Any disagreement with the backend pauses the queue. */
  private async verifyHistory(queue: PreparationQueueRecord) {
    const completed = queue.entries.slice(0, queue.current);
    if (!completed.length) return;
    const [inventory, ...results] = await Promise.all([
      listDriveFiles(AbortSignal.timeout(15_000)),
      ...completed.map(e => getDriveSyncStatus(e.receipts.at(-1)!.jobId!, AbortSignal.timeout(15_000))),
    ]);
    completed.forEach((entry, index) => {
      const result = results[index], job = result.job, receipt = entry.receipts.at(-1)!;
      const file = inventory.files.find(f => f.id === entry.fileId);
      const exact = result.demo_mode !== true && !!job && job.user_id === this.owner && job.id === receipt.jobId &&
        job.file_id === entry.fileId && job.operation === receipt.stage && !job.recovery_required && !!file && file.user_id === this.owner;
      const agrees = !exact ? false
        : entry.result === "ready" ? receipt.stage === "BUILD" && job.status === "completed" && job.total === 1 && job.processed === 1 &&
            job.succeeded === 1 && job.failed === 0 && job.skipped === 0 && file.status === "indexed" && preparationFrame(file) === entry.frame
        // The same exact evidence that allowed the cursor to move: never status alone, never counters alone.
        : entry.result === "failed" ? isDefiniteDocumentFailure(job) && file.status === "failed"
        : entry.result === "skipped" ? isDefiniteSkip(job, file)
        : false;
      if (!agrees) throw new Error("Historical result not confirmed");
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
      const queue: PreparationQueueRecord = { schemaVersion: 3, owner: this.owner, batchId: crypto.randomUUID(), entries, current: 0 };
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
  /** Overlapping callers join the check in flight instead of being dropped. */
  check = () => this.gate.join(() => this.runCheck());
  private runCheck = async () => {
    if (this.busy || !this.live()) return;
    this.busy = true;
    try {
      const gate = readPreparationGate(this.owner);
      if (gate.kind !== "queue") {
        this.child?.dispose(); this.child = null; this.binding = null; this.lastRead = null;
        this.publish({ phase: gate.kind === "legacy" ? "legacy" : "idle", queue: null, child: null,
          message: gate.kind === "legacy" ? "An existing single-document preparation must be reviewed through its original progress screen." : "No preparation queue is reserved." });
        return;
      }
      const queue = gate.record;
      this.lastRead = queue;
      this.bind(queue);
      await this.verifyHistory(queue);
      if (!this.live()) return;
      const unchanged = readPreparationGate(this.owner);
      if (unchanged.kind !== "queue" || !same(unchanged.record, queue)) throw new Error("Queue changed");
      if (queue.current === queue.entries.length) {
        this.publish({ phase: "complete", queue, child: null, message: finishedMessage(queue) });
        return;
      }
      await this.child!.check();
      if (!this.live()) return;
      const child = this.child!.getSnapshot(), current = readPreparationGate(this.owner);
      if (current.kind !== "queue" || current.record.batchId !== queue.batchId || current.record.current !== queue.current ||
          current.record.entries[queue.current].runId !== queue.entries[queue.current].runId) throw new Error("Queue changed");
      let saved = current.record;
      this.lastRead = saved;
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
        saved = next; this.lastRead = next; this.bind(next);
        this.publish({ phase: next.current === next.entries.length ? "complete" : "awaiting_next", queue: next, child: null,
          message: next.current === next.entries.length ? finishedMessage(next) : "Document ready. Explicitly confirm before preparing the next document." });
        return;
      }
      if (["failed", "skipped"].includes(child.phase)) {
        // A terminal file-specific outcome: the exact job, owner and file were verified by the child, and it carried
        // no recovery flag. Only a connected Drive makes it safe to move on; otherwise nothing is recorded and the
        // queue pauses, so the same check succeeds later (self-healing) without having changed any saved state.
        this.child!.pause();
        if (child.connected !== true) {
          this.publish({ queue: saved, child, phase: "blocked",
            message: "Google Drive is not connected, so preparation is paused. Reconnect Drive in Settings, then check status. Nothing was lost." });
          return;
        }
        if (!same(saved, queue)) return; // a check that changed saved state must be observed again before handoff
        // Record the result with its receipt and move the cursor in ONE compare-and-set write (a v2 record that
        // stopped here is upgraded by the same write). Another tab that already advanced makes this write lose.
        const outcome = child.phase as "failed" | "skipped";
        const next: PreparationQueueRecord = {
          ...saved, schemaVersion: 3, current: saved.current + 1,
          entries: saved.entries.map((v, i) => i === saved.current ? { ...v, result: outcome } : v),
        };
        if (!await replaceQueue(this.owner, saved, next, () => this.live())) throw new Error("Result changed");
        this.lastRead = next; this.bind(next);
        const finished = next.current === next.entries.length;
        this.publish({ phase: finished ? "complete" : "awaiting_next", queue: next, child: null,
          message: finished ? finishedMessage(next) : "That document could not be prepared. Your other documents can still be prepared. Explicitly confirm before the next one starts." });
        return;
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
  /** End a finished queue, one waiting between documents, or any paused one (locally). Never while a stage is observed running. */
  finish = async (expected?: PreparationQueueRecord): Promise<boolean> => {
    if (expected && !same(this.state.queue, expected)) return false;
    const reviewed = this.state.queue;
    this.pause();
    if (this.busy || !this.live() || !reviewed) return false;
    // A paused queue is ended locally, with no request: it must work with Drive disconnected or the backend down.
    // Ending removes only this browser's queue record. It submits nothing, deletes no backend history and does not
    // cancel a server job that may already be running.
    const alreadyPaused = ["blocked", "stopped"].includes(this.state.phase);
    if (!alreadyPaused) await this.check();
    const queue = this.state.queue;
    // Also endable: waiting between documents (or not started) with nothing submitted for the current one. Closing
    // then drops only documents that never started; an in-flight, unknown or recovery-blocked queue is never closable.
    const idle = !!queue && ["review", "awaiting_next"].includes(this.state.phase) && queue.current < queue.entries.length &&
      queue.entries[queue.current].receipts.length === 0;
    const paused = ["blocked", "stopped"].includes(this.state.phase);
    if (!this.live() || !same(reviewed, queue) || !(this.state.phase === "complete" || idle || paused)) return false;
    this.busy = true;
    try {
      const closed = await replaceQueue(this.owner, reviewed, null, () => this.live());
      if (closed) {
        this.child?.dispose(); this.child = null; this.binding = null; this.lastRead = null;
        // Say only what is known: a job observed as ended is not "still running"; an unobserved one might be.
        const ended = lastJobHasEnded(reviewed, this.state.child);
        const sent = reviewed.entries.some(e => e.receipts.length > 0 && e.result === "pending");
        this.publish({ phase: "idle", queue: null, child: null, message: !paused ? "Preparation queue closed. Prepared documents remain available."
          : !sent ? "Preparation ended on this screen. Nothing was sent for the remaining documents. The Files page shows the current state of each document."
          : ended ? "Preparation ended on this screen. The last server job had already ended, so nothing was left running. The Files page shows the current state of each document."
          : "Preparation ended on this screen. A job already sent to the server was not cancelled and may still finish. The Files page shows the current state of each document." });
      }
      return closed;
    } catch { this.blocked(); return false; }
    finally { this.busy = false; }
  };
}
