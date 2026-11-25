import type { DiscoveryState } from "./discovery";

/** Counts from the stored inventory (GET /files). Null until the inventory has loaded. */
export type InventoryCounts = { total: number; indexed: number } | null;

export type DiscoveryDisplay = {
  message: string;
  /** Label for the sync button. "Retry sync" only after a failure or a known refusal. */
  actionLabel: string;
  /** The sync button is usable (still subject to the controller's own guards). */
  canSync: boolean;
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * One source of truth for what the Drive sync area says. Derives every message from
 * actual backend state (job status, executor availability, stored files). It never
 * reports success before a job has finished and never shows a made-up percentage.
 */
export function describeDiscovery(state: DiscoveryState, inventory: InventoryCounts): DiscoveryDisplay {
  const syncJob = state.job?.operation === "SYNC" ? state.job : null;
  const failed = syncJob?.status === "failed";
  const total = inventory?.total ?? 0;
  const base = { actionLabel: failed || state.phase === "unavailable" ? "Retry sync" : "Sync Drive" };

  if (state.phase === "checking") return { ...base, message: "Checking Google Drive…", canSync: false };
  if (state.phase === "blocked" || state.phase === "unknown") return { ...base, message: state.message, canSync: false };
  if (!state.connected) {
    // Stored files with no live connection mean access was lost, not that Drive was never linked.
    return {
      ...base,
      canSync: false,
      message: total > 0
        ? "Your Google Drive connection needs to be renewed."
        : "Connect Google Drive to find your files.",
    };
  }
  if (state.phase === "submitting" || state.phase === "active") {
    return { actionLabel: "Syncing Drive…", message: state.job && !syncJob ? "Document preparation is active. Sync will be available when it finishes." : "Finding files in your Google Drive…", canSync: false };
  }
  // Controller-owned messages for states that need their specific instruction.
  if (state.phase === "unavailable" || state.syncAvailable === false) {
    return { ...base, message: "Sync is temporarily unavailable. Please try again.", canSync: state.phase === "unavailable" && state.syncAvailable !== false };
  }
  if (failed) return { ...base, canSync: true, message: "Sync failed. Your Google Drive files were not changed. Check status before trying again." };
  if (state.phase === "complete") {
    return {
      ...base,
      canSync: true,
      message: inventory === null
        ? `Sync complete. ${plural(syncJob?.processed ?? 0, "metadata update", "metadata updates")} processed.`
        : total > 0
          ? `Sync complete. ${plural(total, "file", "files")} found.`
          : "No supported files were found in this Drive.",
    };
  }
  // idle: never synced, or synced earlier.
  if (total === 0) {
    return { ...base, canSync: true, message: "Google Drive is connected. Sync to find your files." };
  }
  if ((inventory?.indexed ?? 0) > 0) {
    return { ...base, canSync: true, message: `${plural(inventory!.indexed, "file is", "files are")} ready for chat. Select a file to prepare more.` };
  }
  return { ...base, canSync: true, message: "Files found. Select a file to prepare it for chat." };
}
