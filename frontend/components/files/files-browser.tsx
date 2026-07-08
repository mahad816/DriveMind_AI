"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCcw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { isApiError } from "@/lib/api/errors";
import {
  buildVectorIndex,
  chunkDocuments,
  ingestDriveFiles,
} from "@/lib/api/indexing";
import { listDriveFiles } from "@/lib/api/files";
import type { DriveFileListResponse, DriveFileStatus } from "@/lib/api/types";
import { FilesTable, type ReindexAction } from "@/components/files/files-table";

function apiErrorToMessage(err: unknown): string {
  if (isApiError(err)) {
    return err.detail;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Unexpected error";
}

type FilesBrowserProps = {
  className?: string;
};

type FilesLoadState = {
  data: DriveFileListResponse | null;
  isLoading: boolean;
  error: string | null;
};

export function FilesBrowser({ className }: FilesBrowserProps) {
  const { data: connection, error: connectionError } = useConnectionStatus({
    pollIntervalMs: 30_000,
  });

  const isConnected = connection?.connected ?? false;

  const [filesState, setFilesState] = useState<FilesLoadState>({
    data: null,
    isLoading: false,
    error: null,
  });

  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<DriveFileStatus | "all">("all");

  const [busyAction, setBusyAction] = useState<null | { fileId: string; action: ReindexAction }>(null);
  const [actionError, setActionError] = useState<string | null>(null);

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
    for (const f of files) {
      counts[f.status] += 1;
    }
    return counts;
  }, [files]);

  const filteredFiles = useMemo(() => {
    const q = query.trim().toLowerCase();
    let result = files;

    if (status !== "all") {
      result = result.filter((f) => f.status === status);
    }

    if (q) {
      result = result.filter((f) => {
        return (
          f.name.toLowerCase().includes(q) ||
          (f.folder_path ?? "").toLowerCase().includes(q) ||
          f.mime_type.toLowerCase().includes(q)
        );
      });
    }

    result = [...result].sort((a, b) => {
      const ad = new Date(a.modified_at).getTime();
      const bd = new Date(b.modified_at).getTime();
      return bd - ad;
    });

    return result;
  }, [files, query, status]);

  const statusPills: Array<{ value: DriveFileStatus | "all"; label: string; count?: number }> = [
    { value: "all", label: "All", count: filesState.data?.total ?? 0 },
    { value: "indexed", label: "Indexed", count: statusCounts.indexed },
    { value: "indexing", label: "Indexing", count: statusCounts.indexing },
    { value: "discovered", label: "Discovered", count: statusCounts.discovered },
    { value: "failed", label: "Failed", count: statusCounts.failed },
    { value: "skipped", label: "Skipped", count: statusCounts.skipped },
  ];

  const runAction = useCallback(
    async (fileId: string, action: ReindexAction) => {
      if (!isConnected) return;
      if (busyAction) return;

      setBusyAction({ fileId, action });
      setActionError(null);

      try {
        if (action === "ingest") {
          await ingestDriveFiles(fileId);
        } else if (action === "chunk") {
          await chunkDocuments(fileId);
        } else {
          await buildVectorIndex(fileId);
        }

        await refreshFiles();
      } catch (err) {
        setActionError(apiErrorToMessage(err));
      } finally {
        setBusyAction(null);
      }
    },
    [busyAction, isConnected, refreshFiles],
  );

  return (
    <div className={className}>
      {connectionError ? (
        <Alert variant="destructive">
          <AlertTitle>Connection status error</AlertTitle>
          <AlertDescription>{connectionError}</AlertDescription>
        </Alert>
      ) : null}

      {actionError ? (
        <Alert variant="destructive" className="mt-4">
          <AlertTitle>Action failed</AlertTitle>
          <AlertDescription>{actionError}</AlertDescription>
        </Alert>
      ) : null}

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base">Files list</CardTitle>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-xs font-normal">
                Total: {filesState.data?.total ?? "—"}
              </Badge>
              {busyAction ? (
                <Badge variant="outline" className="text-xs font-normal">
                  Running…
                </Badge>
              ) : null}
            </div>

            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!isConnected || filesState.isLoading}
                onClick={() => void refreshFiles()}
              >
                <RefreshCcw className="mr-2 size-4" />
                {filesState.isLoading ? "Refreshing…" : "Refresh"}
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">Search</label>
              <Input
                className="mt-1"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name, folder, or type…"
                disabled={!isConnected || filesState.isLoading}
              />
            </div>

            <div className="flex flex-wrap gap-2">
              {statusPills.map((pill) => {
                const active = status === pill.value;
                return (
                  <button
                    key={pill.value}
                    type="button"
                    onClick={() => setStatus(pill.value)}
                    disabled={!isConnected || filesState.isLoading}
                    className={[
                      "rounded-full border px-3 py-1 text-xs transition-colors",
                      active
                        ? "border-transparent bg-primary text-primary-foreground"
                        : "border-border bg-background text-muted-foreground hover:bg-muted",
                    ].join(" ")}
                  >
                    {pill.label}
                    {pill.count !== undefined ? ` (${pill.count})` : null}
                  </button>
                );
              })}
            </div>
          </div>

          {!isConnected ? (
            <Alert className="border-amber-500/30 bg-amber-50 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
              <AlertTitle>Drive not connected</AlertTitle>
              <AlertDescription>
                Connect Drive in Settings, then sync metadata in Index to populate this table.
              </AlertDescription>
            </Alert>
          ) : null}

          {filesState.error ? (
            <Alert variant="destructive">
              <AlertTitle>Could not load files</AlertTitle>
              <AlertDescription>{filesState.error}</AlertDescription>
            </Alert>
          ) : null}

          {filesState.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, idx) => (
                <Skeleton key={idx} className="h-10 w-full" />
              ))}
            </div>
          ) : null}

          {!filesState.isLoading && !filesState.error && files.length === 0 ? (
            <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
              No synced files found. Run <code className="rounded bg-muted px-1 py-0.5">Index → Sync</code>{" "}
              and try again.
            </div>
          ) : null}

          {!filesState.isLoading && files.length > 0 ? (
            <FilesTable
              files={filteredFiles}
              isConnected={isConnected}
              busyAction={busyAction}
              onRunAction={runAction}
            />
          ) : null}

          {!filesState.isLoading && files.length > 0 && filteredFiles.length === 0 ? (
            <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
              No results match your filters.
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

