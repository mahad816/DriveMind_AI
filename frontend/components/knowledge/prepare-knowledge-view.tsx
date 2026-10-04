"use client";

import { DEMO_MODE } from "@/lib/demo";

import Link from "next/link";
import { useCallback, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { AdvancedDiagnostics } from "@/components/knowledge/advanced-diagnostics";
import { Button, buttonVariants } from "@/components/ui/button";
import { getGoogleAuthUrl } from "@/lib/api/auth";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { prepareKnowledge } from "@/lib/knowledge/prepare";
import { setLastPreparedAt } from "@/lib/knowledge/storage";
import type { PrepareProgress } from "@/lib/knowledge/types";
import { cn } from "@/lib/utils";

type PrepareKnowledgeViewProps = {
  variant?: "page" | "embedded";
  onComplete?: () => void;
  onPreparingChange?: (preparing: boolean) => void;
  className?: string;
};

export function PrepareKnowledgeView({
  variant = "page",
  onComplete,
  onPreparingChange,
  className,
}: PrepareKnowledgeViewProps) {
  const { setupState, isConnected, jobError, fileStats, refresh, error } = useKnowledgeStatus({ pollIntervalMs: 0 });
  const [progress, setProgress] = useState<PrepareProgress | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [hasPrepared, setHasPrepared] = useState(false);
  const [completionWarning, setCompletionWarning] = useState<string | null>(null);

  const runPrepare = useCallback(async (fullScan = false) => {
    if (DEMO_MODE) return;
    if ((setupState !== "connected_not_ready" && setupState !== "ready") || isPreparing) return;

    setIsPreparing(true);
    onPreparingChange?.(true);
    setHasPrepared(false);
    setCompletionWarning(null);
    setProgress(null);
    try {
      const result = await prepareKnowledge({ onProgress: setProgress, fullScan });
      setCompletionWarning(result.warning);
      setLastPreparedAt();
      setHasPrepared(true);
      await refresh();
      onComplete?.();
    } catch {
      // prepareKnowledge reports the failed operation through onProgress.
    } finally {
      setIsPreparing(false);
      onPreparingChange?.(false);
    }
  }, [isPreparing, onComplete, onPreparingChange, refresh, setupState]);

  if (DEMO_MODE) {
    return (
      <section className="space-y-4 p-6">
        <h1 className="text-xl font-semibold">Sample knowledge base</h1>
        <p className="text-sm text-muted-foreground">Seven fictional HarborDesk documents. No Google Drive connection is needed. Visitors cannot sync or rebuild this index.</p>
        <p role="status">{setupState === "ready" ? `${fileStats.indexed} sample files ready` : error ?? "Checking sample index…"}</p>
        <Button onClick={() => void refresh()} variant="outline">Refresh status</Button>
        <Link href="/chat" className={buttonVariants()}>Open chat</Link>
        <Link href="/files" className={buttonVariants({ variant: "outline" })}>Browse samples</Link>
      </section>
    );
  }

  const preparing = isPreparing || setupState === "preparing";
  const ready = setupState === "ready" && !preparing;
  const notConnected = setupState === "not_connected";
  const unavailable = setupState === "error";

  const statusText = setupState === "checking"
    ? "Checking your Drive connection and knowledge…"
    : unavailable
      ? "Knowledge status unavailable"
      : notConnected
        ? "Google Drive is not connected"
        : preparing
          ? "Preparing your knowledge…"
          : ready
            ? "Knowledge ready"
            : "Knowledge needs preparation";

  const content = (
    <div className="space-y-5">
      {variant === "page" ? (
        <section className="space-y-2 border-b border-border pb-5" aria-labelledby="drive-connection-heading">
          <h2 id="drive-connection-heading" className="text-sm font-semibold text-foreground">Google Drive</h2>
          <p className="text-sm text-muted-foreground">
            {isConnected ? "Connected" : setupState === "checking" ? "Checking your Drive connection…" : unavailable
              ? "Couldn’t check your Drive connection or files."
              : "Not connected"}
          </p>
        </section>
      ) : null}

      <section className="space-y-3" aria-labelledby={variant === "page" ? "knowledge-status-heading" : undefined}>
        {variant === "page" ? (
          <h2 id="knowledge-status-heading" className="text-sm font-semibold text-foreground">Knowledge status</h2>
        ) : null}
        <p className="text-base font-medium text-foreground" role="status">{statusText}</p>
        {ready || (fileStats.indexed > 0 && !unavailable && !notConnected) ? (
          <p className="text-sm tabular-nums text-muted-foreground">
            {fileStats.indexed} {fileStats.indexed === 1 ? "file" : "files"} ready
          </p>
        ) : null}
        {fileStats.failed > 0 && !unavailable && !notConnected ? (
          <p className="text-sm tabular-nums text-muted-foreground">
            {fileStats.failed} {fileStats.failed === 1 ? "file needs" : "files need"} attention
          </p>
        ) : null}
        {preparing ? <p className="text-sm text-muted-foreground">This can take a few minutes. You can return to check the status.</p> : null}
        {hasPrepared && !ready && !preparing && !progress?.error && !unavailable ? (
          <p className="text-sm text-muted-foreground">Preparation finished, but no files are ready yet.</p>
        ) : null}
        {jobError && !preparing ? <p className="text-sm text-destructive">Last preparation failed: {jobError}</p> : null}
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        {progress?.error ? <p className="text-sm text-destructive">Preparation failed: {progress.error}</p> : null}
        {completionWarning ? <p className="text-sm text-muted-foreground">{completionWarning}</p> : null}
      </section>

      <div className="flex flex-wrap gap-2">
        {notConnected ? (
          <a href={getGoogleAuthUrl()} className={buttonVariants()}>Connect Google Drive</a>
        ) : unavailable ? (
          <Button type="button" onClick={() => void refresh()}>Retry status check</Button>
        ) : setupState === "checking" ? (
          <Button type="button" disabled>Checking…</Button>
        ) : preparing ? (
          <Button type="button" disabled>
            <Loader2 className="mr-2 size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            Preparing knowledge…
          </Button>
        ) : ready ? (
          <>
            {variant === "page" ? <Link href="/chat" className={buttonVariants()}>Start chatting</Link> : null}
            {variant === "page" ? (
              <Button type="button" variant="outline" onClick={() => void runPrepare()}>
                Refresh knowledge
              </Button>
            ) : null}
          </>
        ) : (
          <Button type="button" onClick={() => void runPrepare()}>Prepare knowledge</Button>
        )}
        {variant === "page" && !preparing && !unavailable && !notConnected ? (
          <Button type="button" variant="ghost" onClick={() => void refresh()}>
            <RefreshCw className="mr-2 size-4" aria-hidden="true" />Refresh status
          </Button>
        ) : null}
      </div>

      {variant === "page" && (ready || setupState === "connected_not_ready") ? (
        <details className="border-t border-border pt-4">
          <summary className="cursor-pointer text-sm text-muted-foreground">Advanced</summary>
          <div className="mt-4 space-y-3">
            <Button type="button" variant="outline" size="sm" onClick={() => void runPrepare(true)}>
              Full scan
            </Button>
            <AdvancedDiagnostics />
          </div>
        </details>
      ) : null}
    </div>
  );

  if (variant === "embedded") return <div className={cn("w-full", className)}>{content}</div>;

  return (
    <div className={cn("mx-auto w-full max-w-3xl px-5 py-10 sm:px-8 md:py-14", className)}>
      <header className="mb-10 max-w-xl space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Knowledge</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Manage the Google Drive knowledge DriveMind uses for grounded answers.
        </p>
      </header>
      {content}
    </div>
  );
}
