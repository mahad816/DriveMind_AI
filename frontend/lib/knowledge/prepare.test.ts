import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildVectorIndex,
  chunkDocuments,
  getPendingCounts,
  ingestDriveFiles,
  pollUntilJobDone,
  syncDriveMetadata,
} from "@/lib/api/indexing";
import { ApiError } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/client";
import type { IndexingJobRead, PendingCountsResponse } from "@/lib/api/types";
import { prepareKnowledge } from "@/lib/knowledge/prepare";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

vi.mock("@/lib/api/indexing", () => ({
  syncDriveMetadata: vi.fn(),
  ingestDriveFiles: vi.fn(),
  chunkDocuments: vi.fn(),
  buildVectorIndex: vi.fn(),
  getPendingCounts: vi.fn(),
  pollUntilJobDone: vi.fn(),
}));

const PENDING: PendingCountsResponse = {
  to_ingest: 1,
  to_chunk: 1,
  to_build: 1,
  any_pending: true,
};

function job(status: "completed" | "failed", error: string | null = null): IndexingJobRead {
  return {
    id: `job-${status}`,
    user_id: "user-1",
    status,
    started_at: "2026-09-19T10:00:00Z",
    completed_at: "2026-09-19T10:00:01Z",
    error,
    created_at: "2026-09-19T10:00:00Z",
    updated_at: "2026-09-19T10:00:01Z",
  };
}

