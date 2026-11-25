"use client";
import Link from "next/link";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { ExternalLink, FileText, Maximize2 } from "lucide-react";
import type { CitationItem, DriveFileRead, SourceChunkRead } from "@/lib/api/types";
import { getSourceChunk } from "@/lib/api/sources";
import { isApiError } from "@/lib/api/errors";
import { locateSnippet } from "@/lib/chat/passage";
import { driveUrl } from "@/lib/copy/files";
import { noteId } from "@/components/chat/answer-prose";
import { Sheet } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/controls";
import { cn } from "@/lib/utils";

/** Passages fetched this session, per owner (the cache lives under the owner-keyed workspace). */
type Entry = { status: "loading" | "ready" | "gone" | "error"; data?: SourceChunkRead };
export class PassageCache {
  private entries = new Map<string, Entry>();
  private inFlight = new Map<string, Promise<Entry>>();
  get(id: string) { return this.entries.get(id); }
  load(id: string): Promise<Entry> {
    const known = this.entries.get(id);
    if (known?.status === "ready" || known?.status === "gone") return Promise.resolve(known);
    const pending = this.inFlight.get(id);
    if (pending) return pending;
    const run = getSourceChunk(id).then<Entry, Entry>(
      data => ({ status: "ready", data }),
      error => ({ status: isApiError(error) && error.status === 404 ? "gone" : "error" }),
    ).then(entry => { this.entries.set(id, entry); this.inFlight.delete(id); return entry; });
    this.inFlight.set(id, run);
    return run;
  }
}
export const PassageCacheContext = createContext<PassageCache | null>(null);

export function usePassage(chunkId: string, enabled: boolean) {
  const cache = useContext(PassageCacheContext);
  const [entry, setEntry] = useState<Entry | undefined>(() => cache?.get(chunkId));
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled || !cache) return;
    let live = true;
    if (!cache.get(chunkId) || cache.get(chunkId)?.status === "error") setEntry({ status: "loading" });
    void cache.load(chunkId).then(next => { if (live) setEntry(next); });
    return () => { live = false; };
  }, [cache, chunkId, enabled, attempt]);
  return { entry, retry: () => setAttempt(a => a + 1) };
}

/** The library the citations point into. The signed-in chat provides the person's files; the public demo provides
 *  none, so its notes show no Drive or file-details links (its sample documents are not in anyone's Drive). */
export const CitedFilesContext = createContext<readonly DriveFileRead[] | null>(null);
/** The Google file behind a citation. Citations carry DriveMind's file id; Drive links need Google's. */
export function useCitedFile(citation: CitationItem): DriveFileRead | undefined {
  return useContext(CitedFilesContext)?.find(f => f.id === citation.drive_file_id);
}

