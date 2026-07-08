import { apiBaseUrl } from "@/lib/api/config";
import { apiFetch } from "@/lib/api/client";
import type { DriveFileListResponse } from "@/lib/api/types";

export async function listDriveFiles(): Promise<DriveFileListResponse> {
  return apiFetch<DriveFileListResponse>("/files");
}

/**
 * URL for downloading or previewing raw file content from the backend.
 * Content is binary — open in a new tab rather than parsing as JSON.
 */
export function getDriveFileContentUrl(fileId: string): string {
  return `${apiBaseUrl}/files/${encodeURIComponent(fileId)}/content`;
}
