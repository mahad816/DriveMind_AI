import { describe, expect, it, vi, beforeEach } from "vitest";

import {
  buildVectorIndex,
  chunkDocuments,
  getPendingCounts,
  ingestDriveFiles,
  pollUntilJobDone,
  syncDriveMetadata,
} from "@/lib/api/indexing";
import { prepareKnowledge } from "@/lib/knowledge/prepare";

vi.mock("@/lib/api/indexing", () => ({
  syncDriveMetadata: vi.fn(),
  ingestDriveFiles: vi.fn(),
  chunkDocuments: vi.fn(),
  buildVectorIndex: vi.fn(),
  getPendingCounts: vi.fn(),
  pollUntilJobDone: vi.fn(),
}));

describe("prepareKnowledge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(syncDriveMetadata).mockResolvedValue({ status: "started", message: "ok" });
    vi.mocked(ingestDriveFiles).mockResolvedValue({ status: "started", message: "ok" });
    vi.mocked(chunkDocuments).mockResolvedValue({ status: "started", message: "ok" });
    vi.mocked(buildVectorIndex).mockResolvedValue({ status: "started", message: "ok" });
    vi.mocked(pollUntilJobDone).mockResolvedValue(undefined);
    vi.mocked(getPendingCounts).mockResolvedValue({
      to_ingest: 1,
      to_chunk: 1,
      to_build: 1,
      any_pending: true,
    });
  });

  it("runs sync, ingest, chunk, and build when files are pending", async () => {
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

  it("skips ingest/chunk/build when nothing is pending after sync", async () => {
    vi.mocked(getPendingCounts).mockResolvedValue({
      to_ingest: 0,
      to_chunk: 0,
      to_build: 0,
      any_pending: false,
    });

    await prepareKnowledge({});

    expect(syncDriveMetadata).toHaveBeenCalledTimes(1);
    expect(ingestDriveFiles).not.toHaveBeenCalled();
    expect(chunkDocuments).not.toHaveBeenCalled();
    expect(buildVectorIndex).not.toHaveBeenCalled();
  });
});
