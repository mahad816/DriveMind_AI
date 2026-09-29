"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCcw, FolderOpen } from "lucide-react";

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

  const isConnected = connection?.connected ?? false;
  const isDisconnected = connection?.connected === false && !connectionError;
  const connectionUnavailable = Boolean(connectionError) && !isConnected;

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

  const refreshFiles = useCallback(async () => {
    if (!isConnected) return;
    setFilesState({ data: null, isLoading: true, error: null });

    try {
      const list = await listDriveFiles();
      setFilesState({ data: list, isLoading: false, error: null });
    } catch (err) {
      setFilesState({ data: null, isLoading: false, error: apiErrorToMessage(err) });
    }
  }, [isConnected]);

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

  return (
    <div className={cn("flex flex-col gap-6 md:min-h-0 md:flex-1", className)}>
      <div className="flex flex-col gap-3 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
        <p className="text-sm tabular-nums text-muted-foreground" role="status">
          {filesState.data ? `${filesState.data.total} ${filesCopy.fileCount}` :
            connectionLoading || (isConnected && filesState.isLoading) ? "Loading files…" : "Browse Drive files"}
        </p>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={filesCopy.searchPlaceholder}
            disabled={!isConnected || filesState.isLoading}
            className="h-9 sm:w-72"
            aria-label="Search files"
          />
          <Button
            type="button"
            variant="outline"
            size="default"
            disabled={!isConnected || filesState.isLoading}
            onClick={() => void refreshFiles()}
          >
            <RefreshCcw className="size-4" />
            {filesState.isLoading ? "Refreshing…" : "Refresh"}
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
              disabled={!isConnected || filesState.isLoading}
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
          <AlertTitle>Couldn’t check your Drive connection</AlertTitle>
          <AlertDescription>
            {connectionError}
            <Button type="button" variant="outline" size="sm" className="mt-3 flex" onClick={() => void refreshConnection()}>
              Retry connection check
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {isConnected && connectionError ? (
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
        <p className="py-8 text-sm text-muted-foreground" role="status">Checking your Drive connection…</p>
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

      {isConnected && filesState.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-14 w-full rounded-md" />
          ))}
        </div>
      ) : null}

      {isConnected && !filesState.isLoading && !filesState.error && files.length === 0 ? (
        <EmptyState
          title={filesCopy.emptyTitle}
          description={filesCopy.emptyBody}
          actionLabel={filesCopy.emptyCta}
          actionHref="/index"
          icon={FolderOpen}
        />
      ) : null}

      {isConnected && !filesState.isLoading && files.length > 0 && filteredFiles.length === 0 ? (
        <EmptyState title={filesCopy.noResults} />
      ) : null}

      {isConnected && !filesState.isLoading && filteredFiles.length > 0 ? (
        <div className="grid min-w-0 grid-cols-1 gap-4 md:min-h-0 md:flex-1 md:grid-cols-5 md:gap-6">
          <div className="min-w-0 md:col-span-2 md:min-h-0 md:overflow-y-auto md:overscroll-contain">
            <FileList
              files={filteredFiles}
              selectedId={selectedId}
              onSelect={handleSelect}
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
