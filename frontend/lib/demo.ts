import type { DriveSyncStatusResponse } from "@/lib/api/types";

// Public UI setting only. Backend guards enforce safety independently.
export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export function knowledgeAvailable(status: DriveSyncStatusResponse | null): boolean {
  return DEMO_MODE
    ? status?.demo_mode === true && status.demo_ready === true
    : status?.demo_mode !== true && status?.connected === true;
}
