import { getDriveSyncStatus, syncDriveMetadata, SyncSubmissionError, type SyncRejection } from "@/lib/api/indexing";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import type { IndexingJobRead } from "@/lib/api/types";
import { preparationKey } from "./single-file-preparation";
import { readPreparationGate } from "./preparation-queue-store";
import { JoinedCheck } from "./joined-check";

type Intent = { jobId: string | null; submissionId?: string; revision?: number };
export type DiscoveryState = {
  phase: "checking" | "idle" | "submitting" | "active" | "complete" | "unavailable" | "blocked" | "unknown";
  job: IndexingJobRead | null;
  message: string;
  connected: boolean;
  /** Backend report that the sync executor accepts jobs; null when not (yet) reported. */
  syncAvailable: boolean | null;
};
const initial: DiscoveryState = { phase: "checking", job: null, message: "Checking Drive discovery…", connected: false, syncAvailable: null };
/** Phases from which a new request may be made. "unavailable" is a known refusal, safe to retry. */
export const STARTABLE_PHASES: readonly DiscoveryState["phase"][] = ["idle", "complete", "unavailable"];
const rejectionMessages: Partial<Record<SyncRejection, { phase: DiscoveryState["phase"]; message: string }>> = {
  unavailable: { phase: "unavailable", message: "Sync is temporarily unavailable. Please try again." },
  not_connected: { phase: "idle", message: "Your Google Drive connection needs to be renewed." },
  session: { phase: "blocked", message: "Your session expired. Sign in again, then retry the sync." },
};
/** Why discovery was refused locally, before any backend call. Each reason has its own message. */
export type DiscoveryBlockReason = "preparation_unfinished" | "preparation_unreadable" | "pending_elsewhere" | "coordination_unavailable";
export class DiscoveryBlockedError extends Error {
  constructor(readonly reason: DiscoveryBlockReason) { super(reason); }
}
const blockMessages: Record<DiscoveryBlockReason, string> = {
  preparation_unfinished: "The Drive check was not started because document preparation is unfinished. Finish or close it on the Preparation screen, then check Drive again.",
  preparation_unreadable: "The Drive check was not started because the saved preparation record could not be read. Review it on the Preparation screen or ask the beta owner for help.",
  pending_elsewhere: "A Drive check is already pending in this browser. Check its status instead of starting another.",
  coordination_unavailable: "The Drive check was not started because this browser cannot safely coordinate tabs. Nothing was sent to Drive.",
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Owns metadata discovery only. Unknown acceptance is never replayed. */
export class DiscoveryController {
  private state = initial;
  private listeners = new Set<() => void>();
  private gate = new JoinedCheck();
  private get busy() { return this.gate.busy; }
  private set busy(value: boolean) { this.gate.busy = value; }
  private disposed = false;
  private notified: string | null = null;
  private revision = sessionRevision();
  constructor(private owner: string, private onComplete: () => void) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private live = () => !this.disposed && sessionOwner() === this.owner && sessionRevision() === this.revision;
  private key = () => `drivemind:discovery:v1:${this.owner}`;
  private read(): Intent | null {
    const raw = window.localStorage.getItem(this.key());
    if (raw === null) return null;
    const value = JSON.parse(raw) as Intent;
    if (!value || !(value.jobId === null || (typeof value.jobId === "string" && uuid.test(value.jobId)))) {
      throw new Error("Invalid discovery record");
    }
    return value;
  }
  /** Atomic matching-intent update across cooperating tabs. Never hold over network I/O. */
  private async replace(expected: Intent | null, next: Intent | null): Promise<boolean> {
    if (!navigator.locks) throw new DiscoveryBlockedError("coordination_unavailable");
    return navigator.locks.request(this.key(), () => {
      if (JSON.stringify(this.read()) !== JSON.stringify(expected)) return false;
      // Preparation shares this short owner lock. Never slip a SYNC between its stages.
      if (expected === null && next) this.clearFinishedPreparation();
      if (next) window.localStorage.setItem(this.key(), JSON.stringify(next));
      else window.localStorage.removeItem(this.key());
      return true;
    });
  }
  /**
   * Only truly conflicting preparation blocks discovery. A queue whose every document is
   * confirmed ready (cursor past the last entry; the store validates that) has no work left,
   * so it is cleared here, exactly as the user's "Close completed preparation" would. Leaving
   * it would risk an unclosable record if a later sync changes a prepared file. Anything
   * pending, failed, skipped, legacy or unreadable keeps blocking. Runs inside the owner lock.
   */
  private clearFinishedPreparation() {
    let gate;
    try { gate = readPreparationGate(this.owner); }
    catch { throw new DiscoveryBlockedError("preparation_unreadable"); }
    if (gate.kind === "empty") return;
    if (gate.kind === "queue" && gate.record.current === gate.record.entries.length) {
      window.localStorage.removeItem(preparationKey(this.owner));
      return;
    }
    throw new DiscoveryBlockedError("preparation_unfinished");
  }
  private publish(value: DiscoveryState) {
    if (this.live()) { this.state = value; this.listeners.forEach(listener => listener()); }
  }
  connect = () => { this.disposed = false; };
  dispose = () => { this.disposed = true; };
  /** Overlapping callers join the check in flight instead of being dropped. */
  check = () => this.gate.join(() => this.runCheck());
  private runCheck = async () => {
    if (this.busy || !this.live()) return;
    this.busy = true;
    try {
      const intent = this.read();
      const result = await getDriveSyncStatus(intent?.jobId ?? undefined, AbortSignal.timeout(15_000));
      if (!this.live()) return;
      if (result.demo_mode === true || typeof result.connected !== "boolean") throw new Error("Discovery mode mismatch");
      const job = result.job;
      const syncAvailable = typeof result.sync_available === "boolean" ? result.sync_available : null;
      if (job && job.user_id !== this.owner) throw new Error("Discovery owner mismatch");
      if (intent?.jobId && (!job || job.id !== intent.jobId || job.operation !== "SYNC")) throw new Error("Discovery identity mismatch");
      if (JSON.stringify(this.read()) !== JSON.stringify(intent)) throw new Error("Discovery intent changed");
      if (job?.recovery_required) {
        this.publish({ phase: "blocked", job, connected: result.connected, syncAvailable, message: "Existing work needs review before discovery can continue. Ask the beta owner for help." });
      } else if (intent && !intent.jobId) {
        // Latest-job evidence can describe activity, but cannot correlate a lost receipt.
        this.publish({ phase: "unknown", job, connected: result.connected, syncAvailable, message: "The discovery request could not be confirmed. Check status again; do not start another request. If this persists, ask the beta owner to review it." });
      } else if (job && ["queued", "running"].includes(job.status)) {
        if (!intent && job.operation === "SYNC") {
          const adopted = { jobId: job.id, submissionId: crypto.randomUUID(), revision: this.revision };
          if (!await this.replace(null, adopted)) throw new Error("Discovery intent changed");
        }
        this.publish({ phase: "active", job, connected: result.connected, syncAvailable, message: job.operation === "SYNC" ? `Drive discovery ${job.status === "queued" ? "queued" : "in progress"}.` : "Document preparation is active. Discovery will be available when it finishes." });
      } else {
        if (intent && !await this.replace(intent, null)) throw new Error("Discovery intent changed");
        const completed = job?.operation === "SYNC" && job.status === "completed";
        this.publish({ phase: completed ? "complete" : "idle", job, connected: result.connected, syncAvailable, message: completed ? `Drive check completed. ${job.processed ?? 0} metadata updates processed.` : job?.operation === "SYNC" && job.status === "failed" ? "The Drive check failed. No documents were prepared. You can start a new check after reviewing your connection." : "Discover supported documents without preparing their content." });
        if (this.live() && completed && this.notified !== job.id) { this.notified = job.id; this.onComplete(); }
      }
    } catch (error) {
      const preparation = error instanceof DiscoveryBlockedError && error.reason.startsWith("preparation_");
      this.publish({ ...this.state, phase: "unknown", message: preparation
        ? "Drive discovery is running, but unfinished or unreadable document preparation prevents tracking it here. Resolve it on the Preparation screen, then check status."
        : "Discovery status is unavailable. Check status before starting another request." });
    } finally { this.busy = false; }
  };
  start = async () => {
    if (this.busy || !this.live() || !STARTABLE_PHASES.includes(this.state.phase) || !this.state.connected) return;
    await this.check();
    if (!this.live() || this.busy || !STARTABLE_PHASES.includes(this.state.phase) || !this.state.connected) return;
    // The backend reports the executor closed: say so instead of sending a request that must fail.
    if (this.state.syncAvailable === false) {
      this.publish({ ...this.state, ...rejectionMessages.unavailable! });
      return;
    }
    this.busy = true;
    // Immutable request scope. Receipt bookkeeping deliberately outlives the UI.
    const intent: Intent = { jobId: null, submissionId: crypto.randomUUID(), revision: this.revision };
    let apiCalled = false;
    let acceptedId: string | null = null;
    try {
      if (!await this.replace(null, intent)) throw new DiscoveryBlockedError("pending_elsewhere");
      if (!this.live()) throw new SyncSubmissionError("not_submitted");
      this.publish({ ...this.state, phase: "submitting", message: "Requesting a Drive metadata check…" });
      apiCalled = true;
      const accepted = await syncDriveMetadata(false, AbortSignal.timeout(15_000), async receipt => {
        // No live()/session lookup here: only this captured owner's matching intent.
        // apiFetch still prevents this response from entering an obsolete private UI.
        if (receipt.outcome === "accepted") {
          if (!await this.replace(intent, { ...intent, jobId: receipt.jobId })) {
            throw new Error("Discovery intent changed before receipt persistence");
          }
          acceptedId = receipt.jobId;
        } else {
          await this.replace(intent, null);
        }
      });
      if (accepted.status !== "queued" || !uuid.test(accepted.job_id)) throw new Error("Invalid acceptance");
      // Also supports callers/transports which return the receipt directly.
      if (!acceptedId && !await this.replace(intent, { ...intent, jobId: accepted.job_id })) {
        throw new Error("Discovery intent changed before receipt persistence");
      }
      this.publish({ ...this.state, phase: "active", message: "Drive discovery queued." });
    } catch (error) {
      if (!apiCalled || (error instanceof SyncSubmissionError && error.outcome !== "unknown")) {
        try { await this.replace(intent, null); } catch { /* Preserve any record if safe cleanup fails. */ }
        const known = error instanceof SyncSubmissionError && error.reason ? rejectionMessages[error.reason] : undefined;
        if (known) {
          this.publish({ ...this.state, ...known, ...(error instanceof SyncSubmissionError && error.reason === "not_connected" ? { connected: false } : {}) });
          return;
        }
        // Name the real cause: a local refusal never reached the backend, so it is not a connection problem.
        const message = error instanceof DiscoveryBlockedError ? blockMessages[error.reason] : apiCalled
          ? "The Drive check was not accepted. Verify your connection and check discovery status before explicitly trying again."
          : "The Drive check was not started because browser storage or coordination is unavailable. Nothing was sent to Drive.";
        this.publish({ ...this.state, phase: "blocked", message });
      } else if (acceptedId) {
        this.publish({ ...this.state, phase: "active", message: "Drive discovery accepted. Check its status." });
      } else {
        this.publish({ ...this.state, phase: "unknown", message: "The discovery request could not be confirmed. Check status; do not submit it again." });
      }
    } finally { this.busy = false; }
    if (this.live() && this.state.phase === "active") await this.check();
  };
}
