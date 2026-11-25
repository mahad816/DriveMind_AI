"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ArrowDownUp, ChevronLeft, ChevronRight } from "lucide-react";
import { useFiles, useDriveStatus, useWorkspace } from "@/components/workspace/workspace-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { usePageTitle } from "@/components/shell/shell-context";
import { SyncButton, useDiscovery } from "@/components/library/drive-sync";
import { FilePanel } from "@/components/library/file-panel";
import { ReviewSheet } from "@/components/library/review-sheet";
import { FileTypeIcon } from "@/components/library/file-icon";
import { Button, buttonClass } from "@/components/ui/button";
import { Checkbox, SearchField, Skeleton, StatusDot } from "@/components/ui/controls";
import { Menu } from "@/components/ui/menu";
import { countViews, parseSort, parseView, selectPage, SORT_LABEL, SORTS, VIEW_LABEL, VIEWS } from "@/lib/state/library";
import type { LibrarySort, LibraryView as View } from "@/lib/state/library";
import { SELECTION_LIMIT } from "@/lib/state/selection";
import { fileStatusTone, fileStatusWord, fileTypeName, selectionBlocker } from "@/lib/copy/files";
import { friendlyDate, fullDate } from "@/lib/format";
import type { DriveFileRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import Link from "next/link";

const EMPTY_VIEW: Record<View, string> = {
  ready: "No documents are ready yet. Prepare some from “To prepare”.",
  todo: "Everything supported has been prepared or tried.",
  working: "Nothing is being prepared right now.",
  attention: "Nothing needs attention.",
  all: "No files found in your Drive yet.",
};

export function LibraryView() {
  usePageTitle("Library");
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const files = useFiles();
  const status = useDriveStatus();
  const session = useApplicationSession();
  const { selection, queue } = useWorkspace();
  const selected = useSyncExternalStore(selection.subscribe, selection.getSnapshot, selection.getSnapshot);
  const queueState = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
  const discovery = useDiscovery();

  const view = parseView(params.get("view"));
  const sort = parseSort(params.get("sort"));
  const page = Math.max(1, Number(params.get("page")) || 1);
  const openFile = params.get("file");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [capNote, setCapNote] = useState(false);
  const [reviewing, setReviewing] = useState(false);

  const setParams = useCallback((patch: Record<string, string | null>, mode: "push" | "replace" = "push") => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) { if (v === null || v === "") next.delete(k); else next.set(k, v); }
    if (next.get("view") === "all") next.delete("view");
    if (next.get("sort") === "modified") next.delete("sort");
    if (next.get("page") === "1") next.delete("page");
    const href = `${pathname}${next.size ? `?${next}` : ""}`;
    if (mode === "push") router.push(href, { scroll: false }); else router.replace(href, { scroll: false });
  }, [params, pathname, router]);
  // The filter writes to the URL after a short pause, so typing never floods history.
  useEffect(() => {
    if ((params.get("q") ?? "") === query) return;
    const t = setTimeout(() => setParams({ q: query, page: null }, "replace"), 200);
    return () => clearTimeout(t);
  }, [query, params, setParams]);
  useEffect(() => { setQuery(params.get("q") ?? ""); }, [params]); // back/forward

  const all = useMemo(() => files.data ?? [], [files.data]);
  const counts = useMemo(() => countViews(all, query), [all, query]);
  const total = useMemo(() => countViews(all), [all]);
  const result = useMemo(() => selectPage(all, view, query, sort, page, fileTypeName), [all, view, query, sort, page]);
  // Keep the selection across refetches; drop only ids that are gone or no longer selectable.
  useEffect(() => { if (files.data) selection.retain(id => { const f = files.data!.find(x => x.id === id); return !!f && !selectionBlocker(f); }); }, [files.data, selection]);
  const selectedFiles = useMemo(() => selected.map(id => all.find(f => f.id === id)).filter((f): f is DriveFileRead => !!f), [selected, all]);

  const toggle = (file: DriveFileRead) => {
    const ok = selection.toggle(file.id);
    setCapNote(!ok);
  };
  const eligibleOnPage = result.rows.filter(f => !selectionBlocker(f));
  const allOnPage = eligibleOnPage.length > 0 && eligibleOnPage.every(f => selected.includes(f.id));
  const selectPageRows = () => {
    if (allOnPage) { eligibleOnPage.forEach(f => selection.remove(f.id)); setCapNote(false); return; }
    let capped = false;
    for (const f of eligibleOnPage) if (!selection.has(f.id) && !selection.toggle(f.id)) capped = true;
    setCapNote(capped);
  };

  // Keyboard: ↑/↓ move between rows, Space selects, Enter opens (blueprint §12.2).
  const tbody = useRef<HTMLTableSectionElement>(null);
  const onRowsKey = (event: React.KeyboardEvent) => {
    const buttons = [...(tbody.current?.querySelectorAll<HTMLButtonElement>("[data-row-open]") ?? [])];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      buttons[Math.min(buttons.length - 1, Math.max(0, index + (event.key === "ArrowDown" ? 1 : -1)))]?.focus();
    } else if (event.key === " ") {
      event.preventDefault();
      const file = result.rows[index];
      if (file && !selectionBlocker(file)) toggle(file);
    }
  };

  const connected = status.data?.connected;
  const firstLoad = files.loading && !files.data;
  const failedWithoutData = !files.data && !!files.error && !files.loading;
  const preparing = !!queueState.queue;

  return (
    <div className={cn("mx-auto flex w-full max-w-6xl flex-col px-5 md:px-8", selected.length ? "pb-32" : "pb-16")}>
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4 pb-5 pt-8 md:pt-10">
        <div className="min-w-0">
          <h1 className="font-serif text-display font-medium">Library</h1>
          <p className="mt-2 max-w-xl text-body text-graphite">Choose which documents DriveMind reads and can quote. Your Drive is never changed.</p>
        </div>
        {connected !== false ? <SyncButton /> : null}
      </header>
      {discovery.view.line ? (
        <p role="status" className={cn("-mt-1 mb-4 flex items-center gap-2 text-label", discovery.view.tone === "caution" ? "text-caution" : "text-graphite")}>
          {discovery.view.running ? <StatusDot tone="working" /> : null}{discovery.view.line}
        </p>
      ) : null}

      {connected === false && all.length === 0 && !firstLoad ? (
        <ConnectCard />
      ) : (
        <>
          <div className="flex flex-col gap-3 border-b border-rule pb-3 lg:flex-row lg:items-center lg:justify-between">
            <div role="group" aria-label="Show" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-0.5">
              {VIEWS.filter(v => v !== "working" || total.working > 0).map(v => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setParams({ view: v, page: null })}
                  className={cn("press inline-flex h-8 shrink-0 items-center gap-1.5 rounded-control px-2.5 text-label touch-44",
                    view === v ? "bg-ink text-paper" : "text-graphite hover:bg-well hover:text-ink")}>
                  {VIEW_LABEL[v]}
                  <span className={cn("tabular text-meta", view === v ? "text-paper/75" : "text-faint")}>{(query ? counts : total)[v].toLocaleString()}</span>
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <SearchField value={query} onValueChange={setQuery} label="Filter by file or folder name" placeholder="Filter by name or folder" className="min-w-0 flex-1 lg:w-72" />
              <Menu label={`Sort by ${SORT_LABEL[sort]}`} trigger={
                <button type="button" className={buttonClass("secondary", "md", "gap-1.5 px-3")}><ArrowDownUp className="size-3.5" aria-hidden="true" /><span className="hidden sm:inline">{SORT_LABEL[sort]}</span></button>}
                items={SORTS.map(s => ({ label: `${SORT_LABEL[s]}${s === sort ? " (current)" : ""}`, onSelect: () => setParams({ sort: s as LibrarySort, page: null }) }))} />
            </div>
          </div>
          <div aria-hidden="true" className={cn("h-0.5 overflow-hidden transition-opacity duration-200", files.refreshing ? "opacity-100" : "opacity-0")}>
            <div className="h-full w-1/3 animate-[hairline_1.2s_var(--ease-in-out)_infinite] bg-archive/60" />
          </div>
          {files.error && files.data ? (
            <p role="status" className="mt-2 text-label text-caution">The latest file list couldn&apos;t load. Showing the list from {friendlyDate(new Date(files.updatedAt ?? 0).toISOString()).toLowerCase()}. <button type="button" className="underline underline-offset-2" onClick={() => void files.reload()}>Try again</button></p>
          ) : null}
          {query && result.total === 0 && counts.all > 0 ? (
            <p className="mt-4 text-label text-graphite">No matches in {VIEW_LABEL[view]}. <button type="button" className="text-archive-text underline underline-offset-2" onClick={() => setParams({ view: "all", page: null })}>Show {counts.all.toLocaleString()} in All</button></p>
          ) : null}

          {failedWithoutData ? (
            <div role="alert" className="py-16">
              <p className="text-body">Your file list couldn&apos;t load. Your Drive and prepared documents are unaffected.</p>
              <Button className="mt-4" onClick={() => void files.reload()}>Try again</Button>
            </div>
          ) : (
            <table className="mt-1 w-full table-fixed border-collapse text-body" aria-label={`${VIEW_LABEL[view]} files`} aria-busy={firstLoad || undefined}>
              <thead className="text-left text-meta text-faint">
                <tr className="border-b border-rule">
                  <th scope="col" className="w-10 py-2.5 pl-1 font-normal">
                    <Checkbox checked={allOnPage} onCheckedChange={selectPageRows} disabled={!eligibleOnPage.length || preparing}
                      label={allOnPage ? "Clear selection on this page" : "Select documents on this page"} />
                  </th>
                  <th scope="col" className="py-2.5 font-normal">Name</th>
                  <th scope="col" className="hidden w-[24%] py-2.5 font-normal lg:table-cell">Folder</th>
                  <th scope="col" className="hidden w-32 py-2.5 font-normal sm:table-cell">Modified</th>
                  <th scope="col" className="hidden w-36 py-2.5 pr-1 font-normal sm:table-cell">Status</th>
                </tr>
              </thead>
              <tbody ref={tbody} onKeyDown={onRowsKey}>
                {firstLoad ? Array.from({ length: 8 }, (_, i) => (
                  <tr key={i} className="border-b border-rule" aria-hidden="true">
                    <td className="py-3.5 pl-1"><Skeleton className="size-[18px]" /></td>
                    <td className="py-3.5"><Skeleton className="h-3.5 w-3/5" /></td>
                    <td className="hidden py-3.5 lg:table-cell"><Skeleton className="h-3 w-24" /></td>
                    <td className="hidden py-3.5 sm:table-cell"><Skeleton className="h-3 w-16" /></td>
                    <td className="hidden py-3.5 sm:table-cell"><Skeleton className="h-3 w-20" /></td>
                  </tr>
                )) : result.rows.map(file => {
                  const blocker = selectionBlocker(file);
                  const checked = selected.includes(file.id);
                  const atCap = !checked && selected.length >= SELECTION_LIMIT;
                  const reasonId = `reason-${file.id}`;
                  return (
                    <tr key={file.id} className={cn("group border-b border-rule transition-colors duration-100", checked ? "bg-archive-wash" : "hover:bg-sheet", openFile === file.id && "bg-sheet")}>
                      <td className="py-2.5 pl-1 align-top">
                        <span className="mt-1 inline-flex">
                          <Checkbox checked={checked} onCheckedChange={() => toggle(file)} disabled={!!blocker || atCap || preparing}
                            label={`Select ${file.name}`} describedBy={blocker || atCap || preparing ? reasonId : undefined} />
                        </span>
                        <span id={reasonId} className="sr-only">{preparing ? "Finish the current preparation first." : blocker ?? (atCap ? `Up to ${SELECTION_LIMIT} documents per batch.` : "")}</span>
                      </td>
                      <td className="min-w-0 py-2.5 pr-3">
                        <button type="button" data-row-open onClick={() => setParams({ file: file.id }, "push")}
                          className="flex w-full min-w-0 items-start gap-2.5 rounded-control text-left" title={file.name}>
                          <FileTypeIcon mime={file.mime_type} className="mt-0.5" />
                          <span className="min-w-0">
                            <span className="block truncate-2 text-ink group-hover:underline group-hover:decoration-rule-strong group-hover:underline-offset-4">{file.name}</span>
                            <span className="block truncate text-meta text-faint">{fileTypeName(file.mime_type)}<span className="lg:hidden">{file.folder_path ? `, ${file.folder_path}` : ""}</span></span>
                            <span className="mt-1 flex items-center gap-1.5 text-meta sm:hidden"><StatusDot tone={fileStatusTone(file.status)} /><span className={file.status === "failed" ? "text-fault" : "text-graphite"}>{fileStatusWord(file.status)}</span></span>
                          </span>
                        </button>
                      </td>
                      <td className="hidden truncate py-2.5 pr-3 align-top text-label text-graphite lg:table-cell" title={file.folder_path ?? undefined}><span className="mt-0.5 block truncate">{file.folder_path ?? "My Drive"}</span></td>
                      <td className="hidden py-2.5 align-top text-label text-graphite sm:table-cell"><time dateTime={file.modified_at} title={fullDate(file.modified_at)} className="mt-0.5 block">{friendlyDate(file.modified_at)}</time></td>
                      <td className="hidden py-2.5 pr-1 align-top text-label sm:table-cell">
                        <span className="mt-0.5 flex items-center gap-2"><StatusDot tone={fileStatusTone(file.status)} /><span className={file.status === "failed" ? "text-fault" : "text-ink"}>{fileStatusWord(file.status)}</span></span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {!firstLoad && !failedWithoutData && result.total === 0 && !(query && counts.all > 0) ? (
            <div className="py-14">
              <p className="text-body text-graphite">{query ? `No files named “${query}”. If it's new in Drive, check Drive for changes.` : EMPTY_VIEW[view]}</p>
              {(view === "all" || query) && connected ? <div className="mt-4"><SyncButton /></div> : null}
              {view === "ready" && total.todo > 0 && !query ? <Button className="mt-4" onClick={() => setParams({ view: "todo" })}>Show documents to prepare</Button> : null}
            </div>
          ) : null}
          {result.pages > 1 ? (
            <nav aria-label="Pages" className="mt-4 flex items-center justify-between gap-3 text-label text-graphite">
              <span className="tabular">{((result.page - 1) * 50 + 1).toLocaleString()}–{Math.min(result.page * 50, result.total).toLocaleString()} of {result.total.toLocaleString()}</span>
              <span className="flex items-center gap-1">
                <Button size="icon" intent="quiet" aria-label="Previous page" disabled={result.page <= 1} onClick={() => setParams({ page: String(result.page - 1) })}><ChevronLeft className="size-4" aria-hidden="true" /></Button>
                <span className="tabular px-1">Page {result.page} of {result.pages}</span>
                <Button size="icon" intent="quiet" aria-label="Next page" disabled={result.page >= result.pages} onClick={() => setParams({ page: String(result.page + 1) })}><ChevronRight className="size-4" aria-hidden="true" /></Button>
              </span>
            </nav>
          ) : null}
        </>
      )}

      <SelectionBar count={selected.length} capNote={capNote} onClear={() => { selection.clear(); setCapNote(false); }}
        onReview={() => setReviewing(true)} disabledReason={preparing ? "A preparation is already in progress." : !session.canMutate ? "Available when DriveMind is reachable again." : null} />
      <FilePanel fileId={openFile} onClose={() => setParams({ file: null }, "replace")} />
      <ReviewSheet open={reviewing} onOpenChange={setReviewing} files={selectedFiles} onRemove={id => selection.remove(id)}
        onStarted={() => { setReviewing(false); selection.clear(); }} />
    </div>
  );
}

function SelectionBar({ count, capNote, onClear, onReview, disabledReason }: { count: number; capNote: boolean; onClear: () => void; onReview: () => void; disabledReason: string | null }) {
  return (
    <div aria-hidden={count === 0 || undefined} inert={count === 0 || undefined}
      className={cn("pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center px-3 pb-[max(1rem,env(safe-area-inset-bottom))] transition-[transform,opacity] duration-[220ms] ease-[var(--ease-out)] md:left-auto md:right-auto md:w-full",
        count ? "translate-y-0 opacity-100" : "translate-y-[calc(100%+1rem)] opacity-0")}>
      <div role="region" aria-label="Selection" className="float-layer pointer-events-auto flex w-full max-w-xl flex-wrap items-center gap-x-4 gap-y-2 rounded-panel border border-rule bg-sheet px-4 py-3">
        <p className="min-w-0 flex-1 text-label" aria-live="polite">
          <span className="font-medium tabular">{count} of {SELECTION_LIMIT}</span> selected
          {capNote ? <span className="block text-meta text-caution">Up to five documents per batch. Prepare these, then choose more.</span> : null}
          {disabledReason ? <span className="block text-meta text-graphite">{disabledReason}</span> : null}
        </p>
        <Button intent="quiet" size="sm" onClick={onClear}>Clear</Button>
        <Button intent="primary" onClick={onReview} disabled={!!disabledReason}>Review and prepare</Button>
      </div>
    </div>
  );
}

function ConnectCard() {
  const session = useApplicationSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="mt-4 max-w-lg rounded-panel border border-rule bg-sheet p-6">
      <h2 className="font-serif text-title font-medium">Connect Google Drive to see your files</h2>
      <p className="mt-2 text-body text-graphite">Google will ask for read-only access. DriveMind never edits, moves or deletes your files.</p>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button intent="primary" loading={busy} disabled={!session.canMutate} onClick={async () => {
          setBusy(true); setError(null);
          try { await session.connectDrive(); } catch (e) { setError((e as Error).message); setBusy(false); }
        }}>Connect Google Drive</Button>
        <Link href="/welcome" className="text-label text-graphite underline underline-offset-2">How setup works</Link>
      </div>
      {error ? <p role="alert" className="mt-3 text-label text-fault">{error}</p> : null}
    </div>
  );
}