describe("prepareKnowledge", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(syncDriveMetadata).mockResolvedValue({ job_id: "syncDriveMetadata-id", status: "queued", message: "ok" });
    vi.mocked(ingestDriveFiles).mockResolvedValue({ job_id: "ingestDriveFiles-id", status: "queued", message: "ok" });
    vi.mocked(chunkDocuments).mockResolvedValue({ job_id: "chunkDocuments-id", status: "queued", message: "ok" });
    vi.mocked(buildVectorIndex).mockResolvedValue({ job_id: "buildVectorIndex-id", status: "queued", message: "ok" });
    vi.mocked(pollUntilJobDone).mockResolvedValue(job("completed"));
    vi.mocked(getPendingCounts).mockResolvedValue(PENDING);
  });

  it("rejects revoked-session pending reads after ingestion instead of reporting readiness", async () => {
    const error = new ApiError(401, "Session revoked");
    const progress: number[] = [];
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce({ to_ingest: 1, to_chunk: 0, to_build: 0, any_pending: true })
      .mockRejectedValueOnce(error);

    await expect(prepareKnowledge({
      onProgress: (state) => progress.push(state.progressPercent),
    })).rejects.toBe(error);
    expect(ingestDriveFiles).toHaveBeenCalledTimes(1);
    expect(chunkDocuments).not.toHaveBeenCalled();
    expect(buildVectorIndex).not.toHaveBeenCalled();
    expect(progress).not.toContain(100);
  });

  it("runs the unchanged all-success sequence without a warning", async () => {
    const progress: number[] = [];

    const result = await prepareKnowledge({
      onProgress: (state) => {
        progress.push(state.progressPercent);
      },
    });

    expect(result).toEqual({ warning: null });
    expect(syncDriveMetadata).toHaveBeenCalledTimes(1);
    expect(ingestDriveFiles).toHaveBeenCalledTimes(1);
    expect(chunkDocuments).toHaveBeenCalledTimes(1);
    expect(buildVectorIndex).toHaveBeenCalledTimes(1);
    expect(pollUntilJobDone).toHaveBeenNthCalledWith(2, "ingestDriveFiles-id", {
      timeoutMs: 180_000,
      allowFailed: true,
    });
    expect(vi.mocked(pollUntilJobDone).mock.calls.map(([id]) => id)).toEqual([
      "syncDriveMetadata-id", "ingestDriveFiles-id", "chunkDocuments-id", "buildVectorIndex-id",
    ]);
    expect(progress.at(-1)).toBe(100);
  });

  it("continues healthy work after partial ingestion and returns the original warning", async () => {
    vi.mocked(pollUntilJobDone)
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("failed", "15 of 60 files failed during ingestion."))
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("completed"));
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce(PENDING)
      .mockResolvedValueOnce({ to_ingest: 15, to_chunk: 9, to_build: 0, any_pending: true })
      .mockResolvedValueOnce({ to_ingest: 15, to_chunk: 0, to_build: 9, any_pending: true });

    const result = await prepareKnowledge();

    expect(result.warning).toBe("15 of 60 files failed during ingestion.");
    expect(chunkDocuments).toHaveBeenCalledTimes(1);
    expect(buildVectorIndex).toHaveBeenCalledTimes(1);
    expect(getPendingCounts).toHaveBeenCalledTimes(3);
  });

  it("runs build when partial ingestion leaves only build work", async () => {
    vi.mocked(pollUntilJobDone)
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("failed", "one file failed during ingestion"))
      .mockResolvedValueOnce(job("completed"));
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce(PENDING)
      .mockResolvedValueOnce({ to_ingest: 1, to_chunk: 0, to_build: 2, any_pending: true });

    const result = await prepareKnowledge();

    expect(result.warning).toBe("one file failed during ingestion");
    expect(chunkDocuments).not.toHaveBeenCalled();
    expect(buildVectorIndex).toHaveBeenCalledTimes(1);
  });

  it("refreshes pending after chunking before deciding to build", async () => {
    vi.mocked(pollUntilJobDone)
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("failed", "one file failed during ingestion"))
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("completed"));
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce(PENDING)
      .mockResolvedValueOnce({ to_ingest: 1, to_chunk: 2, to_build: 0, any_pending: true })
      .mockResolvedValueOnce({ to_ingest: 1, to_chunk: 0, to_build: 2, any_pending: true });

    await prepareKnowledge();

    expect(chunkDocuments).toHaveBeenCalledTimes(1);
    expect(getPendingCounts).toHaveBeenCalledTimes(3);
    expect(buildVectorIndex).toHaveBeenCalledTimes(1);
  });

  it("surfaces the ingestion failure when no downstream work exists", async () => {
    const ingestionError = "all files failed during ingestion";
    vi.mocked(pollUntilJobDone)
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("failed", ingestionError));
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce(PENDING)
      .mockResolvedValueOnce({ to_ingest: 9, to_chunk: 0, to_build: 0, any_pending: true });

    await expect(prepareKnowledge()).rejects.toMatchObject({ detail: ingestionError });
    expect(chunkDocuments).not.toHaveBeenCalled();
    expect(buildVectorIndex).not.toHaveBeenCalled();
  });

  it("preserves the pending API error when a failed ingestion refresh fails", async () => {
    const ingestionError = "15 files failed during ingestion";
    vi.mocked(pollUntilJobDone)
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("failed", ingestionError));
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce(PENDING)
      .mockRejectedValueOnce(new ApiError(503, "pending unavailable"));

    await expect(prepareKnowledge()).rejects.toMatchObject({ status: 503, detail: "pending unavailable" });
    expect(chunkDocuments).not.toHaveBeenCalled();
    expect(buildVectorIndex).not.toHaveBeenCalled();
  });

  it("keeps a chunk failure fatal after partial ingestion", async () => {
    vi.mocked(pollUntilJobDone)
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("failed", "ingestion warning"))
      .mockRejectedValueOnce(new ApiError(500, "chunk failed"));
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce(PENDING)
      .mockResolvedValueOnce({ to_ingest: 1, to_chunk: 2, to_build: 0, any_pending: true });

    await expect(prepareKnowledge()).rejects.toMatchObject({ detail: "chunk failed" });
    expect(buildVectorIndex).not.toHaveBeenCalled();
  });

  it("keeps a build failure fatal after partial ingestion", async () => {
    vi.mocked(pollUntilJobDone)
      .mockResolvedValueOnce(job("completed"))
      .mockResolvedValueOnce(job("failed", "ingestion warning"))
      .mockRejectedValueOnce(new ApiError(500, "build failed"));
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce(PENDING)
      .mockResolvedValueOnce({ to_ingest: 1, to_chunk: 0, to_build: 2, any_pending: true });

    await expect(prepareKnowledge()).rejects.toMatchObject({ detail: "build failed" });
    expect(buildVectorIndex).toHaveBeenCalledTimes(1);
  });

  it("skips ingest, chunk, and build when nothing is pending after sync", async () => {
    vi.mocked(getPendingCounts).mockResolvedValue({
      to_ingest: 0,
      to_chunk: 0,
      to_build: 0,
      any_pending: false,
    });

    const result = await prepareKnowledge({});

    expect(result).toEqual({ warning: null });
    expect(syncDriveMetadata).toHaveBeenCalledTimes(1);
    expect(ingestDriveFiles).not.toHaveBeenCalled();
    expect(chunkDocuments).not.toHaveBeenCalled();
    expect(buildVectorIndex).not.toHaveBeenCalled();
  });
  it.each([401, 403, 500, 503, "network"])(
    "stops and reports a %s pending-read failure at each decision boundary",
    async (failure) => {
      for (const boundary of ["scan", "ingest", "chunk"] as const) {
        vi.mocked(getPendingCounts).mockReset();
        vi.mocked(chunkDocuments).mockClear();
        vi.mocked(buildVectorIndex).mockClear();
        vi.mocked(ingestDriveFiles).mockClear();
        const error = typeof failure === "number"
          ? new ApiError(failure, "Pending read failed") : new TypeError("Network unavailable");
        const progress: { progressPercent: number; error: string | null }[] = [];
        if (boundary !== "scan") vi.mocked(getPendingCounts).mockResolvedValueOnce(PENDING);
        if (boundary === "chunk") vi.mocked(getPendingCounts).mockResolvedValueOnce(PENDING);
        vi.mocked(getPendingCounts).mockRejectedValueOnce(error);
        await expect(prepareKnowledge({ onProgress: (state) => progress.push(state) }))
          .rejects.toBe(error);
        expect(progress.some((state) => state.progressPercent === 100)).toBe(false);
        expect(progress.at(-1)?.error).toBe(error.message);
        expect(buildVectorIndex).not.toHaveBeenCalled();
        if (boundary !== "chunk") expect(chunkDocuments).not.toHaveBeenCalled();
        if (boundary === "scan") expect(ingestDriveFiles).not.toHaveBeenCalled();
      }
    },
  );

  it("uses fresh downstream counts after initially zero chunk/build counts", async () => {
    vi.mocked(getPendingCounts)
      .mockResolvedValueOnce({ to_ingest: 1, to_chunk: 0, to_build: 0, any_pending: true })
      .mockResolvedValueOnce({ to_ingest: 0, to_chunk: 1, to_build: 0, any_pending: true })
      .mockResolvedValueOnce({ to_ingest: 0, to_chunk: 0, to_build: 1, any_pending: true });
    await expect(prepareKnowledge()).resolves.toEqual({ warning: null });
    expect(chunkDocuments).toHaveBeenCalledTimes(1);
    expect(buildVectorIndex).toHaveBeenCalledTimes(1);
  });

  it.each([undefined, null, {}, { to_ingest: 0, to_chunk: 0, to_build: 0 }])(
    "cannot report readiness after a malformed pending response %j",
    async (response) => {
      const actual = await vi.importActual<typeof import("@/lib/api/indexing")>("@/lib/api/indexing");
      vi.mocked(getPendingCounts).mockImplementation(actual.getPendingCounts);
      vi.mocked(apiFetch)
        .mockResolvedValueOnce({ to_ingest: 1, to_chunk: 0, to_build: 0, any_pending: true })
        .mockResolvedValueOnce(response);
      const progress: number[] = [];
      await expect(prepareKnowledge({ onProgress: (state) => progress.push(state.progressPercent) }))
        .rejects.toMatchObject({ status: 503 });
      expect(chunkDocuments).not.toHaveBeenCalled();
      expect(buildVectorIndex).not.toHaveBeenCalled();
      expect(progress).not.toContain(100);
    },
  );

});

it("does not continue preparation or report readiness after a known account transition", async () => {
  const { invalidateSessionRequests } = await import("@/lib/api/session-events");
  vi.resetAllMocks();
  vi.mocked(syncDriveMetadata).mockResolvedValue({ job_id: "sync-a", status: "queued", message: "accepted" });
  vi.mocked(pollUntilJobDone).mockImplementationOnce(async () => {
    invalidateSessionRequests();
    return job("completed");
  });
  const progress: number[] = [];
  await expect(prepareKnowledge({ onProgress: value => progress.push(value.progressPercent) })).rejects.toMatchObject({ status: 401 });
  expect(getPendingCounts).not.toHaveBeenCalled();
  expect(ingestDriveFiles).not.toHaveBeenCalled();
  expect(chunkDocuments).not.toHaveBeenCalled();
  expect(buildVectorIndex).not.toHaveBeenCalled();
  expect(progress).not.toContain(100);
});