export function EvidenceNote({ citation, n, turnId, active, expanded, onExpand, onHover, conversationId, variant }: {
  citation: CitationItem; n: number; turnId: string; active: boolean; expanded: boolean; onExpand: (open: boolean) => void;
  onHover?: (n: number | null) => void; conversationId: string | null; variant: "margin" | "sheet";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const file = useCitedFile(citation);
  const { entry, retry } = usePassage(citation.chunk_id, expanded);
  useEffect(() => { if (expanded) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [expanded]);
  const parts = entry?.data ? locateSnippet(entry.data.text, citation.snippet) : null;

  return (
    <div ref={ref} id={noteId(turnId, n)} role="note" aria-label={`Source ${n}: ${citation.filename}`}
      onMouseEnter={() => onHover?.(n)} onMouseLeave={() => onHover?.(null)}
      className={cn("group relative rounded-panel py-3 transition-colors duration-150",
        variant === "margin" ? "pl-4 pr-1" : "px-0",
        variant === "margin" && (active || expanded ? "bg-sheet" : "hover:bg-sheet/60"))}>
      {variant === "margin" ? <span aria-hidden="true" className={cn("absolute inset-y-3 left-0 w-px transition-colors duration-150", active || expanded ? "bg-highlight-edge" : "bg-rule")} /> : null}
      <p className="flex items-start gap-2">
        <span className={cn("mt-px inline-grid h-[1.15rem] min-w-[1.15rem] shrink-0 place-items-center rounded-[5px] px-1 text-[0.6875rem] font-semibold tabular transition-colors duration-150",
          active ? "bg-highlight text-ink" : "bg-archive-wash text-archive-text")}>{n}</span>
        <span className="min-w-0 text-label font-medium text-ink truncate-2" title={citation.filename}>{citation.filename}</span>
      </p>
      {!expanded ? (
        <blockquote className="mt-2 font-serif text-passage text-ink">
          <span className={cn("mark mark-swipe", active && "is-on")}>{citation.snippet}</span>
        </blockquote>
      ) : (
        <div className="mt-2">
          {entry?.status === "ready" && entry.data ? (
            <blockquote className="max-h-[22rem] overflow-y-auto whitespace-pre-wrap font-serif text-passage text-ink">
              {parts ? <>{parts.before}<mark className="mark mark-swipe is-on text-ink">{parts.match}</mark>{parts.after}</> : entry.data.text}
            </blockquote>
          ) : entry?.status === "gone" ? (
            <p className="text-label text-graphite">This passage is no longer available. The document may have been prepared again since this answer.</p>
          ) : entry?.status === "error" ? (
            <p className="text-label text-graphite">The full passage couldn&apos;t load. <button type="button" onClick={retry} className="text-archive-text underline underline-offset-2">Try again</button></p>
          ) : (
            <div aria-hidden="true" className="space-y-2 py-1"><Skeleton className="h-3.5" /><Skeleton className="h-3.5 w-11/12" /><Skeleton className="h-3.5 w-2/3" /></div>
          )}
          {entry?.status === "ready" && !parts ? <p className="mt-2 text-meta text-faint">The cited words couldn&apos;t be matched exactly in this passage, so nothing is highlighted.</p> : null}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-meta">
        <button type="button" onClick={() => onExpand(!expanded)} aria-expanded={expanded}
          className="font-medium text-archive-text underline-offset-2 hover:underline">{expanded ? "Show excerpt" : "Open passage"}</button>
        {file ? (
          <a href={driveUrl(file.drive_file_id)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-graphite hover:text-ink">
            Open in Drive<ExternalLink className="size-3" aria-hidden="true" /><span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : null}
        {expanded ? (
          <>
            <Link href={`/files?file=${citation.drive_file_id}`} className="inline-flex items-center gap-1 text-graphite hover:text-ink"><FileText className="size-3" aria-hidden="true" />File details</Link>
            <Link href={`/sources/${citation.chunk_id}${conversationId ? `?conversation=${conversationId}` : ""}`} className="inline-flex items-center gap-1 text-graphite hover:text-ink">
              <Maximize2 className="size-3" aria-hidden="true" />Full page</Link>
          </>
        ) : null}
      </div>
    </div>
  );
}

/** ≥1280 px: notes sit beside the answer that cites them, sticky within it. */
export function EvidenceMargin({ citations, turnId, active, setActive, expanded, setExpanded, conversationId }: {
  citations: readonly CitationItem[]; turnId: string; active: number | null; setActive: (n: number | null) => void;
  expanded: number | null; setExpanded: (n: number | null) => void; conversationId: string | null;
}) {
  return (
    <aside aria-label="Sources for this answer" className="hidden xl:block">
      <div className="sticky top-6 space-y-1">
        {citations.map((citation, i) => (
          <EvidenceNote key={`${citation.chunk_id}-${i}`} citation={citation} n={i + 1} turnId={turnId} active={active === i + 1}
            expanded={expanded === i + 1} onExpand={open => setExpanded(open ? i + 1 : null)} onHover={setActive}
            conversationId={conversationId} variant="margin" />
        ))}
      </div>
    </aside>
  );
}

/** <1280 px: the same notes in a right sheet (tablet) or a bottom sheet (phone). */
export function EvidenceSheet({ open, onOpenChange, citations, turnId, focus, conversationId }: {
  open: boolean; onOpenChange: (open: boolean) => void; citations: readonly CitationItem[]; turnId: string; focus: number | null; conversationId: string | null;
}) {
  const [expanded, setExpanded] = useState<number | null>(focus);
  useEffect(() => { if (open) setExpanded(focus); }, [open, focus]);
  const files = new Set(citations.map(c => c.drive_file_id)).size;
  return (
    <Sheet open={open} onOpenChange={onOpenChange} side="right" width="evidence" title="Sources"
      description={`${citations.length} ${citations.length === 1 ? "passage" : "passages"} from ${files} ${files === 1 ? "document" : "documents"}`}>
      <div className="divide-y divide-rule">
        {citations.map((citation, i) => (
          <EvidenceNote key={`${citation.chunk_id}-${i}`} citation={citation} n={i + 1} turnId={`${turnId}-sheet`} active={expanded === i + 1}
            expanded={expanded === i + 1} onExpand={next => setExpanded(next ? i + 1 : null)} conversationId={conversationId} variant="sheet" />
        ))}
      </div>
    </Sheet>
  );
}
