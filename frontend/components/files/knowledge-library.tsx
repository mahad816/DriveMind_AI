"use client";

import { DEMO_MODE } from "@/lib/demo";

import { useCallback, useEffect, useMemo, useState, useRef, useId } from "react";
import { RefreshCcw, FolderOpen, Search, ArrowRight, ChevronLeft, ChevronRight, X } from "lucide-react";

import { DriveDiscovery } from "@/components/files/drive-discovery";
import { EmptyState } from "@/components/shared/empty-state";
import { FilesTable } from "@/components/files/files-table";
import { FileList } from "@/components/files/file-list";
import { FilePreviewPanel } from "@/components/files/file-preview-panel";
import { FilePreviewSheet } from "@/components/files/file-preview-sheet";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { isApiError } from "@/lib/api/errors";
import { listDriveFiles } from "@/lib/api/files";
import type { DriveFileListResponse, DriveFileRead, DriveFileStatus } from "@/lib/api/types";
import { fileFilterLabel, filesCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { preparationEligibility, preparationFrame } from "@/lib/knowledge/single-file-preparation";
import { readPreparationGate } from "@/lib/knowledge/preparation-queue-store";
import { sessionOwner, sessionRevision, SESSION_REQUESTS_INVALIDATED_EVENT } from "@/lib/api/session-events";
import { QueuePreparationView } from "@/components/knowledge/queue-preparation-view";

function apiErrorToMessage(err: unknown): string {
  if (isApiError(err)) return err.detail;
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}

type KnowledgeLibraryProps = {
  className?: string;
};

type FilesLoadState = {
  data: DriveFileListResponse | null;
  isLoading: boolean;
  error: string | null;
};

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}

