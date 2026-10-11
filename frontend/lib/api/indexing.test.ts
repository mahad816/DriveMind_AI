import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { buildVectorIndex, chunkDocuments, getPendingCounts, pollUntilJobDone } from "@/lib/api/indexing";
import { ApiError } from "@/lib/api/errors";
import type { DriveSyncStatusResponse, IndexingJobRead } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  apiFetch: vi.fn(),
  buildQueryString: (params: Record<string, string>) => "?" + new URLSearchParams(params).toString(),
}));

const FAILED_JOB: IndexingJobRead = {
  id: "job-failed",
  user_id: "user-1",
  status: "failed",
  started_at: "2026-09-19T10:00:00Z",
  completed_at: "2026-09-19T10:00:01Z",
  error: "3 files failed during ingestion",
  created_at: "2026-09-19T10:00:00Z",
  updated_at: "2026-09-19T10:00:01Z",
};

beforeEach(() => vi.resetAllMocks());

describe("pollUntilJobDone", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(apiFetch).mockResolvedValue({
      connected: true,
      job: FAILED_JOB,
    } satisfies DriveSyncStatusResponse);
  });

  it("throws on a failed job by default", async () => {
    await expect(
      pollUntilJobDone(FAILED_JOB.id, { intervalMs: 0, timeoutMs: 100 }),
    ).rejects.toMatchObject({ detail: FAILED_JOB.error });
  });

  it("returns a failed terminal job only when explicitly allowed", async () => {
    const result = await pollUntilJobDone(FAILED_JOB.id, {
      intervalMs: 0,
      timeoutMs: 100,
      allowFailed: true,
    });

    expect(result).toEqual(FAILED_JOB);
  });
});

it("polls the exact submitted ID without comparing browser time", async () => {
  vi.mocked(apiFetch).mockResolvedValue({
    connected: false,
    job: { ...FAILED_JOB, status: "completed", created_at: "1900-01-01T00:00:00Z" },
  });
  const result = await pollUntilJobDone(FAILED_JOB.id, { intervalMs: 0, timeoutMs: 100 });
  expect(result.id).toBe(FAILED_JOB.id);
  expect(apiFetch).toHaveBeenCalledWith("/index/status?job_id=job-failed");
});

it("refuses an unrelated latest job instead of treating it as completion", async () => {
  vi.mocked(apiFetch).mockResolvedValue({
    connected: true, job: { ...FAILED_JOB, id: "foreign-job", status: "completed" },
  });
  await expect(pollUntilJobDone(FAILED_JOB.id, { intervalMs: 0, timeoutMs: 100 }))
    .rejects.toMatchObject({ status: 503 });
});

it.each([401, 403, 404, 409, 503])("stops polling on HTTP %s", async (status) => {
  vi.mocked(apiFetch).mockRejectedValue(new ApiError(status, "unavailable"));
  await expect(pollUntilJobDone(FAILED_JOB.id, { intervalMs: 0, timeoutMs: 100 }))
    .rejects.toMatchObject({ status });
});

it("uses fresh session CSRF protection before each indexing submission", async () => {
  vi.mocked(apiFetch)
    .mockResolvedValueOnce({ csrf_token: "synthetic-a-csrf" })
    .mockResolvedValueOnce({ job_id: "a-job", status: "queued", message: "accepted" })
    .mockResolvedValueOnce({ csrf_token: "synthetic-b-csrf" })
    .mockResolvedValueOnce({ job_id: "b-job", status: "queued", message: "accepted" });
  await buildVectorIndex("file-a");
  await chunkDocuments("file-b");
  expect(apiFetch).toHaveBeenNthCalledWith(1, "/auth/session");
  expect(apiFetch).toHaveBeenNthCalledWith(2, "/index/build?file_id=file-a", {
    method: "POST", headers: { "X-CSRF-Token": "synthetic-a-csrf" },
  });
  expect(apiFetch).toHaveBeenNthCalledWith(3, "/auth/session");
  expect(apiFetch).toHaveBeenNthCalledWith(4, "/index/chunk?file_id=file-b", {
    method: "POST", headers: { "X-CSRF-Token": "synthetic-b-csrf" },
  });
});

it("does not POST if session inspection fails", async () => {
  vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "sign in"));
  await expect(buildVectorIndex()).rejects.toMatchObject({ status: 401 });
  expect(apiFetch).toHaveBeenCalledTimes(1);
});

it("does not POST with missing CSRF material", async () => {
  vi.mocked(apiFetch).mockResolvedValue({});
  await expect(buildVectorIndex()).rejects.toMatchObject({ status: 503 });
  expect(apiFetch).toHaveBeenCalledTimes(1);
});

it("does not treat a canceled job as successful partial ingestion", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ connected: false, job: { ...FAILED_JOB, status: "canceled" } });
  await expect(pollUntilJobDone(FAILED_JOB.id, {
    intervalMs: 0, timeoutMs: 100, allowFailed: true,
  })).rejects.toMatchObject({ status: 409 });
});


describe("authoritative pending counts", () => {
  it.each([
    undefined, null, {},
    { to_ingest: 0, to_chunk: 0, any_pending: false },
    ...["0", true, -1, 0.5, NaN, Infinity].map((count) => ({
      to_ingest: count, to_chunk: 0, to_build: 0, any_pending: false,
    })),
    { to_ingest: 0, to_chunk: 0, to_build: 0, any_pending: "false" },
    { to_ingest: 1, to_chunk: 0, to_build: 0, any_pending: false },
    { to_ingest: 0, to_chunk: 0, to_build: 0, any_pending: true },
  ])("rejects malformed/unavailable pending state %j", async (response) => {
    vi.mocked(apiFetch).mockResolvedValue(response);
    await expect(getPendingCounts()).rejects.toMatchObject({ status: 503 });
  });

  it.each([false, true])("accepts valid fresh counts (pending=%s)", async (any_pending) => {
    const response = { to_ingest: Number(any_pending), to_chunk: 0, to_build: 0, any_pending };
    vi.mocked(apiFetch).mockResolvedValue(response);
    await expect(getPendingCounts()).resolves.toEqual(response);
  });

  it("preserves typed transport errors", async () => {
    const error = new ApiError(401, "Session revoked");
    vi.mocked(apiFetch).mockRejectedValue(error);
    await expect(getPendingCounts()).rejects.toBe(error);
  });
});
