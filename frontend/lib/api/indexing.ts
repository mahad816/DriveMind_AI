import { apiFetch, buildQueryString } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type {
  DriveSyncStatusResponse,
  JobStartedResponse,
  PendingCountsResponse,
} from "@/lib/api/types";

export async function getDriveSyncStatus(): Promise<DriveSyncStatusResponse> {
  return apiFetch<DriveSyncStatusResponse>("/index/status");
}

export async function getPendingCounts(): Promise<PendingCountsResponse> {
  return apiFetch<PendingCountsResponse>("/index/pending");
}

export async function syncDriveMetadata(full = false): Promise<JobStartedResponse> {
  return apiFetch<JobStartedResponse>(
    `/index/sync${buildQueryString({ full })}`,
    { method: "POST" },
  );
}

export async function ingestDriveFiles(fileId?: string): Promise<JobStartedResponse> {
  return apiFetch<JobStartedResponse>(
    `/index/ingest${buildQueryString({ file_id: fileId })}`,
    { method: "POST" },
  );
}

export async function chunkDocuments(fileId?: string): Promise<JobStartedResponse> {
  return apiFetch<JobStartedResponse>(
    `/index/chunk${buildQueryString({ file_id: fileId })}`,
    { method: "POST" },
  );
}

export async function buildVectorIndex(fileId?: string): Promise<JobStartedResponse> {
  return apiFetch<JobStartedResponse>(
    `/index/build${buildQueryString({ file_id: fileId })}`,
    { method: "POST" },
  );
}

/**
 * Poll GET /index/status every `intervalMs` until the latest job reaches
 * "completed" or "failed". Only considers jobs created on or after `after`.
 *
 * Throws if the job fails or if `timeoutMs` is exceeded.
 */
export async function pollUntilJobDone(
  after: Date,
  options: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<void> {
  const { intervalMs = 2000, timeoutMs = 180_000 } = options;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    await sleep(intervalMs);

    let statusResp: DriveSyncStatusResponse;
    try {
      statusResp = await getDriveSyncStatus();
    } catch {
      // Transient fetch error — keep polling
      continue;
    }

    const job = statusResp.job;
    if (!job) continue;

    // Only care about jobs that started after we fired the request
    if (new Date(job.created_at) < after) continue;

    if (job.status === "completed") return;
    if (job.status === "failed") {
      throw new ApiError(500, job.error ?? "Job failed");
    }
    // "queued" or "running" — keep waiting
  }

  throw new ApiError(504, "Timed out waiting for the job to complete. The backend may still be working — try refreshing.");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
