import {
  buildVectorIndex,
  chunkDocuments,
  getPendingCounts,
  ingestDriveFiles,
  pollUntilJobDone,
  syncDriveMetadata,
} from "@/lib/api/indexing";
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

export async function prepareKnowledge(
  options: PrepareKnowledgeOptions = {},
): Promise<void> {
  const { onProgress, fullScan = false } = options;
  let steps = createInitialSteps();

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

  const runStep = async (
    stepId: PrepareStepId,
    startPercent: number,
    endPercent: number,
    action: () => Promise<unknown>,
  ) => {
    steps = updateStep(steps, stepId, "active");
    emit({ progressPercent: startPercent, currentStepId: stepId });

    try {
      await action();
      steps = updateStep(steps, stepId, "complete");
      emit({ progressPercent: endPercent, currentStepId: stepId });
    } catch (error) {
      steps = updateStep(steps, stepId, "error");
      const message = toErrorMessage(error);
      emit({ progressPercent: startPercent, currentStepId: stepId, error: message });
      throw error;
    }
  };

  emit({ progressPercent: 0, currentStepId: "scan" });

  // Step 1: sync Drive metadata (always runs — discovers new/changed files).
  await runStep("scan", 10, 30, async () => {
    const before = new Date();
    await syncDriveMetadata(fullScan);
    await pollUntilJobDone(before, { timeoutMs: 180_000 });
  });

  // Check what still needs work after the sync.
  // If nothing is pending we skip the remaining heavy steps entirely — this
  // makes "add one file → Set up" near-instant when everything else is Ready.
  let pending = await getPendingCounts().catch(() => ({
    to_ingest: 1,
    to_chunk: 1,
    to_build: 1,
    any_pending: true,
  }));

  if (!pending.any_pending) {
    // All files are already indexed — mark remaining steps complete and exit.
    steps = updateStep(steps, "read", "complete");
    steps = updateStep(steps, "search", "complete");
    steps = updateStep(steps, "ready", "complete");
    emit({ progressPercent: 100, currentStepId: "ready" });
    return;
  }

  // Step 2: download + extract text (only if files need it).
  if (pending.to_ingest > 0) {
    await runStep("read", 35, 60, async () => {
      const before = new Date();
      await ingestDriveFiles();
      await pollUntilJobDone(before, { timeoutMs: 180_000 });
    });
    // Refresh pending counts after ingest.
    pending = await getPendingCounts().catch(() => pending);
  } else {
    steps = updateStep(steps, "read", "complete");
    emit({ progressPercent: 60, currentStepId: "read" });
  }

  // Step 3: chunk + embed into vector store (only if files need it).
  if (pending.to_chunk > 0 || pending.to_build > 0) {
    await runStep("search", 65, 95, async () => {
      if (pending.to_chunk > 0) {
        const before = new Date();
        await chunkDocuments();
        await pollUntilJobDone(before, { timeoutMs: 120_000 });
      }
      const before2 = new Date();
      await buildVectorIndex();
      await pollUntilJobDone(before2, { timeoutMs: 180_000 });
    });
  } else {
    steps = updateStep(steps, "search", "complete");
    emit({ progressPercent: 95, currentStepId: "search" });
  }

  steps = updateStep(steps, "ready", "complete");
  emit({ progressPercent: 100, currentStepId: "ready" });
}