export function KnowledgeLibrary({ className }: KnowledgeLibraryProps) {
  const { data: connection, isLoading: connectionLoading, error: connectionError, refetch: refreshConnection } = useConnectionStatus({
    pollIntervalMs: 30_000,
  });

  const canBrowse = DEMO_MODE ? !connectionError && connection?.demo_mode === true : Boolean(sessionOwner());
  const isDisconnected = !DEMO_MODE && connection?.connected === false && !connectionError;
  const connectionUnavailable = Boolean(connectionError) && (!DEMO_MODE || !canBrowse);

  const [filesState, setFilesState] = useState<FilesLoadState>({
    data: null,
    isLoading: false,
    error: null,
  });

  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const [status, setStatus] = useState<DriveFileStatus | "all">("all");
  const [page, setPage] = useState(0);
  const tabsId = useId();
  const reviewButton = useRef<HTMLButtonElement>(null);
  const filesHeading = useRef<HTMLHeadingElement>(null);
  const focusAfterReview = useRef(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobilePreviewOpen, setMobilePreviewOpen] = useState(false);
  const [scope] = useState(() => ({ owner: sessionOwner(), revision: sessionRevision() }));
  const [draft, setDraft] = useState<DriveFileRead[]>([]);
  const [reviewing, setReviewing] = useState(false);
  const [gate, setGate] = useState("checking");
  const live = useCallback(() => scope.owner === sessionOwner() && scope.revision === sessionRevision(), [scope]);
  useEffect(() => {
    if (DEMO_MODE) return;
    const checkGate = () => {
      if (!live()) return;
      try { setGate(scope.owner ? readPreparationGate(scope.owner).kind : "blocked"); }
      catch { setGate("blocked"); }
    };
    const clearDraft = () => { setSelectedId(null); setMobilePreviewOpen(false); setDraft([]); setReviewing(false); setGate("blocked"); setFilesState({ data: null, isLoading: false, error: null }); };
    checkGate();
    const timer = window.setInterval(checkGate, 3000);
    window.addEventListener("storage", checkGate);
    window.addEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, clearDraft);
    return () => { clearInterval(timer); window.removeEventListener("storage", checkGate); window.removeEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, clearDraft); };
  }, [live, scope]);

  const filesRequest = useRef(0);
  const refreshFiles = useCallback(async () => {
    if (!canBrowse) return;
    const request = ++filesRequest.current;
    setFilesState(before => ({ data: DEMO_MODE ? null : before.data, isLoading: true, error: null }));

    try {
      const list = await listDriveFiles();
      if (!live() || request !== filesRequest.current) return;
      if (!DEMO_MODE && list.files.some(file => file.user_id !== scope.owner)) throw new Error("File ownership could not be verified.");
      setFilesState({ data: list, isLoading: false, error: null });
    } catch (err) {
      if (!live() || request !== filesRequest.current) return;
      setFilesState({ data: null, isLoading: false, error: apiErrorToMessage(err) });
    }
  }, [canBrowse, live, scope.owner]);

  useEffect(() => {
    void refreshFiles();
  }, [refreshFiles]);

  const files = useMemo(() => filesState.data?.files ?? [], [filesState.data]);

  const statusCounts = useMemo(() => {
    const counts: Record<DriveFileStatus, number> = {
      discovered: 0,
      indexing: 0,
      indexed: 0,
      failed: 0,
      skipped: 0,
    };
    for (const file of files) {
      counts[file.status] += 1;
    }
    return counts;
  }, [files]);

  const filteredFiles = useMemo(() => {
    const q = debouncedQuery.trim().toLowerCase();
    let result = files;

    if (status !== "all") {
      result = result.filter((file) => file.status === status);
    }

    if (q) {
      result = result.filter((file) => {
        return (
          file.name.toLowerCase().includes(q) ||
          (file.folder_path ?? "").toLowerCase().includes(q)
        );
      });
    }

    return [...result].sort(
      (a, b) => new Date(b.modified_at).getTime() - new Date(a.modified_at).getTime(),
    );
  }, [debouncedQuery, files, status]);

  const selectedFile = useMemo(
    () => files.find((file) => file.id === selectedId) ?? null,
    [files, selectedId],
  );

  useEffect(() => {
    if (!DEMO_MODE) return;
    if (filteredFiles.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !filteredFiles.some((file) => file.id === selectedId)) {
      setSelectedId(filteredFiles[0]?.id ?? null);
    }
  }, [filteredFiles, selectedId]);

  const handleSelect = useCallback((file: DriveFileRead) => {
    setSelectedId(file.id);
    if (!DEMO_MODE || window.matchMedia("(max-width: 767px)").matches) {
      setMobilePreviewOpen(true);
    }
  }, []);

  const filterPills: Array<{ value: DriveFileStatus | "all"; label: string; count: number }> = DEMO_MODE ? [
    { value: "all", label: "All", count: filesState.data?.total ?? 0 },
    ...(["indexed", "indexing", "discovered", "failed", "skipped"] as const).map(value => ({ value, label: fileFilterLabel[value], count: statusCounts[value] })),
  ] : [
    { value: "discovered", label: "To prepare", count: statusCounts.discovered },
    { value: "indexed", label: "Ready", count: statusCounts.indexed },
    { value: "indexing", label: "Preparing", count: statusCounts.indexing },
    { value: "all", label: "All", count: filesState.data?.total ?? 0 },
  ];
  const pageSize = 12;
  const lastPage = Math.max(0, Math.ceil(filteredFiles.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const pageFiles = filteredFiles.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  const hiddenSelections = draft.filter(file => !pageFiles.some(row => row.id === file.id)).length;
  const selectionDisabled = gate !== "empty" || !live() || !connection?.connected || !!connectionError || filesState.isLoading || !!filesState.error;
  const selectionDisabledReason = !connection?.connected || connectionError ? "Check Drive access before selecting documents for preparation." : "Check file inventory and existing preparation before making another selection.";

  const draftNeedsAttention = draft.some(selected => {
    const current = files.find(file => file.id === selected.id);
    return !current || current.user_id !== scope.owner || preparationEligibility(current) !== null || preparationFrame(current) !== preparationFrame(selected);
  });
  useEffect(() => {
    if (reviewing || filesState.isLoading || !focusAfterReview.current) return;
    focusAfterReview.current = false;
    const destination = reviewButton.current;
    if (destination && !destination.disabled) destination.focus();
    else filesHeading.current?.focus();
  }, [reviewing, filesState.isLoading]);
  const togglePreparation = (file: DriveFileRead) => {
    if (!live() || !scope.owner || gate !== "empty" || !connection?.connected || connectionError || filesState.isLoading || filesState.error) return;
    setDraft(before => before.some(f => f.id === file.id) ? before.filter(f => f.id !== file.id) :
      before.length < 5 && file.user_id === scope.owner && preparationEligibility(file) === null ? [...before, { ...file }] : before);
  };
  if (!DEMO_MODE && reviewing && scope.owner && live()) return <div key="preparation-review" className="min-h-0 min-w-0 md:flex-1 md:overflow-y-auto">
    <QueuePreparationView owner={scope.owner} draft={draft} onRemove={id => setDraft(before => before.filter(file => file.id !== id))} onBack={reserved => { focusAfterReview.current = true; setReviewing(false); if (reserved) setDraft([]); void refreshFiles(); }} />
  </div>;

  return (
    <div className={cn("flex flex-col md:min-h-0 md:flex-1", DEMO_MODE ? "gap-6" : "files-library", className)}>
      {!DEMO_MODE ? <header className="files-page-header"><div><h1 ref={filesHeading} tabIndex={-1} className="editorial-display">Files</h1><p>Your Drive documents, ready to become knowledge.</p></div><DriveDiscovery filesHeader onComplete={() => { void refreshFiles(); void refreshConnection(); }} /></header> : null}
      {!DEMO_MODE && ["queue", "legacy", "blocked"].includes(gate) ? <div className="space-y-1">
        <Link href="/prepare" className="inline-flex min-h-11 items-center self-start text-sm underline underline-offset-4">{gate === "queue" || gate === "legacy" ? "Review existing preparation" : "View preparation progress"}</Link>
        {gate !== "empty" && gate !== "checking" ? <p className="text-sm text-muted-foreground">{gate === "blocked" ? "Saved preparation could not be verified. Review progress before starting new work." : "Resolve or close existing preparation before preparing another selection."}</p> : null}
      </div> : null}

      {DEMO_MODE ? <>
      <div className={cn("flex flex-col sm:flex-row sm:justify-between", DEMO_MODE ? "gap-3 border-b border-border pb-5 sm:items-end" : "gap-2 py-1 sm:items-center")}>
        <p className="text-sm tabular-nums text-muted-foreground" role="status">
          {filesState.data ? `${filesState.data.total} ${filesCopy.fileCount}` :
            connectionLoading || (canBrowse && filesState.isLoading) ? "Loading files…" : DEMO_MODE ? "Browse sample files" : "Browse Drive files"}
        </p>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={filesCopy.searchPlaceholder}
            disabled={!canBrowse || filesState.isLoading}
            className="h-9 sm:w-72"
            aria-label="Search files"
          />
          <Button
            type="button"
            variant="outline"
            size="default"
            disabled={!canBrowse || filesState.isLoading}
            onClick={() => void refreshFiles()}
          >
            <RefreshCcw className="size-4" />
            {filesState.isLoading ? "Refreshing…" : DEMO_MODE ? "Refresh" : "Refresh list"}
          </Button>
        </div>
      </div>

      <div className={cn("flex flex-wrap gap-1 border-b border-border", DEMO_MODE ? "pb-4" : "pb-1")} role="group" aria-label="Filter files by status">
        {filterPills.map((pill) => {
          const active = status === pill.value;
          return (
            <button
              key={pill.value}
              type="button"
              aria-pressed={active}
              onClick={() => setStatus(pill.value)}
              disabled={!canBrowse || filesState.isLoading}
              className={cn(
                "rounded-md border px-2.5 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active
                  ? "border-primary/30 bg-accent font-medium text-accent-foreground"
                  : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {fileFilterLabel[pill.value]}
              {pill.count !== undefined ? ` (${pill.count})` : null}
            </button>
          );
        })}
      </div>

      </> : <>
      <div className="files-toolbar">
        <div role="tablist" aria-label="Filter files by status" className="files-tabs">
          {filterPills.map((pill, index) => <button key={pill.value} id={`${tabsId}-${pill.value}`} type="button" role="tab"
            aria-selected={status === pill.value} aria-controls={`${tabsId}-panel`} tabIndex={status === pill.value ? 0 : -1}
            disabled={!canBrowse || filesState.isLoading}
            onClick={() => { setStatus(pill.value); setPage(0); }}
            onKeyDown={event => {
              const next = event.key === "ArrowRight" ? (index + 1) % filterPills.length : event.key === "ArrowLeft" ? (index + filterPills.length - 1) % filterPills.length : event.key === "Home" ? 0 : event.key === "End" ? filterPills.length - 1 : null;
              if (next === null) return;
              event.preventDefault(); setStatus(filterPills[next].value); setPage(0);
              document.getElementById(`${tabsId}-${filterPills[next].value}`)?.focus();
            }}>
            {pill.label} <span>{filesState.data ? `(${pill.count})` : "—"}</span>
          </button>)}
        </div>
        <div className="files-search-actions">
          <div className="files-search"><Search aria-hidden="true" className="size-3.5" /><Input value={query}
            onChange={event => { setQuery(event.target.value); setPage(0); }} placeholder={filesCopy.searchPlaceholder}
            disabled={!canBrowse || filesState.isLoading} aria-label="Search files" />
            {query && <Button variant="ghost" size="icon-sm" aria-label="Clear file search" onClick={() => { setQuery(""); setPage(0); }}><X className="size-3.5" /></Button>}
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Refresh list" title="Refresh stored file metadata" disabled={!canBrowse || filesState.isLoading} onClick={() => void refreshFiles()}><RefreshCcw className="size-3.5" /></Button>
        </div>
      </div>
      </>}
      {!DEMO_MODE && canBrowse && filesState.isLoading ? <p role="status" className="text-xs text-muted-foreground">Loading files…</p> : null}
      {!DEMO_MODE && scope.owner && draft.length > 0 ? <section aria-label="Preparation selection" className="files-selection">
        <div><p role="status">{draft.length} of 5 documents selected</p>{hiddenSelections > 0 && <p className="text-xs text-muted-foreground">{hiddenSelections} selected {hiddenSelections === 1 ? "document is" : "documents are"} hidden by search, filter or pagination.</p>}</div>
        <div className="files-selection-actions"><Button variant="ghost" onClick={() => setDraft([])}>Clear selection</Button><Button ref={reviewButton}
          disabled={selectionDisabled || draftNeedsAttention} onClick={() => setReviewing(true)}>Review {draft.length} {draft.length === 1 ? "document" : "documents"}<ArrowRight className="size-3.5" /></Button></div>
        {draft.length === 5 && <p className="files-selection-note">Five-document limit reached. Remove one to choose another.</p>}
        {draftNeedsAttention && !filesState.isLoading && <div className="files-selection-note"><p role="alert">A selected document changed or is no longer eligible. Remove it and review your selection.</p>{draft.map(file => <Button key={file.id} variant="ghost" aria-label={`Remove ${file.name} from selection`} onClick={() => setDraft(before => before.filter(row => row.id !== file.id))}>Remove {file.name}</Button>)}</div>}
      </section> : null}

      {connectionUnavailable ? (
        <Alert variant="destructive">
          <AlertTitle>{DEMO_MODE ? "Sample status unavailable" : "Couldn’t check your Drive connection"}</AlertTitle>
          <AlertDescription>
            {connectionError}
            <Button type="button" variant="outline" size="sm" className="mt-3 flex" onClick={() => void refreshConnection()}>
              Retry connection check
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {DEMO_MODE && canBrowse && connectionError ? (
        <Alert variant="destructive">
          <AlertTitle>Connection status unavailable</AlertTitle>
          <AlertDescription>{connectionError}</AlertDescription>
        </Alert>
      ) : null}

      {isDisconnected ? <p className="text-sm leading-6 text-muted-foreground">Reconnect Drive to discover or prepare more documents. Stored file details and prepared knowledge remain available. <Link href="/onboarding" className="underline underline-offset-4">Connect Google Drive</Link>{statusCounts.indexed > 0 ? <> · <Link href="/chat" className="underline underline-offset-4">Open chat</Link></> : null}</p> : null}

      {!connection && connectionLoading && !connectionError && !canBrowse ? (
        <p className="py-8 text-sm text-muted-foreground" role="status">{DEMO_MODE ? "Checking sample index…" : "Checking your Drive connection…"}</p>
      ) : null}

      {filesState.error ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load files</AlertTitle>
          <AlertDescription>
            {filesState.error}
            <Button type="button" variant="outline" size="sm" className="mt-3 flex" onClick={() => void refreshFiles()}>
              Retry loading files
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {canBrowse && filesState.isLoading && !filesState.data ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-14 w-full rounded-md" />
          ))}
        </div>
      ) : null}

      {canBrowse && !filesState.isLoading && !filesState.error && files.length === 0 ? (
        <EmptyState
          title={DEMO_MODE ? "Sample corpus unavailable" : "No discovered files"}
          description={DEMO_MODE ? "The demo operator must prepare the controlled corpus offline." : "Check for files to discover Google Docs, TXT, PDF, DOCX and images. Scanned PDFs have no OCR fallback."}
          actionLabel={undefined}
          actionHref="/index"
          icon={FolderOpen}
        />
      ) : null}

      {DEMO_MODE && canBrowse && !filesState.isLoading && files.length > 0 && filteredFiles.length === 0 ? (
        <EmptyState title={filesCopy.noResults} />
      ) : null}

      {canBrowse && !DEMO_MODE && files.length > 0 && !filesState.error ? <section id={`${tabsId}-panel`} role="tabpanel" aria-labelledby={`${tabsId}-${status}`} className="files-list-panel" aria-busy={filesState.isLoading}>
        <FilesTable files={pageFiles} selected={draft.map(file => file.id)} owner={scope.owner} disabled={selectionDisabled}
          disabledReason={selectionDisabledReason} onToggle={togglePreparation} onPreview={handleSelect} />
        {!filesState.isLoading && !filteredFiles.length && <EmptyState title={filesCopy.noResults} />}
        <footer className="files-pagination"><span>{filteredFiles.length ? `${currentPage * pageSize + 1}–${Math.min((currentPage + 1) * pageSize, filteredFiles.length)} of ${filteredFiles.length} documents` : "0 documents"}</span>
          <div><Button variant="ghost" size="icon-sm" aria-label="Previous page" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><ChevronLeft className="size-4" /></Button><span>{currentPage + 1} / {lastPage + 1}</span><Button variant="ghost" size="icon-sm" aria-label="Next page" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}><ChevronRight className="size-4" /></Button></div>
        </footer>
      </section> : null}
      {!DEMO_MODE && <p className="files-footnote">Only documents you prepare become searchable. Open a filename to preview its details.</p>}
      {canBrowse && DEMO_MODE && !filesState.isLoading && filteredFiles.length > 0 ? <div id={`${tabsId}-panel`} role="tabpanel" aria-labelledby={`${tabsId}-${status}`} className="grid min-w-0 grid-cols-1 gap-4 md:min-h-0 md:flex-1 md:grid-cols-5 md:gap-6">
        <div className="min-w-0 md:col-span-2 md:min-h-0 md:overflow-y-auto"><FileList files={filteredFiles} selectedId={selectedId} onSelect={handleSelect} /></div>
        <div className="hidden md:block md:col-span-3 md:min-h-0"><FilePreviewPanel file={selectedFile} className="md:min-h-0" /></div>
      </div> : null}

      <FilePreviewSheet
        canPrepare={connection?.connected === true && !connectionError}
        file={selectedFile}
        open={mobilePreviewOpen}
        onOpenChange={setMobilePreviewOpen}
      />
    </div>
  );
}
