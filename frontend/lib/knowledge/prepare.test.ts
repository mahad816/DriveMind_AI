import { describe, expect, it, vi, beforeEach } from "vitest";

import {
  buildVectorIndex,
  chunkDocuments,
  ingestDriveFiles,
  syncDriveMetadata,
} from "@/lib/api/indexing";
import { prepareKnowledge } from "@/lib/knowledge/prepare";

vi.mock("@/lib/api/indexing", () => ({
  syncDriveMetadata: vi.fn(),
  ingestDriveFiles: vi.fn(),
  chunkDocuments: vi.fn(),
  buildVectorIndex: vi.fn(),
}));

describe("prepareKnowledge", () => {
  beforeEach(() => {
    vi.mocked(syncDriveMetadata).mockResolvedValue({
      job_id: "1",
      user_id: "u",
      mode: "incremental",
      created: 1,
      updated: 0,
      unchanged: 0,
      removed: 0,
      total_seen: 1,
      message: "ok",
    });
    vi.mocked(ingestDriveFiles).mockResolvedValue({
      job_id: "2",
      user_id: "u",
      ingested: 1,
      unchanged: 0,
      failed: 0,
      skipped: 0,
      total: 1,
      message: "ok",
    });
    vi.mocked(chunkDocuments).mockResolvedValue({
      job_id: "3",
      user_id: "u",
      chunked: 1,
      unchanged: 0,
      skipped: 0,
      total: 1,
      message: "ok",
    });
    vi.mocked(buildVectorIndex).mockResolvedValue({
      job_id: "4",
      user_id: "u",
      embedded: 1,
      unchanged: 0,
      skipped: 0,
      failed: 0,
      removed: 0,
      total: 1,
      message: "ok",
    });
  });

  it("runs sync, ingest, chunk, and build in order", async () => {
    const progress: number[] = [];

    await prepareKnowledge({
      onProgress: (state) => {
        progress.push(state.progressPercent);
      },
    });

    expect(syncDriveMetadata).toHaveBeenCalledTimes(1);
    expect(ingestDriveFiles).toHaveBeenCalledTimes(1);
    expect(chunkDocuments).toHaveBeenCalledTimes(1);
    expect(buildVectorIndex).toHaveBeenCalledTimes(1);
    expect(progress.at(-1)).toBe(100);
  });
});
