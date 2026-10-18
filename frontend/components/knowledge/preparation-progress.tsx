"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Check, CheckCircle2, Circle, CircleAlert, Loader2 } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import type { DriveFileRead, IndexingJobRead } from "@/lib/api/types";
import { fileTypeIcon, fileTypeLabel } from "@/lib/files/utils";
import type { PreparationQueueState } from "@/lib/knowledge/preparation-queue";
import { preparationFrame, stages, type PreparationState } from "@/lib/knowledge/single-file-preparation";

const stageLabels = { INGEST: "Reading document", CHUNK: "Preparing searchable text", BUILD: "Building search index" };

/** Stage names come from the controller's exact job, never elapsed time. */
export function ProcessingStages({ stage, phase, job }: { stage: NonNullable<PreparationState["stage"]>; phase: PreparationState["phase"]; job: IndexingJobRead }) {
  const current = stages.indexOf(stage);
  const succeeded = job.status === "completed" && job.total === 1 && job.processed === 1 && job.succeeded === 1 && job.failed === 0 && job.skipped === 0;
  return <ol className="preparation-stages" aria-label="Processing stages">
    {stages.map((step, index) => {
      const done = index < current || index === current && succeeded && ["continue", "ready"].includes(phase);
      const outcome = index === current && (phase === "failed" || phase === "skipped") ? phase : null;
      const label = done ? "Completed" : index > current ? "Not started" : phase === "failed" ? "Failed" : phase === "skipped" ? "Skipped" : job.status === "queued" ? "Queued" : job.status === "running" ? "In progress" : "Needs review";
      return <li key={step} className={done ? "is-complete" : outcome ? `is-${outcome}` : index === current ? "is-current" : ""} aria-current={index === current ? "step" : undefined}>
        {done ? <Check aria-hidden="true" className="size-3" /> : outcome ? <CircleAlert aria-hidden="true" className="size-3" /> : <span aria-hidden="true" className="preparation-stage-number">{index + 1}</span>}
        <span>{stageLabels[step]}<span className="sr-only"> · {label}</span></span>
      </li>;
    })}
  </ol>;
}

type Props = {
  owner: string;
  state: PreparationQueueState;
  inventory: readonly DriveFileRead[] | null;
  metadataError: boolean;
  actionError: string | null;
  working: boolean;
  canConfirm: boolean;
  onConfirm: () => void;
  onCheck: () => void;
  onClose: () => void;
  onBack?: () => void;
  onLeave: () => void;
};

