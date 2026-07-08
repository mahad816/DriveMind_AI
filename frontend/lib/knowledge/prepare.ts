import {
  buildVectorIndex,
  chunkDocuments,
  ingestDriveFiles,
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
};

export async function prepareKnowledge(
  options: PrepareKnowledgeOptions = {},
): Promise<void> {
  const { onProgress } = options;
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

  await runStep("scan", 10, 30, () => syncDriveMetadata(false));
  await runStep("read", 35, 60, () => ingestDriveFiles());
  await runStep("search", 65, 95, async () => {
    await chunkDocuments();
    await buildVectorIndex();
  });

  steps = updateStep(steps, "ready", "complete");
  emit({ progressPercent: 100, currentStepId: "ready" });
}
