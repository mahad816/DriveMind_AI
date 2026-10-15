import { listDriveFiles } from "@/lib/api/files";
import { getDriveSyncStatus, submitFilePreparationStage, SyncSubmissionError } from "@/lib/api/indexing";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import type { DriveFileRead, IndexingJobRead } from "@/lib/api/types";
import { DEMO_MODE } from "@/lib/demo";

export const preparationKey = (owner: string) => `drivemind:preparation:v1:${owner}`;
const discoveryKey = (owner: string) => `drivemind:discovery:v1:${owner}`;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const stages = ["INGEST", "CHUNK", "BUILD"] as const;
type Stage = typeof stages[number];
type Receipt = { stage: Stage; submissionId: string; jobId: string | null };
export type PreparationRecord = { fileId: string; runId: string; frame: string; receipts: Receipt[] };
type Record = PreparationRecord;
/** Internal adapter: queue storage owns the gate; this executor owns stage semantics. */
export type PreparationStore = {
  read(): Record;
  replace(expected: Record | null, next: Record | null, reserve: boolean): Promise<boolean>;
};
type Continuation = { runId: string; fileId: string; generation: number };
export function validatePreparationRecord(value: unknown, allowEmpty = false): asserts value is PreparationRecord {
  const r = value as Record;
  if (!r || !uuid.test(r.fileId) || !uuid.test(r.runId) || typeof r.frame !== "string" ||
      !Array.isArray(r.receipts) || r.receipts.length < (allowEmpty ? 0 : 1) || r.receipts.length > 3 ||
      !r.receipts.every((v, i) => v && v.stage === stages[i] && uuid.test(v.submissionId) &&
        (v.jobId === null ? i === r.receipts.length - 1 : typeof v.jobId === "string" && uuid.test(v.jobId)))) {
    throw new Error("Invalid preparation record");
  }
}
export type PreparationState = {
  phase: "checking" | "review" | "submitting" | "active" | "continue" | "ready" | "failed" | "skipped" | "ineligible" | "blocked" | "unknown";
  file: DriveFileRead | null; job: IndexingJobRead | null; stage: Stage | null; message: string;
  canRelease: boolean;
};
const supported = new Set([
  "application/vnd.google-apps.document", "text/plain", "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/tiff", "image/bmp",
]);
/** Conservative beta policy: failures/skips need investigation, never a blind rebuild. */
export function preparationEligibility(file: DriveFileRead): string | null {
  if (!supported.has(file.mime_type)) return "This document type is not supported.";
  if (file.status === "indexed") return "This document is already ready for chat.";
  if (file.status === "indexing") return "This document has processing state. Open preparation progress; do not start it again.";
  if (file.status === "failed") return "Previous preparation failed. Ask the beta owner to review the job before trying again.";
  if (file.status === "skipped") return "This document was skipped. It may have no searchable text or no longer be eligible. Ask the beta owner to review it.";
  return file.status === "discovered" ? null : "Document eligibility could not be established.";
}
export const preparationFrame = (f: DriveFileRead) => JSON.stringify([f.drive_file_id, f.mime_type, f.modified_at]);
const frame = preparationFrame;
const initial: PreparationState = { phase: "checking", file: null, job: null, stage: null, message: "Checking document and preparation status…", canRelease: false };

