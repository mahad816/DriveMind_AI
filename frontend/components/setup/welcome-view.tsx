"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Check } from "lucide-react";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { useWorkspace } from "@/components/workspace/workspace-provider";
import { usePageTitle } from "@/components/shell/shell-context";
import { useSetupState } from "@/components/setup/use-setup";
import { useDiscovery } from "@/components/library/drive-sync";
import { Button, buttonClass } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/controls";
import { cn } from "@/lib/utils";

type StepState = "done" | "current" | "upcoming" | "unknown";

export function WelcomeView() {
  usePageTitle("Set up DriveMind");
  const session = useApplicationSession();
  const setup = useSetupState();
  const { queue } = useWorkspace();
  const queueState = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
  const discovery = useDiscovery();
  const router = useRouter();
  const guide = useSearchParams().has("guide");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  // Finished setup goes straight to chat, unless the guide was reopened from Settings.
  useEffect(() => { if (setup.complete && !guide) router.replace("/chat"); }, [setup.complete, guide, router]);

  const driveStep: StepState = setup.connected === null ? "unknown" : setup.connected ? "done" : "current";
  const prepareStep: StepState = !setup.connected ? "upcoming" : setup.ready === null ? "unknown" : setup.ready > 0 ? "done" : "current";
  const connect = async () => {
    setConnecting(true); setConnectError(null);
    try { await session.connectDrive(); } catch (e) { setConnectError((e as Error).message); setConnecting(false); }
  };
  const findingFiles = discovery.view.running;
  const noFilesYet = setup.connected && setup.files === 0 && !findingFiles;

  return (
    <div className="mx-auto w-full max-w-[36rem] px-5 pb-16 pt-12 md:px-8 md:pt-[12dvh]">
      <h1 className="font-serif text-display font-medium">{setup.complete ? "You're ready to ask." : "Three steps to your first answer."}</h1>
      <p className="mt-3 text-body text-graphite">
        DriveMind lists your Drive&apos;s file names, but reads the contents only of documents you choose. Signing in, connecting Drive and preparing documents are separate, so you stay in control of each.
      </p>
      <ol className="mt-10">
        <Step n={1} state="done" title="Sign in" body="You're signed in with your Google account." />
        <Step n={2} state={driveStep} title="Connect Google Drive"
          body={driveStep === "done"
            ? findingFiles ? discovery.view.line ?? "Reading file names from Drive…" : `Connected with read-only access.${setup.files ? ` ${setup.files.toLocaleString()} files found.` : ""}`
            : "Google will ask for read-only access. DriveMind never edits, moves or deletes your files."}>
          {driveStep === "current" ? (
            <div className="mt-4">
              <Button intent="primary" loading={connecting} disabled={!session.canMutate} onClick={() => void connect()}>Connect Google Drive</Button>
              {connectError ? <p role="alert" className="mt-2 text-label text-fault">{connectError}</p> : null}
            </div>
          ) : null}
          {driveStep === "done" && noFilesYet ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {discovery.view.line ? <p className="text-label text-graphite">{discovery.view.line}</p> : <p className="text-label text-graphite">No files found yet.</p>}
              <Button size="sm" disabled={!discovery.view.canStart} onClick={() => void discovery.start()}>Find my files</Button>
            </div>
          ) : null}
          {driveStep === "unknown" ? <p className="mt-2 text-label text-graphite">Couldn&apos;t check the connection. It will be checked again shortly.</p> : null}
        </Step>
        <Step n={3} state={prepareStep} last title="Prepare your first documents"
          body={prepareStep === "done"
            ? `${setup.ready!.toLocaleString()} ${setup.ready === 1 ? "document is" : "documents are"} ready for questions.`
            : "Choose up to five documents. DriveMind reads them so answers can quote them."}>
          {prepareStep === "current" ? (
            <div className="mt-4">
              {queueState.queue
                ? <p className="text-label text-graphite">Preparation is under way. Follow it in the panel at the bottom of the screen.</p>
                : <Link href="/files?view=todo" className={cn(buttonClass("primary"), findingFiles && "pointer-events-none opacity-45")} aria-disabled={findingFiles || undefined}>Choose documents</Link>}
            </div>
          ) : null}
          {prepareStep === "unknown" ? <Skeleton className="mt-3 h-3.5 w-40" /> : null}
        </Step>
      </ol>
      {setup.complete ? <Link href="/chat" className={cn(buttonClass("primary"), "mt-10")}>Start asking</Link> : null}
    </div>
  );
}

function Step({ n, state, title, body, children, last }: { n: number; state: StepState; title: string; body: string; children?: React.ReactNode; last?: boolean }) {
  return (
    <li className="relative flex gap-4 pb-9" aria-current={state === "current" ? "step" : undefined}>
      {!last ? <span aria-hidden="true" className={cn("absolute left-[0.8125rem] top-8 bottom-1 w-px transition-colors duration-300", state === "done" ? "bg-archive/50" : "bg-rule")} /> : null}
      <span aria-hidden="true" className={cn("relative grid size-[1.625rem] shrink-0 place-items-center rounded-full border text-meta font-semibold tabular transition-colors duration-300",
        state === "done" ? "border-archive bg-archive text-archive-ink" : state === "current" ? "border-archive text-archive-text" : "border-rule-strong text-faint")}>
        {state === "done" ? <Check className="size-3.5" strokeWidth={2.75} /> : n}
      </span>
      <div className="min-w-0 pt-0.5">
        <h2 className={cn("text-body font-medium", state === "upcoming" ? "text-graphite" : "text-ink")}>
          {title}<span className="sr-only">{state === "done" ? " (done)" : state === "current" ? " (next)" : ""}</span>
        </h2>
        <p className="mt-1 text-label text-graphite" aria-live="polite">{body}</p>
        {children}
      </div>
    </li>
  );
}
