"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { Button } from "@/components/ui/button";
import { DiscoveryController } from "@/lib/knowledge/discovery";

export function DriveDiscovery({ onComplete }: { onComplete?: () => void }) {
  const { userId } = useApplicationSession();
  return userId ? <OwnedDiscovery key={userId} owner={userId} onComplete={onComplete} /> : null;
}

function OwnedDiscovery({ owner, onComplete }: { owner: string; onComplete?: () => void }) {
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
  return <section className="space-y-3 border-b border-border pb-5" aria-label="Drive discovery">
    <div className="space-y-1">
      <h2 className="text-sm font-semibold">Discover Drive files</h2>
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">Checks names, types and folders for supported documents. This does not extract document text or create AI embeddings.</p>
    </div>
    <p role="status" aria-live="polite" className="text-sm">{state.message}</p>
    {state.job?.operation === "SYNC" && state.job.total !== undefined && state.job.total > 0 ? <p className="text-sm tabular-nums text-muted-foreground">{state.job.processed ?? 0} of {state.job.total} metadata updates processed</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button disabled={!canStart} onClick={() => void controller.start()}>Check Drive for files / changes</Button>
      <Button variant="outline" disabled={state.phase === "submitting"} onClick={() => void controller.check()}>Check discovery status</Button>
      {!state.connected && state.phase !== "checking" ? <Link className="inline-flex min-h-11 items-center text-sm underline underline-offset-4" href="/onboarding">Connect or check Drive access</Link> : null}
    </div>
  </section>;
}
