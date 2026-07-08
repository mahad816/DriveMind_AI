"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCcw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { listDriveFiles } from "@/lib/api/files";
import {
  buildVectorIndex,
  chunkDocuments,
  ingestDriveFiles,
  syncDriveMetadata,
} from "@/lib/api/indexing";
import { ApiError } from "@/lib/api/errors";
import { PipelineStepCard, type PipelineStepResultRow } from "@/components/indexing/pipeline-step-card";
import type {
  ChunkingResponse,
  DriveFileListResponse,
  DriveSyncResponse,
  DriveSyncStatusResponse,
  IndexBuildResponse,
  IngestionResponse,
} from "@/lib/api/types";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";

function apiErrorToMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Unexpected error";
}

function countFiles(files: DriveFileListResponse["files"]) {
  let indexed = 0;
  let failed = 0;
  let skipped = 0;

  for (const f of files) {
    if (f.status === "indexed") indexed += 1;
    if (f.status === "failed") failed += 1;
    if (f.status === "skipped") skipped += 1;
  }

  return { total: files.length, indexed, failed, skipped };
}

export function IndexingDashboard() {
  const { data: connection, error: connectionError, refetch } =
    useConnectionStatus({ pollIntervalMs: 30_000 });

  const isConnected = connection?.connected ?? false;

  const [filesState, setFilesState] = useState<{
    data: DriveFileListResponse | null;
    isLoading: boolean;
    error: string | null;
  }>({ data: null, isLoading: false, error: null });

  const refreshFiles = useCallback(async () => {
    if (!isConnected) return;
    setFilesState((s) => ({ ...s, isLoading: true, error: null }));
    try {
      const files = await listDriveFiles();
      setFilesState({ data: files, isLoading: false, error: null });
    } catch (err) {
      setFilesState({ data: null, isLoading: false, error: apiErrorToMessage(err) });
    }
  }, [isConnected]);

  useEffect(() => {
    void refreshFiles();
  }, [refreshFiles]);

  // Step state
  const [isBusy, setIsBusy] = useState(false);

  const [syncLoading, setSyncLoading] = useState(false);
  const [ingestLoading, setIngestLoading] = useState(false);
  const [chunkLoading, setChunkLoading] = useState(false);
  const [buildLoading, setBuildLoading] = useState(false);

  const [syncError, setSyncError] = useState<string | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [chunkError, setChunkError] = useState<string | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);

  const [syncResult, setSyncResult] = useState<DriveSyncResponse | null>(null);
  const [ingestResult, setIngestResult] = useState<IngestionResponse | null>(null);
  const [chunkResult, setChunkResult] = useState<ChunkingResponse | null>(null);
  const [buildResult, setBuildResult] = useState<IndexBuildResponse | null>(null);

  const jobStatusText = useMemo(() => {
    const job = (connection as DriveSyncStatusResponse | undefined)?.job;
    if (!job) return "No job yet";
    return `Last job: ${job.status}`;
  }, [connection]);

  const fileCounts = useMemo(() => {
    const files = filesState.data?.files ?? [];
    return countFiles(files);
  }, [filesState.data]);

  const isAnyStepLoading = isBusy || syncLoading || ingestLoading || chunkLoading || buildLoading;

  const disabledReason = !isConnected ? "Connect Drive first (Settings)." : null;

  const runStep = useCallback(
    async <TResponse,>(
      fn: () => Promise<TResponse>,
      opts: {
        setLoading: (v: boolean) => void;
        setError: (msg: string | null) => void;
        setResult: (res: TResponse) => void;
      },
    ) => {
      setIsBusy(true);
      opts.setLoading(true);
      opts.setError(null);

      try {
        const res = await fn();
        opts.setResult(res);

        // Keep UI consistent after each action.
        await refetch();
        await refreshFiles();
      } catch (err) {
        opts.setError(apiErrorToMessage(err));
      } finally {
        opts.setLoading(false);
        setIsBusy(false);
      }
    },
    [refetch, refreshFiles],
  );

  const syncRows: PipelineStepResultRow[] = useMemo(() => {
    if (!syncResult) return [];
    return [
      { label: "Created", value: syncResult.created },
      { label: "Updated", value: syncResult.updated },
      { label: "Unchanged", value: syncResult.unchanged },
      { label: "Removed", value: syncResult.removed },
    ];
  }, [syncResult]);

  const ingestRows: PipelineStepResultRow[] = useMemo(() => {
    if (!ingestResult) return [];
    return [
      { label: "Ingested", value: ingestResult.ingested },
      { label: "Unchanged", value: ingestResult.unchanged },
      { label: "Failed", value: ingestResult.failed },
      { label: "Skipped", value: ingestResult.skipped },
    ];
  }, [ingestResult]);

  const chunkRows: PipelineStepResultRow[] = useMemo(() => {
    if (!chunkResult) return [];
    return [
      { label: "Chunked", value: chunkResult.chunked },
      { label: "Unchanged", value: chunkResult.unchanged },
      { label: "Skipped", value: chunkResult.skipped },
      { label: "Total", value: chunkResult.total },
    ];
  }, [chunkResult]);

  const buildRows: PipelineStepResultRow[] = useMemo(() => {
    if (!buildResult) return [];
    return [
      { label: "Embedded", value: buildResult.embedded },
      { label: "Unchanged", value: buildResult.unchanged },
      { label: "Skipped", value: buildResult.skipped },
      { label: "Failed", value: buildResult.failed },
    ];
  }, [buildResult]);

  return (
    <PageContainer size="lg" className="max-w-7xl">
      <PageHeader
        title="Indexing"
        description="Sync Drive metadata and build the vector index used by chat."
      />

      {connectionError ? (
        <Alert variant="destructive">
          <AlertTitle>Connection status error</AlertTitle>
          <AlertDescription>{connectionError}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Index pipeline</CardTitle>
              <CardDescription>{jobStatusText}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-2">
                <PipelineStepCard
                  stepNumber={1}
                  title="Sync metadata"
                  description="Discover files and update Drive file metadata."
                  actionLabel="Run sync"
                  isConnected={isConnected}
                  isBusy={isAnyStepLoading}
                  isLoading={syncLoading}
                  disabledReason={disabledReason}
                  onRun={() =>
                    runStep(() => syncDriveMetadata(false), {
                      setLoading: setSyncLoading,
                      setError: setSyncError,
                      setResult: setSyncResult,
                    })
                  }
                  lastMessage={syncResult?.message ?? null}
                  resultRows={syncRows}
                  error={syncError}
                />

                <PipelineStepCard
                  stepNumber={2}
                  title="Extract text"
                  description="Ingest synced documents into extracted text chunks."
                  actionLabel="Run ingest"
                  isConnected={isConnected}
                  isBusy={isAnyStepLoading}
                  isLoading={ingestLoading}
                  disabledReason={disabledReason}
                  onRun={() =>
                    runStep(() => ingestDriveFiles(undefined), {
                      setLoading: setIngestLoading,
                      setError: setIngestError,
                      setResult: setIngestResult,
                    })
                  }
                  lastMessage={ingestResult?.message ?? null}
                  resultRows={ingestRows}
                  error={ingestError}
                />

                <PipelineStepCard
                  stepNumber={3}
                  title="Chunk"
                  description="Split extracted text into searchable segments."
                  actionLabel="Run chunk"
                  isConnected={isConnected}
                  isBusy={isAnyStepLoading}
                  isLoading={chunkLoading}
                  disabledReason={disabledReason}
                  onRun={() =>
                    runStep(() => chunkDocuments(undefined), {
                      setLoading: setChunkLoading,
                      setError: setChunkError,
                      setResult: setChunkResult,
                    })
                  }
                  lastMessage={chunkResult?.message ?? null}
                  resultRows={chunkRows}
                  error={chunkError}
                />

                <PipelineStepCard
                  stepNumber={4}
                  title="Build vectors"
                  description="Embed chunks and write vectors to Qdrant."
                  actionLabel="Run build"
                  isConnected={isConnected}
                  isBusy={isAnyStepLoading}
                  isLoading={buildLoading}
                  disabledReason={disabledReason}
                  onRun={() =>
                    runStep(() => buildVectorIndex(undefined), {
                      setLoading: setBuildLoading,
                      setError: setBuildError,
                      setResult: setBuildResult,
                    })
                  }
                  lastMessage={buildResult?.message ?? null}
                  resultRows={buildRows}
                  error={buildError}
                />
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Files summary</CardTitle>
              <CardDescription>
                Derived from <code className="rounded bg-muted px-1 py-0.5 text-xs">GET /files</code>.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <Badge variant="outline" className="text-xs font-normal">
                  Total: {filesState.data ? fileCounts.total : "—"}
                </Badge>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!isConnected || filesState.isLoading}
                  onClick={() => void refreshFiles()}
                >
                  {filesState.isLoading ? "Refreshing…" : null}
                  {!filesState.isLoading ? <RefreshCcw className="mr-2 size-4" /> : null}
                  Refresh
                </Button>
              </div>

              {filesState.error ? (
                <Alert variant="destructive">
                  <AlertTitle>Could not load files</AlertTitle>
                  <AlertDescription>{filesState.error}</AlertDescription>
                </Alert>
              ) : null}

              {filesState.isLoading && !filesState.data ? (
                <div className="space-y-2 text-sm text-muted-foreground">
                  Loading file metadata…
                </div>
              ) : null}

              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-border bg-card p-3 text-sm">
                  <p className="text-xs text-muted-foreground">Indexed</p>
                  <p className="text-lg font-semibold">{fileCounts.indexed}</p>
                </div>
                <div className="rounded-lg border border-border bg-card p-3 text-sm">
                  <p className="text-xs text-muted-foreground">Failed</p>
                  <p className="text-lg font-semibold">{fileCounts.failed}</p>
                </div>
                <div className="rounded-lg border border-border bg-card p-3 text-sm col-span-2">
                  <p className="text-xs text-muted-foreground">Skipped</p>
                  <p className="text-lg font-semibold">{fileCounts.skipped}</p>
                </div>
              </div>

              {!isConnected ? (
                <Alert className="border-amber-500/30 bg-amber-50 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
                  <AlertTitle>Drive not connected</AlertTitle>
                  <AlertDescription>
                    Open Settings and connect Google Drive, then sync metadata.
                  </AlertDescription>
                </Alert>
              ) : null}
            </CardContent>
          </Card>
        </div>
      </div>
    </PageContainer>
  );
}

