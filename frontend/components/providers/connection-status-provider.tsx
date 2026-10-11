"use client";

import { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { getDriveSyncStatus } from "@/lib/api/indexing";
import { isApiError } from "@/lib/api/errors";
import type { DriveSyncStatusResponse } from "@/lib/api/types";
import { DEMO_MODE } from "@/lib/demo";

type Snapshot = {
  data: DriveSyncStatusResponse | null;
  isLoading: boolean;
  error: string | null;
};
const INITIAL: Snapshot = { data: null, isLoading: true, error: null };

/** One mounted application owns this source. No cross-user/module-global cache. */
class ConnectionStatusSource {
  private snapshot: Snapshot = INITIAL;
  private listeners = new Set<() => void>();
  private inFlight: Promise<void> | null = null;
  private queuedRefresh: Promise<void> | null = null;
  private polls = new Map<number, { count: number; timer: ReturnType<typeof setInterval> }>();
  private readonly demoMode = DEMO_MODE;

  getSnapshot = () => this.snapshot;
  getServerSnapshot = () => INITIAL;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private publish(snapshot: Snapshot) {
    this.snapshot = snapshot;
    this.listeners.forEach((listener) => listener());
  }

  private request = (): Promise<void> => {
    if (this.inFlight) return this.inFlight;
    this.publish({ ...this.snapshot, isLoading: true });
    this.inFlight = (async () => {
      try {
        const data = await getDriveSyncStatus();
        if ((data.demo_mode === true) !== this.demoMode) {
          throw new Error("Frontend and backend runtime modes do not match.");
        }
        this.publish({ data, isLoading: false, error: null });
      } catch (error) {
        this.publish({
          data: null,
          isLoading: false,
          error: isApiError(error) ? error.detail : error instanceof Error
            ? error.message : "Failed to load connection status",
        });
      }
    })().finally(() => { this.inFlight = null; });
    return this.inFlight;
  };

  /** A manual post-mutation refresh must not settle on a pre-mutation request. */
  refetch = (): Promise<void> => {
    if (!this.inFlight) return this.request();
    if (!this.queuedRefresh) {
      this.queuedRefresh = this.inFlight.then(() => this.request()).finally(() => {
        this.queuedRefresh = null;
      });
    }
    return this.queuedRefresh;
  };

  mount(interval: number) {
    void this.request();
    if (interval > 0) {
      const poll = this.polls.get(interval);
      if (poll) poll.count += 1;
      else this.polls.set(interval, {
        count: 1,
        timer: setInterval(() => { void this.request(); }, interval),
      });
    }
    return () => {
      const poll = this.polls.get(interval);
      if (poll && --poll.count === 0) {
        clearInterval(poll.timer);
        this.polls.delete(interval);
      }
    };
  }
}

const ConnectionStatusContext = createContext<ConnectionStatusSource | null>(null);

export function ConnectionStatusProvider({ children }: { children: ReactNode }) {
  const [source] = useState(() => new ConnectionStatusSource());
  return (
    <ConnectionStatusContext.Provider value={source}>
      {children}
    </ConnectionStatusContext.Provider>
  );
}

export function useSharedConnectionStatus(pollIntervalMs: number) {
  const shared = useContext(ConnectionStatusContext);
  // Standalone consumers remain supported; each has its own isolated source.
  const [local] = useState(() => new ConnectionStatusSource());
  const source = shared ?? local;
  const snapshot = useSyncExternalStore(source.subscribe, source.getSnapshot, source.getServerSnapshot);
  useEffect(() => source.mount(pollIntervalMs), [source, pollIntervalMs]);
  return { ...snapshot, refetch: source.refetch };
}
