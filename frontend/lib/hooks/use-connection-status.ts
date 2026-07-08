"use client";

import { useCallback, useEffect, useState } from "react";

import { getDriveSyncStatus } from "@/lib/api/indexing";
import { isApiError } from "@/lib/api/errors";
import type { DriveSyncStatusResponse } from "@/lib/api/types";

const DEFAULT_POLL_INTERVAL_MS = 30_000;

type UseConnectionStatusOptions = {
  /** Poll interval in milliseconds. Set to 0 to disable polling. */
  pollIntervalMs?: number;
};

type ConnectionStatusState = {
  data: DriveSyncStatusResponse | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
};

export function useConnectionStatus(
  options: UseConnectionStatusOptions = {},
): ConnectionStatusState {
  const { pollIntervalMs = DEFAULT_POLL_INTERVAL_MS } = options;
  const [data, setData] = useState<DriveSyncStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    try {
      const status = await getDriveSyncStatus();
      setData(status);
      setError(null);
    } catch (err) {
      const message = isApiError(err)
        ? err.detail
        : err instanceof Error
          ? err.message
          : "Failed to load connection status";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  useEffect(() => {
    if (pollIntervalMs <= 0) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      void refetch();
    }, pollIntervalMs);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [pollIntervalMs, refetch]);

  return {
    data,
    isLoading,
    error,
    refetch,
  };
}
