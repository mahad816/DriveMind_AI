"use client";
import { useState, useSyncExternalStore } from "react";
import { RefreshCw } from "lucide-react";
import { useWorkspace } from "@/components/workspace/workspace-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import type { DiscoveryState } from "@/lib/knowledge/discovery";
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
export function syncView(state: DiscoveryState, canMutate: boolean): SyncView {
  const job = state.job?.operation === "SYNC" ? state.job : null;
  const running = state.phase === "active" || state.phase === "submitting";
  const so = (n: number | undefined) => (n ? `${n.toLocaleString()} so far` : "");
  let line: string | null = null, tone: SyncView["tone"] = "neutral", needsCheck = false;
  if (state.phase === "submitting") line = "Starting the Drive check…";
  else if (state.phase === "active") line = state.job?.operation === "SYNC" ? `Reading file names from Drive… ${so(job?.processed)}`.trim()
    : "A document is being prepared. Checking Drive will be available when it finishes.";
  else if (state.phase === "complete") line = job ? `Drive checked. ${job.processed ? `${job.processed.toLocaleString()} ${job.processed === 1 ? "change" : "changes"} found.` : "No changes."}` : null;
  else if (state.phase === "unknown") { line = "DriveMind can't confirm whether the Drive check started, so it won't start another. Check again in a moment."; tone = "caution"; needsCheck = true; }
  else if (state.phase === "blocked") {
    tone = "caution";
    line = /preparation is unfinished|preparation record/.test(state.message)
      ? "Drive can't be checked while documents are being prepared. Finish or stop the preparation first."
      : /already pending/.test(state.message) ? "A Drive check is already running in another tab." : "The Drive check couldn't start. Nothing was sent to Drive; try again in a moment.";
  } else if (state.phase === "idle" && job?.status === "failed") { line = "The last Drive check didn't finish. Your files and prepared documents are unaffected."; tone = "caution"; }
  const disabledReason = !state.connected ? "Connect Google Drive first." : !canMutate ? "Available when DriveMind is reachable again." : null;
  return { phase: state.phase, running, canStart: ["idle", "complete", "blocked"].includes(state.phase) && state.connected && canMutate, line, tone, needsCheck, disabledReason };
}

export function useDiscovery() {
  const { discovery } = useWorkspace();
  const { canMutate } = useApplicationSession();
  const state = useSyncExternalStore(discovery.subscribe, discovery.getSnapshot, discovery.getSnapshot);
  const [checking, setChecking] = useState(false);
  return {
    state, view: syncView(state, canMutate),
    start: async () => { if (state.phase === "blocked") await discovery.check(); await discovery.start(); },
    check: async () => { setChecking(true); try { await discovery.check(); } finally { setChecking(false); } },
    checking,
  };
}

export function SyncButton({ label = "Check Drive for changes" }: { label?: string }) {
  const { view, start, check, checking } = useDiscovery();
  if (view.needsCheck) return <Button loading={checking} onClick={() => void check()}>Check again</Button>;
  return (
    <Button icon={<RefreshCw className={view.running ? "size-3.5 animate-spin [animation-duration:1.4s]" : "size-3.5"} aria-hidden="true" />}
      disabled={!view.canStart} title={view.disabledReason ?? undefined} aria-describedby={view.disabledReason ? "sync-reason" : undefined}
      onClick={() => void start()}>
      {view.running ? "Checking Drive…" : label}
      {view.disabledReason ? <span id="sync-reason" className="sr-only">{view.disabledReason}</span> : null}
    </Button>
  );
}
