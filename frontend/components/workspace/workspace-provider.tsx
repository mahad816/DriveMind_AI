"use client";
import { createContext, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { listDriveFiles } from "@/lib/api/files";
import { getDriveSyncStatus } from "@/lib/api/indexing";
import type { DriveFileRead, DriveSyncStatusResponse } from "@/lib/api/types";
import { DiscoveryController } from "@/lib/knowledge/discovery";
import { PreparationQueue } from "@/lib/knowledge/preparation-queue";
import { Resource } from "@/lib/state/resource";
import type { ResourceState } from "@/lib/state/resource";
import { SelectionStore } from "@/lib/state/selection";
import { dropOtherOwnersDrafts, takeConnectIntent } from "@/lib/state/browser-memory";

export type Workspace = {
  owner: string;
  files: Resource<DriveFileRead[]>;
  status: Resource<DriveSyncStatusResponse>;
  discovery: DiscoveryController;
  queue: PreparationQueue;
  selection: SelectionStore;
  tray: { open: boolean; setOpen: (open: boolean) => void };
};
const Context = createContext<Workspace | null>(null);
export function useWorkspace(): Workspace {
  const value = useContext(Context);
  if (!value) throw new Error("WorkspaceProvider is required");
  return value;
}
export function useResource<T>(resource: Resource<T>): ResourceState<T> {
  return useSyncExternalStore(resource.subscribe, resource.getSnapshot, resource.getSnapshot);
}
/** Files are read on demand: a consumer mounting asks for data no older than 30 s. */
export function useFiles(): ResourceState<DriveFileRead[]> & { reload: () => Promise<void> } {
  const { files } = useWorkspace();
  const state = useResource(files);
  useEffect(() => { void files.load(30_000); }, [files]);
  return { ...state, reload: files.refresh };
}
export function useDriveStatus() {
  const { status } = useWorkspace();
  return { ...useResource(status), reload: status.refresh };
}

const POLL_MS = 3000;
const STALE_ON_RETURN = 60_000;

export function WorkspaceProvider({ owner, children }: { owner: string; children: ReactNode }) {
  const [value] = useState<Workspace>(() => {
    const files = new Resource<DriveFileRead[]>(async signal => {
      const result = await listDriveFiles(signal);
      if (!Array.isArray(result.files) || result.files.some(file => file.user_id !== owner)) throw new Error("File list owner could not be verified");
      return result.files;
    });
    const status = new Resource<DriveSyncStatusResponse>(signal => getDriveSyncStatus(undefined, signal));
    const discovery = new DiscoveryController(owner, () => { void files.refresh(); void status.refresh(); });
    return { owner, files, status, discovery, queue: new PreparationQueue(owner), selection: new SelectionStore(), tray: { open: false, setOpen: () => {} } };
  });
  const [trayOpen, setTrayOpen] = useState(false);
  const workspace = useMemo(() => ({ ...value, tray: { open: trayOpen, setOpen: setTrayOpen } }), [value, trayOpen]);

  const discoveryState = useSyncExternalStore(value.discovery.subscribe, value.discovery.getSnapshot, value.discovery.getSnapshot);
  const queueState = useSyncExternalStore(value.queue.subscribe, value.queue.getSnapshot, value.queue.getSnapshot);

  // Lifetime: connect controllers, first reads, and the Drive-consent return.
  useEffect(() => {
    const { files, status, discovery, queue } = value;
    dropOtherOwnersDrafts(owner);
    files.connect(); status.connect(); discovery.connect(); queue.connect();
    void status.load();
    void queue.check();
    void (async () => {
      await discovery.check();
      // Returning from a Drive consent this tab started: discover file names once, visibly (blueprint §5.7).
      if (takeConnectIntent(owner) && discovery.getSnapshot().connected) {
        await discovery.start();
        void status.refresh();
      }
    })();
    const storage = (event: StorageEvent) => {
      if (event.key?.includes(owner)) { void queue.check(); void discovery.check(); }
    };
    const pagehide = () => queue.pause();
    window.addEventListener("storage", storage);
    window.addEventListener("pagehide", pagehide);
    return () => {
      window.removeEventListener("storage", storage); window.removeEventListener("pagehide", pagehide);
      queue.dispose(); discovery.dispose(); files.dispose(); status.dispose();
    };
  }, [owner, value]);

  // Visibility return: one refresh of whatever is stale. Nothing runs while the tab is hidden.
  useEffect(() => {
    const visible = () => {
      if (document.hidden) return;
      if (value.status.isStale(STALE_ON_RETURN)) void value.status.load();
      if (value.files.getSnapshot().updatedAt !== null && value.files.isStale(STALE_ON_RETURN)) void value.files.load();
      void value.queue.check();
      const phase = value.discovery.getSnapshot().phase;
      if (phase !== "checking") void value.discovery.check();
    };
    document.addEventListener("visibilitychange", visible);
    return () => document.removeEventListener("visibilitychange", visible);
  }, [value]);

  // Poll only active work, only while visible.
  const discoveryActive = discoveryState.phase === "active";
  const queueActive = !!queueState.queue && (queueState.phase === "progress" || queueState.phase === "checking");
  useEffect(() => {
    if (!discoveryActive && !queueActive) return;
    const tick = () => {
      if (document.hidden) return;
      if (discoveryActive) { void value.discovery.check(); void value.files.refresh(); }
      if (queueActive) void value.queue.check();
    };
    const timer = setInterval(tick, POLL_MS);
    return () => clearInterval(timer);
  }, [discoveryActive, queueActive, value]);

  // A document finished (cursor moved) or the batch ended: the inventory changed.
  const cursor = queueState.queue ? `${queueState.queue.batchId}:${queueState.queue.current}` : "none";
  const lastCursor = useRef(cursor);
  useEffect(() => {
    if (lastCursor.current !== cursor) { lastCursor.current = cursor; void value.files.refresh(); }
  }, [cursor, value]);
  useEffect(() => { if (queueState.queue) setTrayOpen(true); }, [queueState.queue?.batchId]); // eslint-disable-line react-hooks/exhaustive-deps

  return <Context.Provider value={workspace}>{children}</Context.Provider>;
}
