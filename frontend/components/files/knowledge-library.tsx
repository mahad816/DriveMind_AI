"use client";

import { DEMO_MODE } from "@/lib/demo";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCcw, FolderOpen } from "lucide-react";

import { DriveDiscovery } from "@/components/files/drive-discovery";
import { EmptyState } from "@/components/shared/empty-state";
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

  const canBrowse = DEMO_MODE ? !connectionError && connection?.demo_mode === true : connection?.connected ?? false;
  const isDisconnected = !DEMO_MODE && connection?.connected === false && !connectionError;
  const connectionUnavailable = Boolean(connectionError) && !canBrowse;

  const [filesState, setFilesState] = useState<FilesLoadState>({
    data: null,
    isLoading: false,
    error: null,
  });

  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const [status, setStatus] = useState<DriveFileStatus | "all">("all");
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
    const clearDraft = () => { setDraft([]); setReviewing(false); setGate("blocked"); setFilesState({ data: null, isLoading: false, error: null }); };
    checkGate();
    const timer = window.setInterval(checkGate, 3000);
    window.addEventListener("storage", checkGate);
    window.addEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, clearDraft);
    return () => { clearInterval(timer); window.removeEventListener("storage", checkGate); window.removeEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, clearDraft); };
  }, [live, scope]);

  const refreshFiles = useCallback(async () => {
    if (!canBrowse) return;
    setFilesState({ data: null, isLoading: true, error: null });

    try {
      const list = await listDriveFiles();
      if (!live()) return;
      setFilesState({ data: list, isLoading: false, error: null });
    } catch (err) {
      if (!live()) return;
      setFilesState({ data: null, isLoading: false, error: apiErrorToMessage(err) });
    }
  }, [canBrowse, live]);

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
    if (window.matchMedia("(max-width: 767px)").matches) {
      setMobilePreviewOpen(true);
    }
  }, []);

  const filterPills: Array<{ value: DriveFileStatus | "all"; count?: number }> = [
    { value: "all", count: filesState.data?.total ?? 0 },
    { value: "indexed", count: statusCounts.indexed },
    { value: "indexing", count: statusCounts.indexing },
    { value: "discovered", count: statusCounts.discovered },
    { value: "failed", count: statusCounts.failed },
    { value: "skipped", count: statusCounts.skipped },
  ];

  const draftNeedsAttention = draft.some(selected => {
    const current = files.find(file => file.id === selected.id);
    return !current || current.user_id !== scope.owner || preparationEligibility(current) !== null || preparationFrame(current) !== preparationFrame(selected);
  });
  const togglePreparation = (file: DriveFileRead) => {
    if (!live() || !scope.owner || gate !== "empty") return;
    setDraft(before => before.some(f => f.id === file.id) ? before.filter(f => f.id !== file.id) :
      before.length < 5 && file.user_id === scope.owner && preparationEligibility(file) === null ? [...before, { ...file }] : before);
  };
  if (!DEMO_MODE && reviewing && scope.owner && live()) return <div key="preparation-review" className="min-h-0 min-w-0 md:flex-1 md:overflow-y-auto">
    <QueuePreparationView owner={scope.owner} draft={draft} onBack={reserved => { setReviewing(false); if (reserved) setDraft([]); void refreshFiles(); }} />
  </div>;

  return (
    <div className={cn("flex flex-col gap-6 md:min-h-0 md:flex-1", !DEMO_MODE && "md:overflow-y-auto", className)}>
      {!DEMO_MODE ? <DriveDiscovery onComplete={() => { void refreshFiles(); void refreshConnection(); }} /> : null}
      {!DEMO_MODE ? <div className="space-y-1">
        <Link href="/prepare" className="inline-flex min-h-11 items-center self-start text-sm underline underline-offset-4">{gate === "queue" || gate === "legacy" ? "Review existing preparation" : "View preparation progress"}</Link>
        {gate !== "empty" && gate !== "checking" ? <p className="text-sm text-muted-foreground">{gate === "blocked" ? "Saved preparation could not be verified. Review progress before starting new work." : "Resolve or close existing preparation before preparing another selection."}</p> : null}
      </div> : null}
      {!DEMO_MODE && scope.owner ? <section aria-label="Preparation selection" className="space-y-2 border-y border-border py-3">
        <p role="status" className="text-sm">{draft.length} of 5 documents selected</p>
        {draft.length === 5 ? <p className="text-sm text-muted-foreground">Five-document limit reached. Remove one to choose another.</p> : null}
        {draft.length ? <ol aria-label="Selected documents" className="space-y-1">
          {draft.map((selected, index) => {
            const current = files.find(f => f.id === selected.id);
            const changed = !current || preparationEligibility(current) !== null || preparationFrame(current) !== preparationFrame(selected);
            return <li key={selected.id} className="flex min-w-0 items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 break-words [overflow-wrap:anywhere]">{index + 1}. {selected.name}{changed && !filesState.isLoading ? " · Needs attention" : ""}</span>
              <Button variant="ghost" className="min-h-11 shrink-0" aria-label={`Remove ${selected.name} from selection`} onClick={() => setDraft(before => before.filter(f => f.id !== selected.id))}>Remove</Button>
            </li>;
          })}
        </ol> : <p className="text-sm text-muted-foreground">Choose up to five eligible documents using the checkboxes. Click a filename to preview it.</p>}
        {draftNeedsAttention && draft.length && !filesState.isLoading ? <p role="alert" className="text-sm">A selected document changed or is no longer eligible. Remove it and review your selection.</p> : null}
        {draft.length ? <Button disabled={gate !== "empty" || !canBrowse || filesState.isLoading || !!filesState.error || draftNeedsAttention} onClick={() => setReviewing(true)}>Review {draft.length} {draft.length === 1 ? "document" : "documents"}</Button> : null}
      </section> : null}
      <div className="flex flex-col gap-3 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
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
            {filesState.isLoading ? "Refreshing…" : DEMO_MODE ? "Refresh" : "Reload file list"}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-border pb-4" role="group" aria-label="Filter files by status">
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

      {canBrowse && connectionError ? (
        <Alert variant="destructive">
          <AlertTitle>Connection status unavailable</AlertTitle>
          <AlertDescription>{connectionError}</AlertDescription>
        </Alert>
      ) : null}

      {isDisconnected ? (
        <EmptyState
          title={filesCopy.notConnectedTitle}
          description={filesCopy.notConnectedBody}
          actionLabel="Connect in Settings"
          actionHref="/settings"
          icon={FolderOpen}
        />
      ) : null}

      {!connection && connectionLoading && !connectionError ? (
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

      {canBrowse && filesState.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-14 w-full rounded-md" />
          ))}
        </div>
      ) : null}

      {canBrowse && !filesState.isLoading && !filesState.error && files.length === 0 ? (
        <EmptyState
          title={DEMO_MODE ? "Sample corpus unavailable" : "No discovered files"}
          description={DEMO_MODE ? "The demo operator must prepare the controlled corpus offline." : "Check Drive for files above. If a check has completed, no supported documents were found. Supported types include Google Docs, TXT, PDF, DOCX and images; scanned PDFs have no OCR fallback."}
          actionLabel={undefined}
          actionHref="/index"
          icon={FolderOpen}
        />
      ) : null}

      {canBrowse && !filesState.isLoading && files.length > 0 && filteredFiles.length === 0 ? (
        <EmptyState title={filesCopy.noResults} />
      ) : null}

      {canBrowse && !filesState.isLoading && filteredFiles.length > 0 ? (
        <div className="grid min-w-0 grid-cols-1 gap-4 md:min-h-0 md:flex-1 md:grid-cols-5 md:gap-6">
          <div className="min-w-0 md:col-span-2 md:min-h-0 md:overflow-y-auto md:overscroll-contain">
            <FileList
              files={filteredFiles}
              selectedId={selectedId}
              onSelect={handleSelect}
              preparation={DEMO_MODE ? undefined : { selected: draft.map(f => f.id), disabled: gate !== "empty" || !live(), onToggle: togglePreparation }}
            />
          </div>
          <div className="hidden md:col-span-3 md:block md:min-h-0">
            <FilePreviewPanel file={selectedFile} className="md:min-h-0" />
          </div>
        </div>
      ) : null}

      <FilePreviewSheet
        file={selectedFile}
        open={mobilePreviewOpen}
        onOpenChange={setMobilePreviewOpen}
      />
    </div>
  );
}