/** Read-only presentation of an existing batch. All actions belong to its controller. */
export function PreparationProgress({ owner, state, inventory, metadataError, actionError, working, canConfirm, onConfirm, onCheck, onClose, onBack, onLeave }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  const queue = state.queue;
  useEffect(() => { heading.current?.focus(); }, [queue?.batchId]);
  if (!queue) return null;
  const files = inventory ?? [];
  const loading = inventory === null && !metadataError;
  const blocked = state.phase === "blocked";
  const stopped = state.phase === "stopped";
  const rows = queue.entries.map((entry, index) => {
    const file = files.find(row => row.id === entry.fileId && row.user_id === owner);
    const unchanged = !!file && preparationFrame(file) === entry.frame;
    const current = index === queue.current;
    const child = current ? state.child : null;
    const ready = entry.result === "ready" && unchanged && file?.status === "indexed" && !blocked;
    const exactJob = unchanged && child?.file?.id === entry.fileId && child.file.user_id === owner && preparationFrame(child.file) === entry.frame &&
      child.job?.id === entry.receipts.at(-1)?.jobId && entry.receipts.at(-1)?.stage === child.stage && child.job?.user_id === owner && child.job.file_id === entry.fileId && child.job.operation === child.stage ? child.job : null;
    const outcome = entry.result === "failed" || child?.phase === "failed" ? "failed" : entry.result === "skipped" || child?.phase === "skipped" ? "skipped" : null;
    const label = !file && loading ? "Checking" : ready ? "Ready" : outcome === "failed" ? "Failed" : outcome === "skipped" ? "Skipped" : !unchanged || blocked ? "Needs review" :
      current && child?.phase === "submitting" ? "Requesting" : current && child?.phase === "active" ? exactJob?.status === "queued" ? "Queued" : "Preparing" :
      current && (child?.phase === "continue" || canConfirm) ? "Awaiting confirmation" : stopped ? "Not started" : "Waiting";
    return { file, current, child, exactJob, ready, label, outcome };
  });
  const completed = rows.filter(row => row.ready).length;
  const complete = state.phase === "complete" && completed === queue.entries.length && !metadataError;
  const attention = blocked || stopped || metadataError || !!actionError || state.phase === "complete" && !complete && !loading;
  const activeCount = rows.filter(row => row.label === "Preparing" || row.label === "Requesting").length;
  const queuedCount = rows.filter(row => row.label === "Queued").length;
  const waitingCount = rows.filter(row => row.label === "Waiting" || row.label === "Awaiting confirmation").length;
  const error = actionError ?? (metadataError ? "Document details could not be verified. Processing is paused. Check status before continuing." :
    blocked || stopped ? state.message : attention ? "Completed document details need verification. Check status before continuing." : null);
  const phase = complete ? "complete" : attention ? "attention" : activeCount || queuedCount ? "active" : "waiting";
  const title = attention ? "Preparation needs attention" : loading || state.phase === "checking" ? "Checking preparation" : complete ? "Documents ready" : canConfirm ? state.child?.phase === "continue" ? "Confirm to continue" : queue.current === 0 ? "Confirm to start preparation" : "Ready for the next document" : "Preparing your documents";
  const description = attention ? "Saved outcomes remain below. Review the details before continuing." : loading || state.phase === "checking" ? "Verifying saved work before showing progress." : complete ? "You can now find and ask questions about these documents." : canConfirm ? "Preparation continues only after your confirmation." : "Making your selection searchable in DriveMind.";
  const chatReady = files.some(file => file.user_id === owner && file.status === "indexed");
  const needsCheck = attention || state.child?.phase === "continue";
  const canClose = state.phase === "complete" || stopped && state.child?.canRelease;
  return <section className="preparation-workspace" aria-label="Preparation progress" aria-busy={working}>
    <header className="files-page-header"><div><h1 ref={heading} tabIndex={-1} className="editorial-display">Document preparation</h1><p>Follow your documents from Drive to searchable knowledge.</p></div></header>
    <div className="preparation-panel">
      <div className="preparation-summary">
        <span className={`preparation-symbol is-${phase}`}><span key={phase}>{complete ? <CheckCircle2 aria-hidden="true" className="size-5" /> : attention ? <CircleAlert aria-hidden="true" className="size-5" /> : activeCount || queuedCount || loading ? <Loader2 aria-hidden="true" className="size-5 preparation-spinner" /> : <Circle aria-hidden="true" className="size-5" />}</span></span>
        <div className="preparation-summary-copy" role="status" aria-live="polite" aria-atomic="true"><div key={title} className="preparation-summary-transition"><h2>{title}</h2><p>{working ? "Verifying and requesting preparation…" : description}</p></div></div>
        <p className="preparation-count">{blocked || metadataError || loading ? "—" : completed} of {queue.entries.length}<span>completed</span></p>
      </div>
      {!complete && !attention && (activeCount > 0 || queuedCount > 0 || waitingCount > 0) && <div className="preparation-counts">{activeCount > 0 && <span>{activeCount} active</span>}{queuedCount > 0 && <span>{queuedCount} queued</span>}{waitingCount > 0 && <span>{waitingCount} awaiting confirmation</span>}</div>}
      {error && <p className="preparation-error" role="alert">{error}</p>}
      <ol className="preparation-file-list" aria-label="Documents in preparation order">
        {rows.map((row, index) => {
          const Icon = fileTypeIcon(row.file?.mime_type ?? "");
          const processing = ["Preparing", "Queued", "Requesting"].includes(row.label);
          const showStages = row.current && row.exactJob && row.child?.stage && !blocked && !metadataError && ["active", "continue", "failed", "skipped"].includes(row.child.phase);
          return <li key={queue.entries[index].fileId} aria-current={row.current ? "step" : undefined} className={`${processing ? "is-active" : ""}${row.outcome ? " has-outcome" : ""}`}>
            <div className="preparation-file-row"><span className="files-type-icon"><Icon aria-hidden="true" className="size-4" /></span><div className="preparation-file-name"><h3>{row.file?.name ?? (loading ? "Checking document…" : "Document details unavailable")}</h3><p>{row.file ? fileTypeLabel(row.file.mime_type) : loading ? "Checking document details" : "Metadata could not be verified"}</p></div>
              <span className={`preparation-file-status ${row.ready ? "is-ready" : row.outcome ? "is-error" : ""}`}><span key={row.label}>{row.ready ? <Check aria-hidden="true" className="size-3" /> : row.outcome || row.label === "Needs review" ? <CircleAlert aria-hidden="true" className="size-3" /> : row.label === "Preparing" || row.label === "Requesting" ? <Loader2 aria-hidden="true" className="size-3 preparation-spinner" /> : <Circle aria-hidden="true" className="size-3" />}{row.label}</span></span>
            </div>
            {showStages && row.child?.stage && row.exactJob && <ProcessingStages stage={row.child.stage} phase={row.child.phase} job={row.exactJob} />}
          </li>;
        })}
      </ol>
      <div className="preparation-actions">
        {onBack ? <Button variant="ghost" onClick={onBack}><ArrowLeft className="size-3.5" />Back to files</Button> : <Link onClick={onLeave} href="/files" className={buttonVariants({ variant: "ghost" })}><ArrowLeft className="size-3.5" />Back to files</Link>}
        <div className="preparation-primary-actions">
          {canConfirm && !metadataError && <Button disabled={working} onClick={onConfirm}>{state.child?.phase === "continue" ? "Continue preparation" : queue.current === 0 ? "Prepare first document" : "Prepare next document"}<ArrowRight className="size-3.5" /></Button>}
          {chatReady && <Link href="/chat" onClick={onLeave} className={buttonVariants({ variant: complete ? "default" : "ghost" })}>Start chatting<ArrowRight className="size-3.5" /></Link>}
        </div>
      </div>
      {(needsCheck || canClose) && <div className="preparation-recovery-actions">
        {needsCheck && <Button variant="ghost" size="sm" disabled={working} onClick={onCheck}>Check status</Button>}
        {canClose && <Button variant="ghost" size="sm" disabled={working || metadataError || loading || state.phase === "complete" && !complete} onClick={onClose}>{state.phase === "complete" ? "Close completed preparation" : "End preparation"}</Button>}
        {blocked && <Link href="/settings" onClick={onLeave} className={buttonVariants({ variant: "ghost", size: "sm" })}>Settings</Link>}
      </div>}
    </div>
    {(!complete && !attention || chatReady) && <p className="preparation-footnote">{!complete && !attention && "Leaving does not cancel an accepted server job. Reopening checks saved work; confirm before continuing. "}{chatReady && "Chat searches your prepared knowledge generally, not only this selection."}</p>}
  </section>;
}

