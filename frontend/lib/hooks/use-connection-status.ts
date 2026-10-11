"use client";

import { useSharedConnectionStatus } from "@/components/providers/connection-status-provider";

type UseConnectionStatusOptions = {
  /** Poll interval in milliseconds. Set to 0 to disable polling. */
  pollIntervalMs?: number;
};

export function useConnectionStatus(options: UseConnectionStatusOptions = {}) {
  return useSharedConnectionStatus(options.pollIntervalMs ?? 30_000);
}
