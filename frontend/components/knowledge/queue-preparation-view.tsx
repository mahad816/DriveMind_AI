"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { listDriveFiles } from "@/lib/api/files";
import type { DriveFileRead } from "@/lib/api/types";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import { fileTypeLabel } from "@/lib/files/utils";
import { preparationEligibility, preparationFrame } from "@/lib/knowledge/single-file-preparation";
import { PreparationQueue, queueConfirmation } from "@/lib/knowledge/preparation-queue";
import { fileStatusLabel } from "@/lib/user-language";

const stageLabels = { INGEST: "Reading document", CHUNK: "Preparing searchable text", BUILD: "Building search index" };

type Props = { owner: string; draft?: readonly DriveFileRead[]; onBack?: (reserved: boolean) => void };

/** Review and observe the C1 coordinator; rendering/polling never grants permission. */
export function QueuePreparationView({ owner, draft, onBack }: Props) {
  const [controller] = useState(() => new PreparationQueue(owner));
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  const [inventory, setInventory] = useState<DriveFileRead[] | null>(null);
  const [metadataError, setMetadataError] = useState(false);
  const [working, setWorking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const scope = useRef({ alive: false, revision: sessionRevision() });
  const actionBusy = useRef(false);
  const metadataRequest = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const live = () => scope.current.alive && sessionOwner() === owner && sessionRevision() === scope.current.revision;
  const refreshMetadata = async () => {
    const request = ++metadataRequest.current;
    try {
      const result = await listDriveFiles(AbortSignal.timeout(15_000));
      if (!live() || request !== metadataRequest.current) return;
      if (result.files.some(f => f.user_id !== owner)) throw new Error("Metadata owner mismatch");
      setInventory(result.files); setMetadataError(false);
    } catch {
      if (live() && request === metadataRequest.current) { setInventory(null); setMetadataError(true); controller.pause(); }
    }
  };
  // The coordinator instance and verified owner are fixed for this component lifetime.
  useEffect(() => {
    const lifetime = scope.current;
    lifetime.alive = true; controller.connect();
    const observe = () => { void controller.check(); void refreshMetadata(); };
    const pause = () => { controller.pause(); };
    const visibility = () => { if (document.hidden) pause(); };
    observe();
    const timer = window.setInterval(observe, 3000);
    window.addEventListener("pagehide", pause); document.addEventListener("visibilitychange", visibility);
    window.addEventListener("storage", observe);
    return () => {
      lifetime.alive = false; controller.dispose();
      clearInterval(timer); window.removeEventListener("pagehide", pause);
      document.removeEventListener("visibilitychange", visibility); window.removeEventListener("storage", observe);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controller]);

  const files = inventory ?? [];
  const queue = state.queue;
  useEffect(() => { heading.current?.focus(); }, [queue?.batchId]);
  const entries = queue?.entries ?? draft?.map(f => ({ fileId: f.id, frame: preparationFrame(f), result: "pending" as const })) ?? [];
  const invalidDraft = !draft?.length || draft.length > 5 || new Set(draft.map(f => f.id)).size !== draft.length ||
    entries.some(e => { const file = files.find(f => f.id === e.fileId); return !file || preparationEligibility(file) !== null || preparationFrame(file) !== e.frame; });
  const current = queue?.entries[queue.current];
  const confirmation = queue ? queueConfirmation(queue) : undefined;
  // Never enable an action for a document whose authorized name/frame is unavailable.
  const currentFile = current ? files.find(f => f.id === current.fileId) : null;
  const canConfirm = !!confirmation && !!currentFile && preparationFrame(currentFile) === current?.frame &&
    (state.child?.phase === "continue" ? currentFile.status === "indexing" : preparationEligibility(currentFile) === null) &&
    ["review", "awaiting_next", "progress"].includes(state.phase) &&
    (state.child?.phase === "review" || state.child?.phase === "continue" || (state.phase === "awaiting_next" && state.child === null));
  const start = async () => {
    if (actionBusy.current || !live() || !inventory || metadataError) return;
    actionBusy.current = true; setWorking(true); setActionError(null);
    try {
      if (queue) {
        if (canConfirm && confirmation) await controller.confirm(confirmation);
      } else if (draft && state.phase === "idle" && !invalidDraft) {
        const reserved = await controller.reserve(draft, true);
        if (!reserved && live()) setActionError("Preparation could not start. Check status; existing work must be resolved before reserving another selection.");
      }
    } catch {
      if (live()) setActionError("Preparation could not be verified. Check status before trying anything again.");
    } finally {
      actionBusy.current = false;
      if (live()) { setWorking(false); void refreshMetadata(); }
    }
  };
  const back = () => { controller.pause(); onBack?.(!!queue); };
  const chatReady = files.some(f => f.status === "indexed");
  const close = async () => {
    if (actionBusy.current || !live() || !queue) return;
    actionBusy.current = true; setWorking(true); setActionError(null);
    try {
      const closed = await controller.finish(queue);
      if (live() && !closed) setActionError("This preparation could not be closed safely. Check status; unresolved work must remain saved.");
      if (live() && closed) onBack?.(true);
    } finally { actionBusy.current = false; if (live()) setWorking(false); }
  };

  return <section aria-label={queue ? "Preparation progress" : "Review selection"} aria-busy={working} className="min-w-0 space-y-5">
    <div className="space-y-2">
      <h2 ref={heading} tabIndex={-1} className="text-xl font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">{queue ? state.phase === "complete" ? "Documents ready" : "Document preparation" : draft ? "Review selection" : "Preparation"}</h2>
      {entries.length ? <p className="text-sm text-muted-foreground">{entries.length} {entries.length === 1 ? "document" : "documents"} · Prepared one at a time, in this order.</p> : null}
    </div>
    <p role="status" aria-live="polite" className="text-sm leading-6">{working ? "Checking and requesting preparation…" : state.message}</p>
    {metadataError ? <p role="alert" className="text-sm">Document details could not be verified. Processing is paused. Check status before continuing.</p> : inventory === null ? <p className="text-sm text-muted-foreground">Loading authorized document details…</p> : null}
    {actionError ? <p role="alert" className="text-sm">{actionError}</p> : null}
    {entries.length ? <ol aria-label="Documents in preparation order" className="divide-y divide-border border-y border-border">
      {entries.map((entry, index) => {
        const file = files.find(f => f.id === entry.fileId);
        const changed = !file || preparationFrame(file) !== entry.frame;
        const active = !!queue && index === queue.current;
        let label = "Not started";
        let detail: string | null = null;
        if (entry.result === "ready") label = changed || file?.status !== "indexed" || state.phase === "blocked" ? "Needs review" : "Ready";
        else if (entry.result === "failed") label = "Failed";
        else if (entry.result === "skipped") label = "Skipped";
        else if (active && state.phase === "blocked") label = "Needs review";
        else if (active && state.child?.phase === "failed") label = "Failed";
        else if (active && state.child?.phase === "skipped") label = "Skipped";
        else if (active && state.child?.stage) {
          label = stageLabels[state.child.stage];
          detail = state.child.phase === "continue" ? "Stage completed · Confirm to continue" : state.child.job?.status === "running" ? "In progress" : state.child.job?.status === "queued" ? "Queued" : "Needs review";
        }
        if (!queue && (changed || (file && preparationEligibility(file)))) {
          label = "Needs attention"; detail = changed ? "Document metadata changed or is unavailable. Return to Files and review this selection." : preparationEligibility(file!);
        }
        return <li key={entry.fileId} aria-current={active ? "step" : undefined} className="flex min-w-0 gap-3 py-4">
          <span aria-hidden="true" className="pt-0.5 text-sm tabular-nums text-muted-foreground">{index + 1}.</span>
          <div className="min-w-0 flex-1 space-y-1">
            <h3 className="break-words text-sm font-medium [overflow-wrap:anywhere]">{file?.name ?? "Document details unavailable"}</h3>
            <p className="text-xs text-muted-foreground">{file ? fileTypeLabel(file.mime_type) : "Type unavailable"}{!queue && file ? ` · ${fileStatusLabel[file.status]}` : ""}</p>
            <p className="text-sm">{label}</p>
            {detail ? <p className="text-sm leading-6 text-muted-foreground">{detail}</p> : null}
          </div>
        </li>;
      })}
    </ol> : null}
    {!queue && draft ? <p className="text-sm leading-6 text-muted-foreground">DriveMind will read these documents, extract searchable text, and create a search index. Relevant content is processed using the configured AI services. Your original Google Drive documents will not be modified. You’ll confirm before each next document starts.</p> : null}
    {queue && ["progress", "awaiting_next", "review"].includes(state.phase) ? <p className="text-sm leading-6 text-muted-foreground">Leaving this page does not cancel an accepted server job. Returning or refreshing only checks saved work; confirm before continuing. Each next document requires your confirmation.</p> : null}
    {queue && ["blocked", "stopped"].includes(state.phase) ? <p className="text-sm leading-6 text-muted-foreground">Preparation has stopped. Earlier ready documents remain available. Check status or ask the beta owner to investigate. Do not repeat an uncertain request or clear saved preparation.</p> : null}
    <div className="flex flex-wrap gap-2">
      {!queue && draft && state.phase === "idle" ? <Button disabled={working || !inventory || metadataError || invalidDraft} onClick={() => void start()}>Prepare first document</Button> : null}
      {canConfirm ? <Button disabled={working || metadataError} onClick={() => void start()}>{state.child?.phase === "continue" ? "Continue preparation" : queue!.current === 0 ? "Prepare first document" : "Prepare next document"}</Button> : null}
      {onBack ? <Button variant="outline" onClick={back}>{queue ? "Back to files" : "Cancel review"}</Button> : <Link onClick={back} href="/files" className={buttonVariants({ variant: "outline" })}>Back to files</Link>}
      <Button variant="ghost" disabled={working} onClick={() => { void controller.check(); void refreshMetadata(); }}>Check status</Button>
      {chatReady ? <Link onClick={back} href="/chat" className={buttonVariants()}>Start chatting</Link> : null}
      {queue && (state.phase === "complete" || (state.phase === "stopped" && state.child?.canRelease)) ? <Button variant="outline" disabled={working} onClick={() => void close()}>{state.phase === "complete" ? "Close completed preparation" : "End preparation"}</Button> : null}
      {state.phase === "legacy" ? <Link onClick={back} href="/prepare" className={buttonVariants()}>Review existing preparation</Link> : null}
      {state.phase === "blocked" ? <Link onClick={back} href="/settings" className={buttonVariants({ variant: "ghost" })}>Settings</Link> : null}
    </div>
    {chatReady ? <p className="text-sm leading-6 text-muted-foreground">Chat searches your prepared knowledge generally, not only this selection.</p> : null}
  </section>;
}
