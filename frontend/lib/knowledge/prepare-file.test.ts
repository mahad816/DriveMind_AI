import { beforeEach, expect, it, vi } from "vitest";
import { ingestDriveFiles, chunkDocuments, buildVectorIndex, pollUntilJobDone } from "@/lib/api/indexing";
import { prepareSingleFile } from "@/lib/knowledge/prepare-file";

vi.mock("@/lib/api/indexing", () => ({
  ingestDriveFiles: vi.fn(), chunkDocuments: vi.fn(),
  buildVectorIndex: vi.fn(), pollUntilJobDone: vi.fn(),
}));
beforeEach(() => vi.resetAllMocks());

it("prepares one internal file sequentially using each accepted job ID", async () => {
  vi.mocked(ingestDriveFiles).mockResolvedValue({ job_id: "ingest-id", status: "queued", message: "accepted" });
  vi.mocked(chunkDocuments).mockResolvedValue({ job_id: "chunk-id", status: "queued", message: "accepted" });
  vi.mocked(buildVectorIndex).mockResolvedValue({ job_id: "build-id", status: "queued", message: "accepted" });
  await prepareSingleFile("owned-file");
  expect(ingestDriveFiles).toHaveBeenCalledWith("owned-file");
  expect(chunkDocuments).toHaveBeenCalledWith("owned-file");
  expect(buildVectorIndex).toHaveBeenCalledWith("owned-file");
  expect(vi.mocked(pollUntilJobDone).mock.calls.map(([id]) => id))
    .toEqual(["ingest-id", "chunk-id", "build-id"]);
});

it("does not advance stages after admission failure", async () => {
  vi.mocked(ingestDriveFiles).mockRejectedValue(new Error("unavailable"));
  await expect(prepareSingleFile("owned-file")).rejects.toThrow("unavailable");
  expect(chunkDocuments).not.toHaveBeenCalled();
  expect(buildVectorIndex).not.toHaveBeenCalled();
  expect(pollUntilJobDone).not.toHaveBeenCalled();
});
