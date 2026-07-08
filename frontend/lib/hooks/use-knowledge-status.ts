"use client";

import { useCallback, useEffect, useState } from "react";

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

  const isConnected = connection?.connected ?? false;

  const refresh = useCallback(async () => {
    setLastPreparedAtState(getLastPreparedAt());
    await refetchConnection();
  }, [refetchConnection]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!isConnected) {
      setFileStats(EMPTY_STATS);
      setFilesError(null);
      return;
    }

    let cancelled = false;

    async function loadFiles() {
      setFilesLoading(true);
      try {
        const response = await listDriveFiles();
        if (!cancelled) {
          setFileStats(countFiles(response.files));
          setFilesError(null);
        }
      } catch (err) {
        if (!cancelled) {
          const message = isApiError(err)
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Failed to load knowledge status";
          setFilesError(message);
        }
      } finally {
        if (!cancelled) {
          setFilesLoading(false);
        }
      }
    }

    void loadFiles();

    return () => {
      cancelled = true;
    };
  }, [isConnected]);

  const isReady = isConnected && fileStats.indexed > 0;
  const needsConnect = !isConnected;
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
