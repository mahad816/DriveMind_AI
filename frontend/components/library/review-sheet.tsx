"use client";
import { useState, useSyncExternalStore } from "react";
import { X } from "lucide-react";
import { useWorkspace } from "@/components/workspace/workspace-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { Sheet } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { FileTypeIcon } from "@/components/library/file-icon";
import { fileTypeName } from "@/lib/copy/files";
import type { DriveFileRead } from "@/lib/api/types";

/** Explicit review before anything is sent. Reserving re-reads the server; nothing is prepared until the first click. */
export function ReviewSheet({ open, onOpenChange, files, onRemove, onStarted }: {
  open: boolean; onOpenChange: (open: boolean) => void; files: DriveFileRead[]; onRemove: (id: string) => void; onStarted: () => void;
}) {
  const { queue, tray } = useWorkspace();
  const session = useApplicationSession();
  const queueState = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const occupied = !!queueState.queue || queueState.phase === "legacy";

  const start = async () => {
    setBusy(true); setError(null);
    try {
      // The kept controller re-reads files and status, checks owner, eligibility and that nothing else is running,
      // then reserves the batch and submits only the first document's first step.
      const reserved = await queue.reserve(files, true);
      if (reserved) { tray.setOpen(true); onStarted(); }
      else setError("Preparation couldn't start. Another preparation or Drive check may still be running, or a document changed in Drive. Nothing was sent; check the library and try again.");
    } catch {
      setError("Preparation couldn't start. Nothing was sent; try again in a moment.");
    } finally { setBusy(false); }
  };

  return (
    <Sheet open={open} onOpenChange={next => { if (!busy) onOpenChange(next); }} side="right" title="Prepare these documents?"
      description={`${files.length} of 5 selected`}
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button intent="quiet" onClick={() => onOpenChange(false)} disabled={busy}>Back</Button>
          <Button intent="primary" loading={busy} disabled={!files.length || occupied || !session.canMutate} onClick={() => void start()}>Prepare first document</Button>
        </div>
      }>
      <ol className="divide-y divide-rule border-y border-rule">
        {files.map((file, i) => (
          <li key={file.id} className="flex items-start gap-3 py-3">
            <span className="mt-0.5 w-4 text-meta tabular text-faint">{i + 1}</span>
            <FileTypeIcon mime={file.mime_type} className="mt-0.5" />
            <span className="min-w-0 flex-1">
              <span className="block text-label text-ink [overflow-wrap:anywhere]">{file.name}</span>
              <span className="block text-meta text-faint">{fileTypeName(file.mime_type)}</span>
            </span>
            <button type="button" onClick={() => onRemove(file.id)} disabled={busy} aria-label={`Remove ${file.name}`}
              className="press grid size-7 place-items-center rounded-control text-graphite hover:bg-well hover:text-ink"><X className="size-3.5" aria-hidden="true" /></button>
          </li>
        ))}
      </ol>
      {!files.length ? <p className="mt-4 text-label text-graphite">No documents selected. Go back and choose up to five.</p> : null}
      <section className="mt-6 space-y-2 text-label text-graphite">
        <h3 className="text-label font-medium text-ink">What happens next</h3>
        <p>DriveMind reads each document from Drive, one at a time, so answers can quote it. Your Drive is never changed.</p>
        <p>You&apos;ll confirm before each next document starts. Progress stays visible in a panel while you keep working.</p>
        <p>A document that can&apos;t be read is marked and skipped; the rest can still be prepared.</p>
      </section>
      {occupied ? <p role="status" className="mt-4 text-label text-caution">A preparation is already in progress. Finish or stop it first.</p> : null}
      {error ? <p role="alert" className="mt-4 text-label text-fault">{error}</p> : null}
    </Sheet>
  );
}
