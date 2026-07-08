"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { AdvancedDiagnostics } from "@/components/knowledge/advanced-diagnostics";
import { PrepareProgress } from "@/components/knowledge/prepare-progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { prepareKnowledge } from "@/lib/knowledge/prepare";
import { setLastPreparedAt } from "@/lib/knowledge/storage";
import type { PrepareProgress as PrepareProgressState } from "@/lib/knowledge/types";
import { PREPARE_STEP_ORDER } from "@/lib/knowledge/types";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { markOnboardingComplete } from "@/lib/onboarding/storage";
import { prepareCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";

const INITIAL_PROGRESS: PrepareProgressState = {
  steps: PREPARE_STEP_ORDER.map((id) => ({ id, phase: "pending" })),
  progressPercent: 0,
  currentStepId: null,
  error: null,
};

type PrepareKnowledgeViewProps = {
  variant?: "page" | "embedded";
  autoStart?: boolean;
  onComplete?: () => void;
  className?: string;
};

export function PrepareKnowledgeView({
  variant = "page",
  autoStart = false,
  onComplete,
  className,
}: PrepareKnowledgeViewProps) {
  const {
    isConnected,
    needsConnect,
    isReady,
    fileStats,
    lastPreparedLabel,
    refresh,
    isLoading: statusLoading,
  } = useKnowledgeStatus({ pollIntervalMs: 0 });

  const [progress, setProgress] = useState<PrepareProgressState>(INITIAL_PROGRESS);
  const [isPreparing, setIsPreparing] = useState(false);
  const [hasPrepared, setHasPrepared] = useState(false);
  const [autoStarted, setAutoStarted] = useState(false);

  const runPrepare = useCallback(async () => {
    if (!isConnected || isPreparing) {
      return;
    }

    setIsPreparing(true);
    setHasPrepared(false);
    setProgress(INITIAL_PROGRESS);

    try {
      await prepareKnowledge({
        onProgress: setProgress,
      });
      setLastPreparedAt();
      setHasPrepared(true);
      markOnboardingComplete();
      await refresh();
      onComplete?.();
    } catch {
      // Error state is stored in progress.
    } finally {
      setIsPreparing(false);
    }
  }, [isConnected, isPreparing, onComplete, refresh]);

  useEffect(() => {
    if (!autoStart || autoStarted || needsConnect || statusLoading) {
      return;
    }
    setAutoStarted(true);
    void runPrepare();
  }, [autoStart, autoStarted, needsConnect, runPrepare, statusLoading]);

  const showComplete =
    variant === "page" &&
    (hasPrepared || (isReady && !isPreparing && progress.progressPercent >= 100));

  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-lg flex-col gap-6",
        variant === "page" ? "px-2 py-4 md:py-8" : "px-0 py-2",
        className,
      )}
    >
      <div className="space-y-2 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <Sparkles className="size-5" />
        </div>
        <h1 className="text-xl font-semibold tracking-tight md:text-2xl">{prepareCopy.title}</h1>
        <p className="text-sm text-muted-foreground">{prepareCopy.description}</p>
      </div>

      {needsConnect ? (
        <Alert className="border-warning/30 bg-warning/10 text-foreground">
          <AlertTitle>Connect Google Drive first</AlertTitle>
          <AlertDescription>
            Connect in <Link className="underline underline-offset-2" href="/settings">Settings</Link>{" "}
            or continue from{" "}
            <Link className="underline underline-offset-2" href="/onboarding">onboarding</Link>.
          </AlertDescription>
        </Alert>
      ) : null}

      {progress.error ? (
        <Alert variant="destructive">
          <AlertTitle>Preparation failed</AlertTitle>
          <AlertDescription>{progress.error}</AlertDescription>
        </Alert>
      ) : null}

      {showComplete ? (
        <div className="rounded-2xl border border-success/30 bg-success/10 p-5 text-center">
          <p className="font-medium text-foreground">{prepareCopy.complete}</p>
          <p className="mt-1 text-sm text-muted-foreground">{prepareCopy.completeHint}</p>
          <Link href="/chat" className={buttonVariants({ size: "lg", className: "mt-4" })}>
            Ask your first question
          </Link>
        </div>
      ) : (
        <>
          <PrepareProgress
            steps={progress.steps}
            progressPercent={isPreparing ? progress.progressPercent : isReady ? 100 : 0}
            connectComplete={isConnected}
          />
          <p className="text-center text-sm text-muted-foreground">{prepareCopy.durationHint}</p>
        </>
      )}

      {!showComplete ? (
        <Button
          type="button"
          size="lg"
          className="w-full"
          disabled={!isConnected || isPreparing}
          onClick={() => void runPrepare()}
        >
          {isPreparing ? <Loader2 className="size-4 animate-spin" /> : null}
          {isPreparing ? prepareCopy.running : prepareCopy.cta}
        </Button>
      ) : null}

      {variant === "page" ? (
        <details className="rounded-2xl border border-border bg-surface-elevated p-4">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            {prepareCopy.advanced}
          </summary>
          <div className="mt-4 space-y-3 border-t border-border pt-4">
            {lastPreparedLabel ? (
              <p className="text-sm text-muted-foreground">
                {prepareCopy.lastPrepared}: {lastPreparedLabel}
                {fileStats.indexed > 0 ? ` · ${fileStats.indexed} ${prepareCopy.filesReady}` : null}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">Your assistant has not been set up yet.</p>
            )}
            <AdvancedDiagnostics />
          </div>
        </details>
      ) : null}
    </div>
  );
}
