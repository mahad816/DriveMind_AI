import { apiFetch, buildQueryString } from "@/lib/api/client";
import { sessionOwner, notifySessionInvalid, sessionRevision } from "@/lib/api/session-events";
import { ApiError } from "@/lib/api/errors";
import type {
  DriveSyncStatusResponse,
  IndexingJobRead,
  JobStartedResponse,
  PendingCountsResponse,
} from "@/lib/api/types";

export async function getDriveSyncStatus(jobId?: string): Promise<DriveSyncStatusResponse> {
  return apiFetch<DriveSyncStatusResponse>(`/index/status${buildQueryString({ job_id: jobId })}`);
}

export async function getPendingCounts(): Promise<PendingCountsResponse> {
  const pending = await apiFetch<PendingCountsResponse | null | undefined>("/index/pending");
  if (
    !pending ||
    ![pending.to_ingest, pending.to_chunk, pending.to_build].every(
      (count) => Number.isSafeInteger(count) && count >= 0,
    ) ||
    typeof pending.any_pending !== "boolean" ||
    pending.any_pending !== (pending.to_ingest > 0 || pending.to_chunk > 0 || pending.to_build > 0)
  ) {
    throw new ApiError(503, "Indexing pending state is unavailable.");
  }
  return pending;
}

async function submitIndexJob(path: string): Promise<JobStartedResponse> {
  // Existing same-origin session inspection supplies CSRF material. Fetch per
  // mutation: do not cache a token across logout/account changes.
  const owner = sessionOwner();
  const session = await apiFetch<{ csrf_token: string; user_id?: string }>("/auth/session");
  if (owner && session.user_id !== owner) {
    notifySessionInvalid();
    throw new ApiError(409, "Your account changed. Preparation stopped.");
  }
  if (typeof session.csrf_token !== "string" || !session.csrf_token) {
    throw new ApiError(503, "Application session verification is unavailable.");
  }
  return apiFetch<JobStartedResponse>(path, {
    method: "POST",
    headers: { "X-CSRF-Token": session.csrf_token },
  });
}

export async function syncDriveMetadata(full = false): Promise<JobStartedResponse> {
  return submitIndexJob(`/index/sync${buildQueryString({ full })}`);
}

export async function ingestDriveFiles(fileId?: string): Promise<JobStartedResponse> {
  return submitIndexJob(`/index/ingest${buildQueryString({ file_id: fileId })}`);
}

export async function chunkDocuments(fileId?: string): Promise<JobStartedResponse> {
  return submitIndexJob(`/index/chunk${buildQueryString({ file_id: fileId })}`);
}

export async function buildVectorIndex(fileId?: string): Promise<JobStartedResponse> {
  return submitIndexJob(`/index/build${buildQueryString({ file_id: fileId })}`);
}

/**
 * Poll GET /index/status every `intervalMs` until the latest job reaches
 * "completed" or "failed". Uses the exact server-issued job UUID.
 *
 * Throws if the job fails (unless explicitly allowed) or if `timeoutMs` is exceeded.
 */
export async function pollUntilJobDone(
  jobId: string,
  options: { intervalMs?: number; timeoutMs?: number; allowFailed?: boolean } = {},
): Promise<IndexingJobRead> {
  const { intervalMs = 2000, timeoutMs = 180_000, allowFailed = false } = options;
  const deadline = Date.now() + timeoutMs;
  const revision = sessionRevision();

  while (Date.now() < deadline) {
    await sleep(intervalMs);
    if (revision !== sessionRevision()) throw new ApiError(401, "Your session changed. Polling stopped.");

    let statusResp: DriveSyncStatusResponse;
    try {
      statusResp = await getDriveSyncStatus(jobId);
    } catch (error) {
      if (error instanceof ApiError && [401, 403, 404, 409, 503].includes(error.status)) throw error;
      // Transient fetch error — keep polling
      continue;
    }

    const job = statusResp.job;
    if (!job) continue;

    if (job.id !== jobId) throw new ApiError(503, "The indexing status did not match the submitted job.");

    if (job.status === "completed") return job;
    if (job.status === "failed") {
      if (allowFailed) return job;
      throw new ApiError(500, job.error ?? "Job failed");
    }
    if (job.status === "canceled") throw new ApiError(409, "Indexing job was canceled.");
    // "queued" or "running" — keep waiting
  }

  throw new ApiError(504, "Timed out waiting for the job to complete. The backend may still be working — try refreshing.");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
