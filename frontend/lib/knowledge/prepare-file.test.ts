import { beforeEach, expect, it, vi } from "vitest";
import { ingestDriveFiles, chunkDocuments, buildVectorIndex, pollUntilJobDone } from "@/lib/api/indexing";
import { prepareSingleFile } from "@/lib/knowledge/prepare-file";
import { ApiError } from "@/lib/api/errors";

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

it.each([401, 403, 503, "network"])("stops file preparation on a %s stage failure", async (status) => {
  for (const boundary of ["ingest", "chunk"] as const) {
    vi.resetAllMocks();
    vi.mocked(ingestDriveFiles).mockResolvedValue({ job_id: "ingest-id", status: "queued", message: "accepted" });
    vi.mocked(chunkDocuments).mockResolvedValue({ job_id: "chunk-id", status: "queued", message: "accepted" });
    const error = typeof status === "number" ? new ApiError(status, "Unavailable") : new TypeError("Network unavailable");
    if (boundary === "chunk") vi.mocked(pollUntilJobDone).mockResolvedValueOnce({
      id: "ingest-id", user_id: "owned-user", status: "completed", error: null,
      started_at: null, completed_at: null,
      created_at: "2026-10-12T00:00:00Z", updated_at: "2026-10-12T00:00:00Z",
    });
    vi.mocked(pollUntilJobDone).mockRejectedValueOnce(error);
    await expect(prepareSingleFile("owned-file")).rejects.toBe(error);
    expect(buildVectorIndex).not.toHaveBeenCalled();
    if (boundary === "ingest") expect(chunkDocuments).not.toHaveBeenCalled();
  }
});
