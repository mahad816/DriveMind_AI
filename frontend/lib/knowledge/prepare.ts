import {
  buildVectorIndex,
  chunkDocuments,
  getPendingCounts,
  ingestDriveFiles,
  pollUntilJobDone,
  syncDriveMetadata,
} from "@/lib/api/indexing";
import { sessionRevision } from "@/lib/api/session-events";
import { ApiError } from "@/lib/api/errors";
import type { PrepareProgress, PrepareStepId, PrepareStepState } from "@/lib/knowledge/types";
import { PREPARE_STEP_ORDER } from "@/lib/knowledge/types";

function createInitialSteps(): PrepareStepState[] {
  return PREPARE_STEP_ORDER.map((id) => ({ id, phase: "pending" }));
}

function updateStep(
  steps: PrepareStepState[],
  stepId: PrepareStepId,
  phase: PrepareStepState["phase"],
): PrepareStepState[] {
  return steps.map((step) => (step.id === stepId ? { ...step, phase } : step));
}

function toErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong while preparing your knowledge.";
}

export type PrepareKnowledgeOptions = {
  onProgress?: (progress: PrepareProgress) => void;
  /** Force a full Drive re-scan instead of incremental. Use when files are missing. */
  fullScan?: boolean;
};

export type PrepareKnowledgeResult = {
  warning: string | null;
};

export async function prepareKnowledge(
  options: PrepareKnowledgeOptions = {},
): Promise<PrepareKnowledgeResult> {
  const { onProgress, fullScan = false } = options;
  const revision = sessionRevision();
  const checkSession = () => { if (revision !== sessionRevision()) throw new ApiError(401, "Your session changed. Preparation stopped."); };
  let steps = createInitialSteps();
  let ingestionWarning: string | null = null;

  const emit = (
    partial: Partial<PrepareProgress> & {
      currentStepId?: PrepareStepId | null;
    },
  ) => {
    onProgress?.({
      steps,
      progressPercent: partial.progressPercent ?? 0,
      currentStepId: partial.currentStepId ?? null,
      error: partial.error ?? null,
    });
  };

  const runStep = async <T>(
    stepId: PrepareStepId,
    startPercent: number,
    endPercent: number,
    action: () => Promise<T>,
  ) => {
    steps = updateStep(steps, stepId, "active");
    emit({ progressPercent: startPercent, currentStepId: stepId });

    try {
      checkSession();
      const result = await action();
      checkSession();
      steps = updateStep(steps, stepId, "complete");
      emit({ progressPercent: endPercent, currentStepId: stepId });
      return result;
    } catch (error) {
      steps = updateStep(steps, stepId, "error");
      const message = toErrorMessage(error);
      emit({ progressPercent: startPercent, currentStepId: stepId, error: message });
      throw error;
    }
  };

  emit({ progressPercent: 0, currentStepId: "scan" });

  // Step 1: sync Drive metadata (always runs — discovers new/changed files).
  let pending = await runStep("scan", 10, 30, async () => {
    const accepted = await syncDriveMetadata(fullScan);
    await pollUntilJobDone(accepted.job_id, { timeoutMs: 180_000 });
    // Fresh state is required before deciding which stages can be skipped.
    checkSession();
    return getPendingCounts();
  });

  // Check what still needs work after the sync.
  // If nothing is pending we skip the remaining heavy steps entirely — this
  // makes "add one file → Set up" near-instant when everything else is Ready.
  if (!pending.any_pending) {
    // All files are already indexed — mark remaining steps complete and exit.
    steps = updateStep(steps, "read", "complete");
    steps = updateStep(steps, "search", "complete");
    steps = updateStep(steps, "ready", "complete");
    emit({ progressPercent: 100, currentStepId: "ready" });
    return { warning: null };
  }

  // Step 2: download + extract text (only if files need it).
  if (pending.to_ingest > 0) {
    await runStep("read", 35, 60, async () => {
      const accepted = await ingestDriveFiles();
      const job = await pollUntilJobDone(accepted.job_id, {
        timeoutMs: 180_000,
        allowFailed: true,
      });

      if (job.status === "failed") {
        const originalError = job.error ?? "Job failed";
        checkSession();
        pending = await getPendingCounts();
        if (pending.to_chunk === 0 && pending.to_build === 0) {
          throw new ApiError(500, originalError);
        }
        ingestionWarning = originalError;
      } else {
        checkSession();
        pending = await getPendingCounts();
      }
    });
  } else {
    steps = updateStep(steps, "read", "complete");
    emit({ progressPercent: 60, currentStepId: "read" });
  }

  // Step 3: chunk + embed into vector store (only if files need it).
  if (pending.to_chunk > 0 || pending.to_build > 0) {
    await runStep("search", 65, 95, async () => {
      if (pending.to_chunk > 0) {
        const accepted = await chunkDocuments();
        await pollUntilJobDone(accepted.job_id, { timeoutMs: 120_000 });
        // Chunking changes build eligibility, so use authoritative fresh counts.
        checkSession();
        pending = await getPendingCounts();
      }
      if (pending.to_build > 0) {
        checkSession();
        const accepted = await buildVectorIndex();
        await pollUntilJobDone(accepted.job_id, { timeoutMs: 180_000 });
      }
    });
  } else {
    steps = updateStep(steps, "search", "complete");
    emit({ progressPercent: 95, currentStepId: "search" });
  }

  steps = updateStep(steps, "ready", "complete");
  emit({ progressPercent: 100, currentStepId: "ready" });
  return { warning: ingestionWarning };
}
