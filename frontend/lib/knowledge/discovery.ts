import { getDriveSyncStatus, syncDriveMetadata, SyncSubmissionError } from "@/lib/api/indexing";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import type { IndexingJobRead } from "@/lib/api/types";

type Intent = { jobId: string | null; submissionId?: string; revision?: number };
export type DiscoveryState = {
  phase: "checking" | "idle" | "submitting" | "active" | "complete" | "blocked" | "unknown";
  job: IndexingJobRead | null;
  message: string;
  connected: boolean;
};
const initial: DiscoveryState = { phase: "checking", job: null, message: "Checking Drive discovery…", connected: false };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Owns metadata discovery only. Unknown acceptance is never replayed. */
export class DiscoveryController {
  private state = initial;
  private listeners = new Set<() => void>();
  private busy = false;
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
    if (!navigator.locks) throw new Error("Safe discovery coordination is unavailable");
    return navigator.locks.request(this.key(), () => {
      if (JSON.stringify(this.read()) !== JSON.stringify(expected)) return false;
      // Preparation shares this short owner lock. Never slip a SYNC between its stages.
      if (expected === null && next && window.localStorage.getItem(`drivemind:preparation:v1:${this.owner}`) !== null) {
        throw new Error("A preparation workflow needs attention");
      }
      if (next) window.localStorage.setItem(this.key(), JSON.stringify(next));
      else window.localStorage.removeItem(this.key());
      return true;
    });
  }
  private publish(value: DiscoveryState) {
    if (this.live()) { this.state = value; this.listeners.forEach(listener => listener()); }
  }
  connect = () => { this.disposed = false; };
  dispose = () => { this.disposed = true; };
  check = async () => {
    if (this.busy || !this.live()) return;
    this.busy = true;
    try {
      const intent = this.read();
      const result = await getDriveSyncStatus(intent?.jobId ?? undefined, AbortSignal.timeout(15_000));
      if (!this.live()) return;
      if (result.demo_mode === true || typeof result.connected !== "boolean") throw new Error("Discovery mode mismatch");
      const job = result.job;
      if (job && job.user_id !== this.owner) throw new Error("Discovery owner mismatch");
      if (intent?.jobId && (!job || job.id !== intent.jobId || job.operation !== "SYNC")) throw new Error("Discovery identity mismatch");
      if (JSON.stringify(this.read()) !== JSON.stringify(intent)) throw new Error("Discovery intent changed");
      if (job?.recovery_required) {
        this.publish({ phase: "blocked", job, connected: result.connected, message: "Existing work needs review before discovery can continue. Ask the beta owner for help." });
      } else if (intent && !intent.jobId) {
        // Latest-job evidence can describe activity, but cannot correlate a lost receipt.
        this.publish({ phase: "unknown", job, connected: result.connected, message: "The discovery request could not be confirmed. Check status again; do not start another request. If this persists, ask the beta owner to review it." });
      } else if (job && ["queued", "running"].includes(job.status)) {
        if (!intent && job.operation === "SYNC") {
          const adopted = { jobId: job.id, submissionId: crypto.randomUUID(), revision: this.revision };
          if (!await this.replace(null, adopted)) throw new Error("Discovery intent changed");
        }
        this.publish({ phase: "active", job, connected: result.connected, message: job.operation === "SYNC" ? `Drive discovery ${job.status === "queued" ? "queued" : "in progress"}.` : "Document preparation is active. Discovery will be available when it finishes." });
      } else {
        if (intent && !await this.replace(intent, null)) throw new Error("Discovery intent changed");
        const completed = job?.operation === "SYNC" && job.status === "completed";
        this.publish({ phase: completed ? "complete" : "idle", job, connected: result.connected, message: completed ? `Drive check completed. ${job.processed ?? 0} metadata updates processed.` : job?.operation === "SYNC" && job.status === "failed" ? "The Drive check failed. No documents were prepared. You can start a new check after reviewing your connection." : "Discover supported documents without preparing their content." });
        if (this.live() && completed && this.notified !== job.id) { this.notified = job.id; this.onComplete(); }
      }
    } catch {
      this.publish({ ...this.state, phase: "unknown", message: "Discovery status is unavailable. Check status before starting another request." });
    } finally { this.busy = false; }
  };
  start = async () => {
    if (this.busy || !this.live() || !["idle", "complete"].includes(this.state.phase) || !this.state.connected) return;
    await this.check();
    if (!this.live() || this.busy || !["idle", "complete"].includes(this.state.phase) || !this.state.connected) return;
    this.busy = true;
    // Immutable request scope. Receipt bookkeeping deliberately outlives the UI.
    const intent: Intent = { jobId: null, submissionId: crypto.randomUUID(), revision: this.revision };
    let apiCalled = false;
    let acceptedId: string | null = null;
    try {
      if (!await this.replace(null, intent)) throw new SyncSubmissionError("not_submitted");
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
        this.publish({ ...this.state, phase: "blocked", message: "The Drive check was not accepted. Verify your connection and check discovery status before explicitly trying again. Safe browser storage and coordination must be available." });
      } else if (acceptedId) {
        this.publish({ ...this.state, phase: "active", message: "Drive discovery accepted. Check its status." });
      } else {
        this.publish({ ...this.state, phase: "unknown", message: "The discovery request could not be confirmed. Check status; do not submit it again." });
      }
    } finally { this.busy = false; }
    if (this.live() && this.state.phase === "active") await this.check();
  };
}
