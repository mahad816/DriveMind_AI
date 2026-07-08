import { Check, Circle, Loader2 } from "lucide-react";

import type { PrepareStepId, PrepareStepState } from "@/lib/knowledge/types";
import { prepareStepLabel } from "@/lib/user-language";
import { cn } from "@/lib/utils";

type PrepareProgressProps = {
  steps: PrepareStepState[];
  progressPercent: number;
  connectComplete?: boolean;
  className?: string;
};

function StepIcon({ phase }: { phase: PrepareStepState["phase"] }) {
  if (phase === "complete") {
    return <Check className="size-4 text-success" aria-hidden="true" />;
  }
  if (phase === "active") {
    return <Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />;
  }
  if (phase === "error") {
    return <Circle className="size-4 text-destructive" aria-hidden="true" />;
  }
  return <Circle className="size-4 text-muted-foreground/50" aria-hidden="true" />;
}

function displayPhase(
  step: PrepareStepState,
  connectComplete: boolean,
): PrepareStepState["phase"] {
  if (step.id === "connect" && connectComplete) {
    return "complete";
  }
  return step.phase;
}

export function PrepareProgress({
  steps,
  progressPercent,
  connectComplete = false,
  className,
}: PrepareProgressProps) {
  const visibleSteps: PrepareStepId[] = ["connect", "scan", "read", "search"];

  return (
    <div className={cn("space-y-4", className)}>
      <div className="space-y-2">
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${Math.min(Math.max(progressPercent, 0), 100)}%` }}
            role="progressbar"
            aria-valuenow={progressPercent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Knowledge preparation progress"
          />
        </div>
        <p className="text-caption text-muted-foreground">{Math.round(progressPercent)}% complete</p>
      </div>

      <ul className="space-y-3 rounded-2xl border border-border bg-surface-elevated p-4">
        {visibleSteps.map((stepId) => {
          const step = steps.find((item) => item.id === stepId) ?? {
            id: stepId,
            phase: "pending" as const,
          };
          const phase = displayPhase(step, connectComplete);

          return (
            <li key={stepId} className="flex items-center gap-3 text-sm">
              <StepIcon phase={phase} />
              <span
                className={cn(
                  phase === "active" && "font-medium text-foreground",
                  phase === "complete" && "text-foreground",
                  phase === "pending" && "text-muted-foreground",
                  phase === "error" && "text-destructive",
                )}
              >
                {prepareStepLabel[stepId]}
                {phase === "active" ? "…" : null}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
