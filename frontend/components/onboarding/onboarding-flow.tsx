"use client";

import Link from "next/link";
import { useState } from "react";
import { DEMO_MODE } from "@/lib/demo";
import { PrepareKnowledgeView } from "@/components/knowledge/prepare-knowledge-view";
import { Button, buttonVariants } from "@/components/ui/button";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";

export function OnboardingFlow() {
  return DEMO_MODE ? <PrepareKnowledgeView /> : <NormalOnboardingFlow />;
}

function NormalOnboardingFlow() {
  const [connecting, setConnecting] = useState(false);
  const { connectDrive, error: sessionError } = useApplicationSession();
  const { setupState, isConnected, fileStats, refresh } = useKnowledgeStatus({ pollIntervalMs: 0 });
  const connect = async () => { if (connecting) return; setConnecting(true); try { await connectDrive(); } finally { setConnecting(false); } };
  return <div className="mx-auto w-full max-w-2xl space-y-8 px-5 py-10 sm:px-8 md:py-16">
    <div className="flex items-center justify-between gap-4">
      <p className="text-sm font-semibold">DriveMind</p>
      <Link href="/settings" className={buttonVariants({ variant: "ghost" })}>Settings</Link>
    </div>
    <header className="space-y-3">
      <h1 className="text-2xl font-semibold tracking-tight">Set up your Drive knowledge</h1>
      <p className="max-w-lg text-sm leading-6 text-muted-foreground">Sign in, connect Drive, then discover supported documents. Discovering files is separate from preparing them for answers.</p>
    </header>
    <ol className="space-y-3 border-y border-border py-5 text-sm" aria-label="Setup steps">
      <li>1. Sign in with Google · Complete</li>
      <li aria-current={!isConnected ? "step" : undefined}>2. Connect Google Drive{isConnected ? " · Complete" : ""}</li>
      <li aria-current={isConnected ? "step" : undefined}>3. Discover documents</li>
      <li className="text-muted-foreground">4. Choose up to five documents, review, then prepare one at a time</li>
    </ol>
    {fileStats.indexed > 0 && !isConnected ? <div className="space-y-2"><p className="text-sm">Your prepared knowledge is available. Reconnect Drive to discover or prepare more documents.</p><Link href="/chat" className={buttonVariants()}>Start chatting</Link></div> : null}
    {sessionError ? <p role="alert">{sessionError}</p> : null}
    {setupState === "checking" ? <p role="status">Checking your Drive connection…</p> : setupState === "error" ? <div className="space-y-3">
      <p role="alert">We couldn’t check your Drive connection or files.</p>
      <Button onClick={() => void refresh()}>Retry status check</Button>
    </div> : !isConnected ? <section className="space-y-4">
      <h2 className="text-lg font-semibold">Connect Google Drive</h2>
      <p className="text-sm leading-6 text-muted-foreground">DriveMind requests read-only access. Connecting does not prepare your documents. You’ll discover file metadata first.</p>
      <div className="flex flex-wrap gap-2"><Button disabled={connecting} onClick={() => void connect()}>{connecting ? "Opening Google…" : "Connect Google Drive"}</Button><Button variant="outline" onClick={() => void refresh()}>Check connection again</Button></div>
    </section> : <section className="space-y-4">
      <h2 className="text-lg font-semibold">Discover your documents</h2>
      <p className="text-sm leading-6 text-muted-foreground">Check Drive for supported files, then browse their names, types and folders. No document preparation starts when you browse.</p>
      <Link href="/files" className={buttonVariants()}>Browse and discover files</Link>
      {fileStats.indexed > 0 ? <div className="space-y-3"><p className="text-sm">{fileStats.indexed} {fileStats.indexed === 1 ? "file ready" : "files ready"}</p><Link href="/chat" className={buttonVariants({ variant: "outline" })}>Start chatting</Link></div> : null}
    </section>}
  </div>;
}