/** A single immutable target. Remounted observers never resume mutations by themselves. */
export class SingleFilePreparation {
  private state = initial;
  private listeners = new Set<() => void>();
  private revision = sessionRevision();
  private disposed = false;
  private busy = false;
  private generation = 0;
  private continuation: Continuation | null = null;
  private observed: Record | null = null;
  constructor(private owner: string, private requestedFileId: string | null, private store?: PreparationStore) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  connect = () => { this.disposed = false; };
  pause = () => { this.generation += 1; this.continuation = null; };
  dispose = () => { this.disposed = true; this.pause(); };
  private live = () => !DEMO_MODE && !this.disposed && sessionOwner() === this.owner && sessionRevision() === this.revision;
  // Permission objects are controller-local; live() binds owner and session revision.
  private permitted = (permission: Continuation) => this.live() &&
    this.continuation === permission && this.generation === permission.generation;
  private matches = (permission: Continuation, record: Record | null) =>
    record?.runId === permission.runId && record.fileId === permission.fileId;
  private publish(value: Partial<PreparationState>) {
    if (this.live()) { this.state = { ...this.state, ...value }; this.listeners.forEach(listener => listener()); }
  }
  private read(): Record | null {
    if (this.store) return this.store.read();
    const raw = window.localStorage.getItem(preparationKey(this.owner));
    if (raw === null) return null;
    const r: unknown = JSON.parse(raw);
    validatePreparationRecord(r);
    return r;
  }
  /** Share discovery's short owner gate; never hold a Web Lock over an API call. */
  private async replace(expected: Record | null, next: Record | null, reserve = false) {
    if (this.store) return this.store.replace(expected, next, reserve);
    if (!navigator.locks) throw new Error("Browser coordination unavailable");
    return navigator.locks.request(discoveryKey(this.owner), () => {
      if (JSON.stringify(this.read()) !== JSON.stringify(expected)) return false;
      if (reserve && window.localStorage.getItem(discoveryKey(this.owner)) !== null) return false;
      if (next) window.localStorage.setItem(preparationKey(this.owner), JSON.stringify(next));
      else window.localStorage.removeItem(preparationKey(this.owner));
      return true;
    });
  }
  private verifyJob(job: IndexingJobRead | null) {
    if (job && (job.user_id !== this.owner || !uuid.test(job.id))) throw new Error("Job owner mismatch");
  }
  check = async () => {
    if (this.busy || !this.live()) return;
    this.busy = true;
    try {
      const record = this.read(), receipt = record?.receipts.at(-1);
      // Observation may follow another workflow; consent must never follow it.
      if (this.continuation && !this.matches(this.continuation, record)) this.pause();
      const [inventory, latest, exact] = await Promise.all([
        listDriveFiles(AbortSignal.timeout(15_000)), getDriveSyncStatus(undefined, AbortSignal.timeout(15_000)),
        receipt?.jobId ? getDriveSyncStatus(receipt.jobId, AbortSignal.timeout(15_000)) : Promise.resolve(null),
      ]);
      if (!this.live()) return;
      if (latest.demo_mode === true || exact?.demo_mode === true || typeof latest.connected !== "boolean") throw new Error("Mode mismatch");
      this.verifyJob(latest.job); this.verifyJob(exact?.job ?? null);
      if (JSON.stringify(this.read()) !== JSON.stringify(record)) throw new Error("Preparation changed");
      this.observed = record;
      const fileId = record?.fileId ?? this.requestedFileId;
      const file = inventory.files.find(f => f.id === fileId) ?? null;
      if (file && file.user_id !== this.owner) throw new Error("File owner mismatch");
      if (record && record.receipts.length === 0 && (!file || frame(file) !== record.frame)) throw new Error("Reviewed document changed");
      if (receipt?.jobId && (!exact?.job || exact.job.id !== receipt.jobId || exact.job.file_id !== record?.fileId || exact.job.operation !== receipt.stage)) throw new Error("Job target mismatch");
      const job = exact?.job;
      // Latest-owner evidence cannot stand in for this stage's lost receipt.
      this.publish({ file, job: record ? job ?? null : latest.job, stage: receipt?.stage ?? null, canRelease: false });
      // A running BUILD can carry recovery protection while external writes are
      // in flight. Observe that exact active job; never release/retry it. A
      // terminal flag (or a different recovery blocker) needs operator review.
      const observingProtectedJob = job && ["queued", "running"].includes(job.status) &&
        latest.job?.id === job.id && ["queued", "running"].includes(latest.job.status);
      if ((latest.job?.recovery_required || job?.recovery_required) && !observingProtectedJob) {
        this.publish({ phase: "blocked", message: "Existing work needs recovery review. Ask the beta owner for help; do not prepare it again." });
      } else if (receipt && !receipt.jobId) {
        this.publish({ phase: "unknown", message: "The request could not be confirmed. Check status; do not submit it again. Ask the beta owner to investigate if this persists." });
      } else if (job && ["queued", "running"].includes(job.status)) {
        this.publish({ phase: "active", message: job.status === "queued" ? "Preparation stage queued." : "Preparation stage in progress. You can leave this page; the server job may continue." });
      } else if (job && ["failed", "canceled"].includes(job.status)) {
        this.publish({ phase: "failed", canRelease: true, message: "This stage did not complete successfully. No further stages will start. Ask the beta owner to review it before retrying." });
      } else if (job?.status === "completed" && (job.skipped === 1 || file?.status === "skipped")) {
        this.publish({ phase: "skipped", canRelease: true, message: "This document was skipped. No further stages will start. It may not contain searchable text." });
      } else if (record && job) {
        if (job.status !== "completed" || job.total !== 1 || job.processed !== 1 || job.succeeded !== 1 || job.failed !== 0 || job.skipped !== 0) throw new Error("Incomplete single-file evidence");
        if (!file || frame(file) !== record.frame) throw new Error("Document changed");
        if (latest.job?.id !== job.id) throw new Error("Intervening work requires review");
        if (receipt?.stage === "BUILD") {
          if (file.status !== "indexed") throw new Error("Indexed status not confirmed");
          this.publish({ phase: "ready", canRelease: true, message: "This document is ready for chat." });
        } else {
          if (file.status !== "indexing") throw new Error("Stage output not confirmed");
          this.publish({ phase: latest.connected ? "continue" : "blocked", message: latest.connected ? "Stage completed. Continue to the next preparation stage." : "Reconnect Google Drive in Settings before continuing preparation." });
        }
      } else if (latest.job && ["queued", "running"].includes(latest.job.status)) {
        this.publish({ phase: "blocked", message: "Another job is active. Wait for it to finish, then check status." });
      } else if (window.localStorage.getItem(discoveryKey(this.owner)) !== null) {
        this.publish({ phase: "blocked", message: "Drive discovery needs attention. Return to Files and check discovery status before preparation." });
      } else if (!latest.connected) {
        this.publish({ phase: "blocked", message: "Connect Google Drive in Settings, then check status." });
      } else if (!file) {
        this.publish({ phase: "ineligible", message: "Choose a document from Files. The selected document may no longer be available." });
      } else {
        const reason = preparationEligibility(file);
        this.publish({ phase: reason ? "ineligible" : "review", message: reason ?? "One document selected. Review it before preparing." });
      }
    } catch {
      this.pause();
      this.publish({ phase: "unknown", canRelease: false, message: "Preparation status could not be verified. Check status; do not repeat a submitted stage. Ask the beta owner for help if this persists." });
    } finally { this.busy = false; }
    const permission = this.continuation;
    if (permission && this.permitted(permission) && this.matches(permission, this.observed) && this.state.phase === "continue") await this.submitNext(permission);
    else if (permission && !["active", "submitting"].includes(this.state.phase)) this.pause();
  };
  confirm = async () => {
    if (this.busy || !this.live() || !["review", "continue"].includes(this.state.phase)) return;
    const reviewed = this.state.file;
    const generation = this.generation;
    const reviewedRun = this.observed?.runId;
    await this.check();
    if (!this.live() || generation !== this.generation || reviewedRun !== this.observed?.runId || !reviewed || this.state.file?.id !== reviewed.id || frame(this.state.file) !== frame(reviewed)) return;
    if (!["review", "continue"].includes(this.state.phase)) return;
    const permission = { runId: this.observed?.runId ?? crypto.randomUUID(), fileId: reviewed.id, generation };
    this.continuation = permission;
    await this.submitNext(permission);
  };
  private async submitNext(permission: Continuation) {
    if (this.busy || !this.permitted(permission) || !["review", "continue"].includes(this.state.phase)) return;
    this.busy = true;
    let before: Record | null = null, intent: Record | null = null;
    let acceptedId: string | null = null;
    let submitted = false;
    try {
      before = this.observed;
      const file = this.state.file;
      if (file?.id !== permission.fileId || (before && !this.matches(permission, before))) throw new SyncSubmissionError("not_submitted");
      if (!file || (before ? before.fileId !== file.id : preparationEligibility(file) !== null)) throw new Error("Ineligible");
      const stage = stages[before?.receipts.length ?? 0];
      if (!stage) throw new Error("No further stage");
      intent = {
        fileId: file.id, runId: permission.runId, frame: before?.frame ?? frame(file),
        receipts: [...(before?.receipts ?? []), { stage, submissionId: crypto.randomUUID(), jobId: null }],
      };
      const captured = intent;
      if (!await this.replace(before, captured, true)) throw new Error("Preparation intent changed");
      if (!this.permitted(permission)) throw new SyncSubmissionError("not_submitted");
      this.publish({ phase: "submitting", stage, job: null, canRelease: false, message: "Requesting preparation for this document…" });
      submitted = true;
      await submitFilePreparationStage(stage, file.id, AbortSignal.timeout(15_000), async receipt => {
        if (receipt.outcome === "accepted") {
          const saved = { ...captured, receipts: captured.receipts.map((r, i) => i === captured.receipts.length - 1 ? { ...r, jobId: receipt.jobId } : r) };
          if (!await this.replace(captured, saved)) throw new Error("Receipt persistence failed");
          acceptedId = receipt.jobId;
        } else {
          await this.replace(captured, before);
        }
      }, () => this.permitted(permission) && JSON.stringify(this.read()) === JSON.stringify(captured));
      if (!acceptedId) throw new Error("Missing durable receipt");
      this.publish({ phase: "active", message: "Preparation stage accepted." });
    } catch (error) {
      this.pause();
      if (!submitted || (error instanceof SyncSubmissionError && error.outcome !== "unknown")) {
        if (intent) { try { await this.replace(intent, before); } catch { /* Failed cleanup must remain blocked. */ } }
        this.publish({ phase: "blocked", message: "This stage was not accepted. Check status and your connection before explicitly trying again. Browser storage and coordination must be available." });
      } else {
        this.publish({ phase: acceptedId ? "active" : "unknown", message: acceptedId ? "The stage was accepted. Check its status." : "The request could not be confirmed. Check status; do not submit it again." });
      }
    } finally { this.busy = false; }
    if (this.live() && this.state.phase === "active") await this.check();
  }
  /** Only release a known terminal receipt, never an active/uncertain/recovery marker. */
  finish = async (): Promise<boolean> => {
    const reviewedRun = this.observed;
    this.pause();
    if (this.busy || !this.live()) return false;
    await this.check();
    if (!this.live() || !this.state.canRelease || !reviewedRun ||
        this.observed?.runId !== reviewedRun.runId || this.observed.fileId !== reviewedRun.fileId) return false;
    this.busy = true;
    try {
      const record = this.observed;
      const closed = record !== null && await this.replace(record, null);
      return closed && this.live();
    } catch {
      this.publish({ phase: "blocked", canRelease: false, message: "The saved preparation could not be closed safely. Check status before continuing." });
      return false;
    } finally { this.busy = false; }
  };
}
