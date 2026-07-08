import { apiFetch, buildQueryString } from "@/lib/api/client";
import type {
  ChunkingResponse,
  DriveSyncResponse,
  DriveSyncStatusResponse,
  IndexBuildResponse,
  IngestionResponse,
} from "@/lib/api/types";

export async function getDriveSyncStatus(): Promise<DriveSyncStatusResponse> {
  return apiFetch<DriveSyncStatusResponse>("/index/status");
}

export async function syncDriveMetadata(full = false): Promise<DriveSyncResponse> {
  return apiFetch<DriveSyncResponse>(
    `/index/sync${buildQueryString({ full })}`,
    { method: "POST" },
  );
}

export async function ingestDriveFiles(fileId?: string): Promise<IngestionResponse> {
  return apiFetch<IngestionResponse>(
    `/index/ingest${buildQueryString({ file_id: fileId })}`,
    { method: "POST" },
  );
}

export async function chunkDocuments(fileId?: string): Promise<ChunkingResponse> {
  return apiFetch<ChunkingResponse>(
    `/index/chunk${buildQueryString({ file_id: fileId })}`,
    { method: "POST" },
  );
}

export async function buildVectorIndex(fileId?: string): Promise<IndexBuildResponse> {
  return apiFetch<IndexBuildResponse>(
    `/index/build${buildQueryString({ file_id: fileId })}`,
    { method: "POST" },
  );
}
