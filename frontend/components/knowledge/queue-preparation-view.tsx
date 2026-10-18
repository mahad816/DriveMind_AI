"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { listDriveFiles } from "@/lib/api/files";
import type { DriveFileRead } from "@/lib/api/types";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import { preparationEligibility, preparationFrame } from "@/lib/knowledge/single-file-preparation";
import { PreparationQueue, queueConfirmation } from "@/lib/knowledge/preparation-queue";
import { PreparationProgress } from "@/components/knowledge/preparation-progress";
import { PreparationReview } from "@/components/files/preparation-review";

type Props = { owner: string; draft?: readonly DriveFileRead[]; onBack?: (reserved: boolean) => void; onRemove?: (id: string) => void };

/** Review and observe the C1 coordinator; rendering/polling never grants permission. */
export function QueuePreparationView({ owner, draft, onBack, onRemove }: Props) {
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

  if (!queue && draft && ["idle", "checking"].includes(state.phase)) return <PreparationReview
    draft={draft} inventory={inventory} working={working}
    disabled={state.phase !== "idle" || working || !inventory || metadataError || invalidDraft}
    error={actionError ?? (metadataError ? "Document details could not be verified. Return to Files and refresh before continuing." : null)}
    onRemove={onRemove} onPrepare={() => void start()} onBack={back} />;

  if (queue) return <PreparationProgress owner={owner} state={state} inventory={inventory} metadataError={metadataError}
    actionError={actionError} working={working} canConfirm={canConfirm}
    onConfirm={() => void start()} onCheck={() => { void controller.check(); void refreshMetadata(); }}
    onClose={() => void close()} onBack={onBack ? back : undefined} onLeave={back} />;

  const message = actionError ?? (metadataError ? "Document details could not be verified. Processing is paused. Check status before continuing." : state.message);
  return <section aria-label="Preparation status" className="preparation-workspace" aria-busy={working}>
    <header className="files-page-header"><h1 ref={heading} tabIndex={-1} className="editorial-display">Preparation</h1></header>
    <div className="preparation-panel preparation-empty">
      <p role={state.phase === "blocked" || metadataError || actionError ? "alert" : "status"}>{message}</p>
      <div className="preparation-actions">
        {onBack ? <Button variant="ghost" onClick={back}>Back to files</Button> : <Link onClick={back} href="/files" className={buttonVariants({ variant: "ghost" })}>Back to files</Link>}
        <Button variant="ghost" disabled={working} onClick={() => { void controller.check(); void refreshMetadata(); }}>Check status</Button>
        {chatReady && <Link onClick={back} href="/chat" className={buttonVariants()}>Start chatting</Link>}
        {state.phase === "legacy" && <Link onClick={back} href="/prepare" className={buttonVariants()}>Review existing preparation</Link>}
        {state.phase === "blocked" && <Link onClick={back} href="/settings" className={buttonVariants({ variant: "ghost" })}>Settings</Link>}
      </div>
    </div>
  </section>;
}