type SingleProps = {
  owner: string;
  state: PreparationState;
  onConfirm: () => void;
  onCheck: () => void;
  onPause: () => void;
  onReadyChat: () => void;
  onFinish: () => void;
};

/** The original single-file executor also uses the same visual language. */
export function SingleFileProgress({ owner, state, onConfirm, onCheck, onPause, onReadyChat, onFinish }: SingleProps) {
  const file = state.file?.user_id === owner ? state.file : null;
  const exactJob = file && state.job?.user_id === owner && state.job.file_id === file.id && state.job.operation === state.stage ? state.job : null;
  const ready = state.phase === "ready" && file?.status === "indexed" && exactJob?.operation === "BUILD" && exactJob.status === "completed" && exactJob.succeeded === 1 && exactJob.failed === 0 && exactJob.skipped === 0;
  const attention = ["unknown", "blocked", "failed", "skipped", "ineligible"].includes(state.phase);
  const label = ready ? "Ready" : state.phase === "failed" ? "Failed" : state.phase === "skipped" ? "Skipped" : attention ? "Needs review" : state.phase === "continue" ? "Awaiting confirmation" : state.phase === "submitting" ? "Requesting" : exactJob?.status === "queued" ? "Queued" : "Preparing";
  const Icon = fileTypeIcon(file?.mime_type ?? "");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <section className="preparation-workspace" aria-label="Preparation progress">
    <header className="files-page-header"><div><h1 ref={heading} tabIndex={-1} className="editorial-display">Document preparation</h1><p>Follow your document from Drive to searchable knowledge.</p></div></header>
    <div className="preparation-panel">
      <div className="preparation-summary"><span className={`preparation-symbol is-${ready ? "complete" : attention ? "attention" : "active"}`}><span key={label}>{ready ? <CheckCircle2 aria-hidden="true" className="size-5" /> : attention ? <CircleAlert aria-hidden="true" className="size-5" /> : <Loader2 aria-hidden="true" className="size-5 preparation-spinner" />}</span></span>
        <div className="preparation-summary-copy" role="status" aria-live="polite" aria-atomic="true"><div key={label} className="preparation-summary-transition"><h2>{ready ? "Documents ready" : attention ? "Preparation needs attention" : state.phase === "continue" ? "Confirm to continue" : "Preparing your document"}</h2>{!attention && <p>{ready ? "You can now find and ask questions about this document." : state.message}</p>}</div></div>
        <p className="preparation-count">{ready ? 1 : 0} of 1<span>completed</span></p>
      </div>
      {attention && <p className="preparation-error" role="alert">{state.message}</p>}
      <ol className="preparation-file-list" aria-label="Documents in preparation order"><li className={!ready && !attention && state.phase !== "continue" ? "is-active" : undefined}>
        <div className="preparation-file-row"><span className="files-type-icon"><Icon aria-hidden="true" className="size-4" /></span><div className="preparation-file-name"><h3>{file?.name ?? "Document details unavailable"}</h3><p>{file ? fileTypeLabel(file.mime_type) : "Metadata could not be verified"}</p></div><span className={`preparation-file-status ${ready ? "is-ready" : attention ? "is-error" : ""}`}><span key={label}>{ready ? <Check aria-hidden="true" className="size-3" /> : attention ? <CircleAlert aria-hidden="true" className="size-3" /> : <Circle aria-hidden="true" className="size-3" />}{label}</span></span></div>
        {state.stage && exactJob && ["active", "continue", "failed", "skipped"].includes(state.phase) && <ProcessingStages stage={state.stage} phase={state.phase} job={exactJob} />}
      </li></ol>
      <div className="preparation-actions">{state.canRelease ? <Button variant="ghost" onClick={onFinish}><ArrowLeft className="size-3.5" />Back to files</Button> : <Link href="/files" onClick={onPause} className={buttonVariants({ variant: "ghost" })}><ArrowLeft className="size-3.5" />Back to files</Link>}
        {state.phase === "continue" && <Button onClick={onConfirm}>Continue preparation<ArrowRight className="size-3.5" /></Button>}
        {ready && <Button onClick={onReadyChat}>Start chatting<ArrowRight className="size-3.5" /></Button>}
      </div>
      {(attention || state.phase === "continue") && <div className="preparation-recovery-actions"><Button variant="ghost" size="sm" onClick={onCheck}>Check preparation status</Button>{["blocked", "unknown"].includes(state.phase) && <Link href="/settings" onClick={onPause} className={buttonVariants({ variant: "ghost", size: "sm" })}>Settings</Link>}</div>}
    </div>
    <p className="preparation-footnote">{ready ? "Chat uses your prepared knowledge. It is not restricted to this document." : "Leaving this page does not cancel an accepted server job. After returning, confirm before any further stage starts."}</p>
  </section>;
}
