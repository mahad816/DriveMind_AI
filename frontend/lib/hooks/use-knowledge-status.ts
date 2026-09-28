"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { listDriveFiles } from "@/lib/api/files";
import { isApiError } from "@/lib/api/errors";
import { formatLastPreparedAt, getLastPreparedAt } from "@/lib/knowledge/storage";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";

type KnowledgeFileStats = {
  total: number;
  indexed: number;
  failed: number;
  skipped: number;
};

type UseKnowledgeStatusResult = {
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
      if (requestId === fileRequestId.current) setFilesLoading(false);
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
      setFileStats(EMPTY_STATS);
      setFilesError(null);
      setFilesLoading(false);
    }
    return () => {
      fileRequestId.current += 1;
    };
  }, [isConnected, loadFiles]);

  const isReady = isConnected && fileStats.indexed > 0;
  const needsConnect = !connectionError && connection?.connected === false;
  const needsPrepare = isConnected && fileStats.indexed === 0;

  return {
    isLoading: connectionLoading || filesLoading,
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
