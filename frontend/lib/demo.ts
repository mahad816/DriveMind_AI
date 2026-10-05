import type { DriveSyncStatusResponse } from "@/lib/api/types";

// Public UI setting only. Backend guards enforce safety independently.
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export const DEMO_QUESTION_LIMIT = 4000;
// Count Unicode characters consistently with the backend's character limit.
export const questionCharacters = (value: string) => Array.from(value).length;

export const DEMO_SUGGESTIONS = [
  "What is HarborDesk and who is the pilot for?",
  'Summarize "architecture_notes.txt".',
  "How did pilot feedback influence the launch scope?",
  "When is the pilot launch and what must happen first?",
] as const;

export function knowledgeAvailable(status: DriveSyncStatusResponse | null): boolean {
  return DEMO_MODE
    ? status?.demo_mode === true && status.demo_ready === true
    : status?.demo_mode !== true && status?.connected === true;
}
