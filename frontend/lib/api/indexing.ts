import { apiFetch, buildQueryString } from "@/lib/api/client";
import { sessionOwner, notifySessionInvalid, sessionRevision } from "@/lib/api/session-events";
import { ApiError } from "@/lib/api/errors";
import type {
  DriveSyncStatusResponse,
  IndexingJobRead,
  JobStartedResponse,
  PendingCountsResponse,
} from "@/lib/api/types";

export async function getDriveSyncStatus(jobId?: string, signal?: AbortSignal): Promise<DriveSyncStatusResponse> {
  const path = `/index/status${buildQueryString({ job_id: jobId })}`;
  return signal ? apiFetch<DriveSyncStatusResponse>(path, { signal }) : apiFetch<DriveSyncStatusResponse>(path);
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

export type SyncReceipt = { outcome: "accepted"; jobId: string } | { outcome: "rejected" };
export class SyncSubmissionError extends Error {
  constructor(readonly outcome: "not_submitted" | "rejected" | "unknown") {
    super(outcome === "unknown" ? "Discovery acceptance could not be confirmed." : "Discovery was not accepted.");
  }
}

async function submitIndexJob(
  path: string,
  signal?: AbortSignal,
  receipt?: (value: SyncReceipt) => Promise<void>,
): Promise<JobStartedResponse> {
  const owner = sessionOwner();
  const revision = sessionRevision();
  let postAttempted = false;
  let acceptedReceipt = false;
  const receiptState: { outcome: "rejected" | "unknown" } = { outcome: "unknown" };
  try {
    // Fresh same-origin proof before every mutation; never cache CSRF across owners.
    type SessionProof = { csrf_token: string; user_id?: string };
    const session = signal
      ? await apiFetch<SessionProof>("/auth/session", { signal })
      : await apiFetch<SessionProof>("/auth/session");
    if (owner && session.user_id !== owner) {
      notifySessionInvalid();
      throw new ApiError(409, "Your account changed. Preparation stopped.");
    }
    if (typeof session.csrf_token !== "string" || !session.csrf_token.trim()) {
      throw new ApiError(503, "Application session verification is unavailable.");
    }
    if (receipt && (!owner || owner !== sessionOwner() || revision !== sessionRevision() || signal?.aborted)) {
      throw new SyncSubmissionError("not_submitted");
    }
    postAttempted = true;
    const result = await apiFetch<JobStartedResponse>(path, {
      method: "POST",
      ...(signal ? { signal } : {}),
      headers: { "X-CSRF-Token": session.csrf_token },
      ...(receipt ? { onResponseReceipt: async (response: Response) => {
        // Observe only this request's receipt. apiFetch still fences its return value.
        // A lost/truncated body is ambiguous, including for errors.
        const body = await response.json().catch(() => null);
        if (response.status === 202 && body?.status === "queued" &&
            typeof body.job_id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(body.job_id)) {
          await receipt({ outcome: "accepted", jobId: body.job_id });
          acceptedReceipt = true;
        } else if (
          // Exact guard/admission rejections, before any new job commit:
          // api/session_dependencies.py, security/session_helpers.py, api/index.py.
          (response.status === 401 && body?.detail === "Your application session is invalid or expired.") ||
          (response.status === 403 && body?.detail === "Application session request could not be verified.") ||
          (response.status === 409 && body?.detail === "An unresolved indexing job already exists for this account.")
        ) {
          receiptState.outcome = "rejected";
          await receipt({ outcome: "rejected" });
        }
      } } : {}),
    });
    if (receipt && !acceptedReceipt) throw new SyncSubmissionError("unknown");
    return result;
  } catch (error) {
    if (!receipt) throw error; // Existing preparation callers keep their contract.
    throw new SyncSubmissionError(postAttempted ? receiptState.outcome : "not_submitted");
  }
}

export async function syncDriveMetadata(
  full = false, signal?: AbortSignal, receipt?: (value: SyncReceipt) => Promise<void>,
): Promise<JobStartedResponse> {
  return submitIndexJob(`/index/sync${buildQueryString({ full })}`, signal, receipt);
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
