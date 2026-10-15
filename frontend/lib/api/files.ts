import { DEMO_MODE } from "@/lib/demo";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import { beginInventoryRead, publishInventoryRead, inventoryCounts } from "@/lib/knowledge/inventory-display";
import { apiBaseUrl } from "@/lib/api/config";
import { apiFetch } from "@/lib/api/client";
import type { DriveFileListResponse } from "@/lib/api/types";

export async function listDriveFiles(signal?: AbortSignal): Promise<DriveFileListResponse> {
  const owner = sessionOwner(), revision = sessionRevision();
  const read = !DEMO_MODE ? beginInventoryRead() : 0;
  try {
    const inventory = await (signal ? apiFetch<DriveFileListResponse>("/files", { signal }) : apiFetch<DriveFileListResponse>("/files"));
    if (!DEMO_MODE && owner) {
      // An advisory display update must not alter an executor's API result.
      let counts = null;
      try { counts = inventoryCounts(inventory, owner); } catch { /* Invalid metadata is unavailable, never ready. */ }
      publishInventoryRead(read, owner, revision, counts);
    }
    return inventory;
  } catch (error) {
    if (!DEMO_MODE && !signal?.aborted) publishInventoryRead(read, owner, revision, null);
    throw error;
  }
}

/**
 * URL for downloading or previewing raw file content from the backend.
 * Content is binary — open in a new tab rather than parsing as JSON.
 */
export function getDriveFileContentUrl(fileId: string): string {
  return `${apiBaseUrl}/files/${encodeURIComponent(fileId)}/content`;
}
