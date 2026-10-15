"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { PageShell } from "@/components/layout/page-shell";
import { Button, buttonVariants } from "@/components/ui/button";
import { FileStatusBadge } from "@/components/files/file-status-badge";
import { fileTypeLabel } from "@/lib/files/utils";
import { SingleFilePreparation, stages } from "@/lib/knowledge/single-file-preparation";
import { DEMO_MODE } from "@/lib/demo";

export function SingleFilePreparationView() {
  const { userId } = useApplicationSession();
  const params = useSearchParams();
  return !DEMO_MODE && userId ? <OwnedPreparation key={`${userId}:${params.get("file") ?? "saved"}`} owner={userId} fileId={params.get("file")} /> : null;
}
function OwnedPreparation({ owner, fileId }: { owner: string; fileId: string | null }) {
  const router = useRouter();
  const [controller] = useState(() => new SingleFilePreparation(owner, fileId));
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  useEffect(() => {
    controller.connect(); void controller.check();
    const pauseWhenHidden = () => { if (document.hidden) controller.pause(); };
    window.addEventListener("pagehide", controller.pause);
    document.addEventListener("visibilitychange", pauseWhenHidden);
    const timer = window.setInterval(() => { void controller.check(); }, 3000);
    return () => {
      window.clearInterval(timer); window.removeEventListener("pagehide", controller.pause);
      document.removeEventListener("visibilitychange", pauseWhenHidden); controller.dispose();
    };
  }, [controller]);
  const labels = ["Reading document", "Preparing searchable text", "Building search index"];
  const current = stages.indexOf(state.stage!);
  return <PageShell title={state.phase === "review" ? "Review document" : "Document preparation"} size="md">
    {state.file ? <section aria-label="Selected document" className="space-y-2 border-y border-border py-5">
      <p className="text-xs font-medium text-muted-foreground">One document selected</p>
      <h2 className="break-words text-lg font-semibold">{state.file.name}</h2>
      <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground"><span>{fileTypeLabel(state.file.mime_type)}</span><FileStatusBadge status={state.file.status} /></div>
    </section> : null}
    <p role="status" aria-live="polite" className="text-sm leading-6">{state.message}</p>
    {state.phase === "review" ? <p className="text-sm leading-6 text-muted-foreground">DriveMind will read this document, extract searchable text, and create a search index. Relevant content is processed using the configured AI services. Your original Google Drive document will not be modified.</p> : null}
    {state.stage ? <ol aria-label="Preparation stages" className="space-y-3 text-sm">
      {stages.map((stage, i) => <li key={stage} aria-current={stage === state.stage ? "step" : undefined} className={i > current ? "text-muted-foreground" : "text-foreground"}>
        {labels[i]} <span className="text-muted-foreground">· {i < current ? "Completed" : i > current ? "Not started" : state.phase === "ready" || state.phase === "continue" ? "Completed" : state.phase === "submitting" ? "Requesting" : state.phase === "unknown" || state.phase === "blocked" ? "Needs review" : state.job?.status === "queued" ? "Queued" : state.job?.status === "running" ? "In progress" : state.phase === "skipped" ? "Skipped" : state.phase === "failed" ? "Failed" : "Needs review"}</span>
      </li>)}
    </ol> : null}
    {state.job?.total === 1 && state.stage && ["active", "continue", "ready"].includes(state.phase) ? <p className="text-sm tabular-nums text-muted-foreground">{state.job.processed ?? 0} of 1 document processed in this stage</p> : null}
    <div className="flex flex-wrap gap-2">
      {state.phase === "review" ? <Button onClick={() => void controller.confirm()}>Prepare this document</Button> : null}
      {state.phase === "continue" ? <Button onClick={() => void controller.confirm()}>Continue preparation</Button> : null}
      {state.phase === "ready" ? <Button onClick={() => { void controller.finish().then(closed => { if (closed) router.push("/chat"); }); }}>Start chatting</Button> : state.phase === "ineligible" && state.file?.status === "indexed" ? <Link className={buttonVariants()} href="/chat">Start chatting</Link> : null}
      {state.canRelease ? <Button variant="outline" onClick={() => { void controller.finish().then(closed => { if (closed) router.push("/files"); }); }}>Back to files</Button> : <Link onClick={controller.pause} className={buttonVariants({ variant: "outline" })} href="/files">{state.phase === "review" ? "Cancel" : "Back to files"}</Link>}
      {!["checking", "submitting"].includes(state.phase) ? <Button variant="ghost" onClick={() => void controller.check()}>Check preparation status</Button> : null}
      {["blocked", "unknown"].includes(state.phase) ? <Link onClick={controller.pause} href="/settings" className={buttonVariants({ variant: "ghost" })}>Settings</Link> : null}
    </div>
    {state.phase === "ready" ? <p className="text-sm leading-6 text-muted-foreground">Chat uses your prepared knowledge. It is not restricted to this document.</p> : null}
    {state.phase === "active" || state.phase === "submitting" ? <p className="text-sm leading-6 text-muted-foreground">Leaving this page does not cancel an accepted server job. Return to preparation progress to check it; after returning, you’ll confirm before any further stage starts.</p> : null}
  </PageShell>;
}
