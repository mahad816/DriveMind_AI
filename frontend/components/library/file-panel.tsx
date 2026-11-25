"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { ExternalLink } from "lucide-react";
import { useFiles, useWorkspace } from "@/components/workspace/workspace-provider";
import { prefillComposer } from "@/components/shell/shell-context";
import { Sheet } from "@/components/ui/dialog";
import { Button, buttonClass } from "@/components/ui/button";
import { Skeleton, StatusDot } from "@/components/ui/controls";
import { FileTypeIcon } from "@/components/library/file-icon";
import { driveUrl, fileStatusExplanation, fileStatusTone, fileStatusWord, fileTypeName, selectionBlocker } from "@/lib/copy/files";
import { fetchFileTextPreview } from "@/lib/files/preview";
import { fullDate } from "@/lib/format";
import { SELECTION_LIMIT } from "@/lib/state/selection";

const TEXT_LIKE = /^(text\/|application\/json|application\/xml)/;

export function FilePanel({ fileId, onClose }: { fileId: string | null; onClose: () => void }) {
  const files = useFiles();
  const { selection, queue, tray } = useWorkspace();
  const selected = useSyncExternalStore(selection.subscribe, selection.getSnapshot, selection.getSnapshot);
  const queueState = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
  const router = useRouter();
  const file = fileId ? files.data?.find(f => f.id === fileId) ?? null : null;
  // Keep the last file while the sheet animates out.
  const [shown, setShown] = useState(file);
  useEffect(() => { if (file) setShown(file); }, [file]);
  const current = file ?? shown;
  const [preview, setPreview] = useState<{ id: string; text: string | null; loading: boolean } | null>(null);
  useEffect(() => {
    if (!file || !TEXT_LIKE.test(file.mime_type)) return;
    let live = true;
    setPreview({ id: file.id, text: null, loading: true });
    void fetchFileTextPreview(file.id, file.mime_type).then(text => { if (live) setPreview({ id: file.id, text, loading: false }); });
    return () => { live = false; };
  }, [file?.id, file?.mime_type]); // eslint-disable-line react-hooks/exhaustive-deps

  // Closing is immediate: the URL update that follows can be slow (first compile, slow device), and the panel must not
  // wait for it. Dismissal is remembered per file, so opening the same file again works.
  const [dismissed, setDismissed] = useState<string | null>(null);
  useEffect(() => { if (!fileId) setDismissed(null); }, [fileId]);
  const open = !!fileId && dismissed !== fileId && (!!file || files.loading);
  const missing = !!fileId && dismissed !== fileId && !files.loading && files.data && !file;
  const blocker = current ? selectionBlocker(current) : null;
  const isSelected = !!current && selected.includes(current.id);
  const inQueue = !!current && !!queueState.queue?.entries.some(e => e.fileId === current.id);

  return (
    <Sheet open={open || !!missing} onOpenChange={next => { if (!next) { setDismissed(fileId); onClose(); } }} side="right"
      title={missing ? "File not found" : current?.name ?? "Loading…"}
      description={current && !missing ? `${fileTypeName(current.mime_type)}, in ${current.folder_path ?? "My Drive"}` : undefined}
      footer={current && !missing ? (
        <div className="flex flex-wrap items-center gap-2">
          {current.status === "indexed" ? (
            <Button intent="primary" onClick={() => { onClose(); router.push("/chat"); requestAnimationFrame(() => prefillComposer(`In “${current.name}”, `)); }}>Ask about this document</Button>
          ) : current.status === "indexing" && inQueue ? (
            <Button intent="primary" onClick={() => { onClose(); tray.setOpen(true); }}>Show progress</Button>
          ) : !blocker ? (
            <Button intent={isSelected ? "secondary" : "primary"} disabled={!!queueState.queue || (!isSelected && selected.length >= SELECTION_LIMIT)}
              onClick={() => selection.toggle(current.id)}>{isSelected ? "Remove from selection" : "Select for preparation"}</Button>
          ) : null}
          <a href={driveUrl(current.drive_file_id)} target="_blank" rel="noreferrer" className={buttonClass("quiet")}>
            Open in Google Drive<ExternalLink className="size-3.5" aria-hidden="true" /><span className="sr-only">(opens in a new tab)</span>
          </a>
        </div>
      ) : undefined}>
      {missing ? (
        <p className="text-body text-graphite">This file is no longer in your library. It may have been removed from Drive.</p>
      ) : !current ? (
        <div className="space-y-3" aria-hidden="true"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /></div>
      ) : (
        <div className="space-y-6">
          <section aria-label="Status" className="rounded-panel bg-well/60 px-4 py-3">
            <p className="flex items-center gap-2 text-label font-medium"><StatusDot tone={fileStatusTone(current.status)} />{fileStatusWord(current.status)}</p>
            <p className="mt-1 text-label text-graphite">{fileStatusExplanation(current)}</p>
            {!blocker && !isSelected && selected.length >= SELECTION_LIMIT ? <p className="mt-1 text-meta text-caution">Five documents are already selected. Prepare those first.</p> : null}
          </section>
          <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-label">
            <dt className="text-faint">Type</dt><dd className="flex items-center gap-1.5"><FileTypeIcon mime={current.mime_type} />{fileTypeName(current.mime_type)}</dd>
            <dt className="text-faint">Folder</dt><dd className="[overflow-wrap:anywhere]">{current.folder_path ?? "My Drive"}</dd>
            <dt className="text-faint">Modified</dt><dd>{fullDate(current.modified_at)}</dd>
            {current.indexed_at ? <><dt className="text-faint">Prepared</dt><dd>{fullDate(current.indexed_at)}</dd></> : null}
          </dl>
          {TEXT_LIKE.test(current.mime_type) ? (
            <section aria-label="Preview">
              <h3 className="text-meta font-medium text-faint">Preview</h3>
              {preview?.loading ? <div className="mt-2 space-y-2" aria-hidden="true"><Skeleton className="h-3.5" /><Skeleton className="h-3.5 w-5/6" /><Skeleton className="h-3.5 w-2/3" /></div>
                : preview?.text ? <p className="mt-2 whitespace-pre-wrap font-serif text-passage text-ink">{preview.text}</p>
                : <p className="mt-2 text-label text-graphite">A preview isn&apos;t available right now. Open it in Google Drive instead.</p>}
            </section>
          ) : (
            <p className="text-label text-graphite">Previews are shown for plain-text files only. Open this one in Google Drive to read it.</p>
          )}
        </div>
      )}
    </Sheet>
  );
}
