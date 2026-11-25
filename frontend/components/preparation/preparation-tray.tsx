"use client";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useWorkspace, useResource } from "@/components/workspace/workspace-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { queueConfirmation } from "@/lib/knowledge/preparation-queue";
import { SingleFilePreparation } from "@/lib/knowledge/single-file-preparation";
import { trayModel } from "@/lib/copy/preparation";
import type { RowState, TrayAction } from "@/lib/copy/preparation";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { StatusDot } from "@/components/ui/controls";
import type { Tone } from "@/components/ui/controls";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

const ROW_TONE: Record<RowState, Tone> = {
  waiting: "neutral", starting: "working", reading: "working", organising: "working", finishing: "working", between: "caution",
  ready: "ready", failed: "fault", skipped: "caution", paused: "caution",
};

export function PreparationTray() {
  const { queue, files, tray, owner } = useWorkspace();
  const session = useApplicationSession();
  const state = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
  const inventory = useResource(files);
  const model = trayModel(state, inventory.data);
  const toast = useToast();
  const pathname = usePathname();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ending, setEnding] = useState(false);
  const [endError, setEndError] = useState<string | null>(null);

  if (!model.visible) return null;
  const nothingSentForCurrent = !!state.queue && state.queue.entries[state.queue.current]?.receipts.length === 0;

  const run = async (action: TrayAction) => {
    if (working) return;
    setError(null);
    if (action === "end") { setEnding(true); setEndError(null); return; }
    setWorking(true);
    try {
      if (action === "confirm" && state.queue) await queue.confirm(queueConfirmation(state.queue));
      else if (action === "check") {
        if (state.phase === "legacy") await new SingleFilePreparation(owner, null).check();
        await queue.check(); void files.refresh();
      } else if (action === "reconnect") await session.connectDrive();
      else if (action === "done" && state.queue) {
        if (await queue.finish(state.queue)) toast("Preparation finished");
        else setError("This couldn't be closed yet. Check again in a moment.");
      }
    } catch (e) {
      setError(action === "reconnect" ? (e as Error).message : "That didn't go through. Nothing was sent twice; check again in a moment.");
    } finally { setWorking(false); }
  };

  const endTracking = async () => {
    setWorking(true);
    try {
      let closed = false;
      if (state.phase === "legacy") {
        const legacy = new SingleFilePreparation(owner, null);
        closed = await legacy.finish();
        if (closed) await queue.check();
      } else if (state.queue) closed = await queue.finish(state.queue);
      if (closed) { setEnding(false); toast("Stopped tracking preparation"); void files.refresh(); }
      else setEndError("Tracking can't stop while a step is running. Wait for it to finish, then try again.");
    } finally { setWorking(false); }
  };

  const open = tray.open;
  const lift = pathname.startsWith("/chat") ? "max-md:bottom-[calc(7.5rem+env(safe-area-inset-bottom))]" : "max-md:bottom-[calc(1rem+env(safe-area-inset-bottom))]";
  return (
    <aside aria-label="Document preparation"
      className={cn("enter-rise float-layer fixed z-40 overflow-hidden rounded-panel border border-rule bg-sheet",
        "md:bottom-4 md:right-4 md:w-[var(--tray)] max-md:inset-x-3", lift)}>
      <button type="button" onClick={() => tray.setOpen(!open)} aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-well/60">
        <StatusDot tone={model.tone === "working" ? "working" : model.tone === "attention" ? "caution" : model.tone === "done" ? "ready" : "neutral"} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-label font-medium">{open ? model.headline : model.pill}</span>
        </span>
        {open ? <ChevronDown className="size-4 text-graphite" aria-hidden="true" /> : <ChevronUp className="size-4 text-graphite" aria-hidden="true" />}
        <span className="sr-only">{open ? "Collapse" : "Expand"} preparation details</span>
      </button>
      <div className={cn("grid transition-[grid-template-rows] duration-[220ms] ease-[var(--ease-out)]", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div className="min-h-0 overflow-hidden" inert={!open || undefined}>
          <div className="border-t border-rule px-4 pb-4 pt-3">
            <p role="status" aria-live="polite" className="text-label text-graphite">{model.summary}</p>
            {model.rows.length ? (
              <ol className="mt-3 max-h-56 space-y-2.5 overflow-y-auto">
                {model.rows.map(row => (
                  <li key={row.fileId} className="flex gap-2.5">
                    <span className="mt-1.5"><StatusDot tone={ROW_TONE[row.state]} /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-label text-ink" title={row.name}>{row.name}</span>
                      <span className={cn("block text-meta", row.state === "failed" ? "text-fault" : "text-graphite")}>{row.label}</span>
                      {row.detail ? <span className="block text-meta text-faint">{row.detail}</span> : null}
                    </span>
                  </li>
                ))}
              </ol>
            ) : null}
            {error ? <p role="alert" className="mt-3 text-meta text-fault">{error}</p> : null}
            {model.primary || model.secondary.length ? (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                {model.primary ? (
                  <Button intent="primary" size="sm" loading={working}
                    disabled={(model.primary.action === "confirm" || model.primary.action === "reconnect") && !session.canMutate}
                    title={!session.canMutate ? "Available when DriveMind is reachable again" : undefined}
                    onClick={() => void run(model.primary!.action)}>{model.primary.label}</Button>
                ) : null}
                {model.secondary.map(s => (
                  <Button key={s.label} intent="quiet" size="sm" disabled={working} onClick={() => void run(s.action)}>{s.label}</Button>
                ))}
                {model.tone === "done" && inventory.data?.some(f => f.status === "indexed") ? (
                  <Link href="/chat" className="ml-auto text-label text-archive-text underline underline-offset-2">Ask a question</Link>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <ConfirmDialog open={ending} onOpenChange={setEnding} busy={working} error={endError}
        title="Stop tracking this preparation?" confirmLabel="Stop tracking"
        description={nothingSentForCurrent
          ? "Documents that haven't started won't be prepared. Documents that are ready stay ready."
          : "This only stops tracking on this device. A step that was already sent may still finish, and the library will show the result."}
        onConfirm={() => void endTracking()} />
    </aside>
  );
}
