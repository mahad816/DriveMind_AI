"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { listDriveFiles } from "@/lib/api/files";
import { isApiError } from "@/lib/api/errors";
import { formatLastPreparedAt, getLastPreparedAt } from "@/lib/knowledge/storage";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";

export type SetupState =
  | "checking"
  | "not_connected"
  | "connected_not_ready"
  | "preparing"
  | "ready"
  | "error";

type KnowledgeFileStats = {
  total: number;
  indexed: number;
  failed: number;
  skipped: number;
};

type UseKnowledgeStatusResult = {
  setupState: SetupState;
  jobError: string | null;
  isLoading: boolean;
  error: string | null;
  isConnected: boolean;
  isReady: boolean;
  needsConnect: boolean;
  needsPrepare: boolean;
  fileStats: KnowledgeFileStats;
  lastPreparedAt: string | null;
  lastPreparedLabel: string | null;
  refresh: () => Promise<void>;
};

const EMPTY_STATS: KnowledgeFileStats = {
  total: 0,
  indexed: 0,
  failed: 0,
  skipped: 0,
};

function countFiles(files: Awaited<ReturnType<typeof listDriveFiles>>["files"]): KnowledgeFileStats {
  let indexed = 0;
  let failed = 0;
  let skipped = 0;

  for (const file of files) {
    if (file.status === "indexed") indexed += 1;
    if (file.status === "failed") failed += 1;
    if (file.status === "skipped") skipped += 1;
  }

  return { total: files.length, indexed, failed, skipped };
}

export function useKnowledgeStatus(
  options: { pollIntervalMs?: number } = {},
): UseKnowledgeStatusResult {
  const { pollIntervalMs = 30_000 } = options;
  const {
    data: connection,
    isLoading: connectionLoading,
    error: connectionError,
    refetch: refetchConnection,
  } = useConnectionStatus({ pollIntervalMs });

  const [fileStats, setFileStats] = useState<KnowledgeFileStats>(EMPTY_STATS);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesLoaded, setFilesLoaded] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [lastPreparedAt, setLastPreparedAtState] = useState<string | null>(null);
  const fileRequestId = useRef(0);

  const isConnected = !connectionError && (connection?.connected ?? false);

  const loadFiles = useCallback(async () => {
    const requestId = ++fileRequestId.current;
    setFilesLoading(true);
    try {
      const response = await listDriveFiles();
      if (requestId === fileRequestId.current) {
        setFileStats(countFiles(response.files));
        setFilesError(null);
      }
    } catch (err) {
      if (requestId === fileRequestId.current) {
        const message = isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Failed to load knowledge status";
        setFilesError(message);
      }
    } finally {
      if (requestId === fileRequestId.current) {
        setFilesLoaded(true);
        setFilesLoading(false);
      }
    }
  }, []);

  const refresh = useCallback(async () => {
    setLastPreparedAtState(getLastPreparedAt());
    await Promise.all([refetchConnection(), isConnected ? loadFiles() : Promise.resolve()]);
  }, [isConnected, loadFiles, refetchConnection]);

  useEffect(() => {
    setLastPreparedAtState(getLastPreparedAt());
  }, []);

  useEffect(() => {
    if (isConnected) {
      void loadFiles();
    } else {
      fileRequestId.current += 1;
      setFilesLoaded(false);
      setFileStats(EMPTY_STATS);
      setFilesError(null);
      setFilesLoading(false);
    }
    return () => {
      fileRequestId.current += 1;
    };
  }, [isConnected, loadFiles]);

  const isReady = isConnected && !filesError && filesLoaded && fileStats.indexed > 0;
  const needsConnect = !connectionError && connection?.connected === false;
  const needsPrepare = isConnected && filesLoaded && !filesError && fileStats.indexed === 0;
  const job = connection?.job;
  const setupState: SetupState = connectionError || filesError
    ? "error"
    : connectionLoading && !connection
      ? "checking"
      : !connection
        ? "checking"
        : !connection.connected
          ? "not_connected"
          : job?.status === "queued" || job?.status === "running"
            ? "preparing"
            : !filesLoaded
              ? "checking"
              : isReady
                ? "ready"
                : "connected_not_ready";

  return {
    setupState,
    jobError: job?.status === "failed" ? job.error : null,
    isLoading: connectionLoading || (isConnected && !filesLoaded) || filesLoading,
    error: connectionError ?? filesError,
    isConnected,
    isReady,
    needsConnect,
    needsPrepare,
    fileStats,
    lastPreparedAt,
    lastPreparedLabel: formatLastPreparedAt(lastPreparedAt),
    refresh,
  };
}
