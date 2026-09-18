import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { pollUntilJobDone } from "@/lib/api/indexing";
import type { DriveSyncStatusResponse, IndexingJobRead } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  apiFetch: vi.fn(),
  buildQueryString: vi.fn(() => ""),
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

describe("pollUntilJobDone", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiFetch).mockResolvedValue({
      connected: true,
      job: FAILED_JOB,
    } satisfies DriveSyncStatusResponse);
  });

  it("throws on a failed job by default", async () => {
    await expect(
      pollUntilJobDone(new Date(0), { intervalMs: 0, timeoutMs: 100 }),
    ).rejects.toMatchObject({ detail: FAILED_JOB.error });
  });

  it("returns a failed terminal job only when explicitly allowed", async () => {
    const result = await pollUntilJobDone(new Date(0), {
      intervalMs: 0,
      timeoutMs: 100,
      allowFailed: true,
    });

    expect(result).toEqual(FAILED_JOB);
  });
});
