"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { Button } from "@/components/ui/button";
import { DiscoveryController } from "@/lib/knowledge/discovery";

export function DriveDiscovery({ onComplete, compact = false }: { onComplete?: () => void; compact?: boolean }) {
  const { userId } = useApplicationSession();
  return userId ? <OwnedDiscovery key={userId} owner={userId} onComplete={onComplete} compact={compact} /> : null;
}

function OwnedDiscovery({ owner, onComplete, compact }: { owner: string; onComplete?: () => void; compact: boolean }) {
  const completed = useRef(onComplete);
  completed.current = onComplete;
  const [controller] = useState(() => new DiscoveryController(owner, () => completed.current?.()));
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  useEffect(() => {
    controller.connect();
    void controller.check();
    // Reads only: never resubmit when observing queued, running or uncertain work.
    const timer = setInterval(() => { void controller.check(); }, 5000);
    return () => { clearInterval(timer); controller.dispose(); };
  }, [controller]);
  const canStart = state.connected && ["idle", "complete"].includes(state.phase);
  return <section className={compact ? "flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border pb-2" : "space-y-3 border-b border-border pb-5"} aria-label="Drive discovery">
    {!compact ? <div className="space-y-1">
      <h2 className="text-sm font-semibold">Discover Drive files</h2>
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">Checks names, types and folders for supported documents. Documents are prepared only after you select and review them.</p>
    </div> : null}
    {(!compact || state.phase !== "idle" || (state.job?.operation === "SYNC" && state.job.status === "failed")) ? <p role="status" aria-live="polite" className={compact ? "w-full text-sm" : "text-sm"}>{state.message}</p> : null}
    {state.job?.operation === "SYNC" && state.job.total !== undefined && state.job.total > 0 ? <p className="text-sm tabular-nums text-muted-foreground">{state.job.processed ?? 0} of {state.job.total} metadata updates processed</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button variant={compact ? "outline" : "default"} disabled={!canStart} onClick={() => void controller.start()}>{compact ? "Check for files" : "Check Drive for files / changes"}</Button>
      <Button variant={compact ? "ghost" : "outline"} disabled={state.phase === "submitting"} onClick={() => void controller.check()}>{compact ? "Check status" : "Check discovery status"}</Button>
      {!state.connected && state.phase !== "checking" ? <Link className="inline-flex min-h-11 items-center text-sm underline underline-offset-4" href="/onboarding">Connect or check Drive access</Link> : null}
    </div>
    {compact ? <p className="text-sm text-muted-foreground">File details only; no content is prepared.</p> : null}
  </section>;
}
