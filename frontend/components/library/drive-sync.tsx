"use client";
import { useId, useState, useSyncExternalStore } from "react";
import { RefreshCw } from "lucide-react";
import { useFiles, useWorkspace } from "@/components/workspace/workspace-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { STARTABLE_PHASES, type DiscoveryState } from "@/lib/knowledge/discovery";
import { describeDiscovery, type InventoryCounts } from "@/lib/knowledge/discovery-copy";
import { Button } from "@/components/ui/button";

export type SyncView = {
  phase: DiscoveryState["phase"];
  running: boolean;
  canStart: boolean;
  /** Short status for a header line; null when there is nothing to say. */
  line: string | null;
  tone: "neutral" | "caution";
  needsCheck: boolean;
  disabledReason: string | null;
};

/** Presentation of the kept discovery controller. Unknown or blocked discovery is never restarted automatically. */
export function syncView(state: DiscoveryState, canMutate: boolean, inventory: InventoryCounts = null): SyncView {
  const running = state.phase === "active" || state.phase === "submitting";
  const display = describeDiscovery(state, inventory);
  const needsCheck = !running && (state.phase === "blocked" || state.phase === "unknown" || state.phase === "unavailable" || state.syncAvailable === false);
  const disabledReason = !canMutate ? "Available when DriveMind is reachable again."
    : !state.connected ? "Connect Google Drive first." : null;
  return {
    phase: state.phase, running,
    canStart: STARTABLE_PHASES.includes(state.phase) && display.canSync && canMutate,
    line: display.message,
    tone: needsCheck || state.job?.status === "failed" ? "caution" : "neutral",
    needsCheck, disabledReason,
  };
}

export function useDiscovery() {
  const { discovery } = useWorkspace();
  const { canMutate } = useApplicationSession();
  const files = useFiles();
  const state = useSyncExternalStore(discovery.subscribe, discovery.getSnapshot, discovery.getSnapshot);
  const [checking, setChecking] = useState(false);
  return {
    state, view: syncView(state, canMutate, files.data ? { total: files.data.length, indexed: files.data.filter(f => f.status === "indexed").length } : null),
    start: async () => { if (state.phase === "blocked") await discovery.check(); await discovery.start(); },
    check: async () => { setChecking(true); try { await discovery.check(); } finally { setChecking(false); } },
    checking,
  };
}

export function SyncButton({ label = "Check Drive for changes" }: { label?: string }) {
  const { view, start, check, checking } = useDiscovery();
  const reasonId = useId();
  if (view.needsCheck) return <Button loading={checking} onClick={() => void check()}>Check sync status</Button>;
  return (
    <Button icon={<RefreshCw className={view.running ? "size-3.5 animate-spin [animation-duration:1.4s]" : "size-3.5"} aria-hidden="true" />}
      disabled={!view.canStart} title={view.disabledReason ?? undefined} aria-describedby={view.disabledReason ? reasonId : undefined}
      onClick={() => void start()}>
      {view.running ? "Checking Drive…" : label}
      {view.disabledReason ? <span id={reasonId} className="sr-only">{view.disabledReason}</span> : null}
    </Button>
  );
}
