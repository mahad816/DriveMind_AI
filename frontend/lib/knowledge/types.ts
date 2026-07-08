export type PrepareStepId = "connect" | "scan" | "read" | "search" | "ready";

export type PrepareStepPhase = "pending" | "active" | "complete" | "error";

export type PrepareStepState = {
  id: PrepareStepId;
  phase: PrepareStepPhase;
};

export type PrepareProgress = {
  steps: PrepareStepState[];
  progressPercent: number;
  currentStepId: PrepareStepId | null;
  error: string | null;
};

export const PREPARE_STEP_ORDER: PrepareStepId[] = [
  "connect",
  "scan",
  "read",
  "search",
  "ready",
];
