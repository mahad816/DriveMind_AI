import { describe, expect, it } from "vitest";

import { formatSourceCount } from "@/lib/chat/source-label";
import type { CitationItem } from "@/lib/api/types";

function citation(fileId: string, chunkId: string, filename = "notes.txt"): CitationItem {
  return {
    chunk_id: chunkId,
    drive_file_id: fileId,
    filename,
    snippet: "A cited passage",
    score: null,
  };
}

describe("user-facing cited-source count", () => {
  it("counts two cited files", () => {
    expect(formatSourceCount(2, [citation("file-a", "a1"), citation("file-b", "b1")]))
      .toBe("Sources · 2");
  });

  it("counts two passages from the same file as one cited file", () => {
    expect(formatSourceCount(2, [citation("file-a", "a1"), citation("file-a", "a2")]))
      .toBe("Sources · 1");
  });

  it("counts distinct file IDs across three cited passages", () => {
    expect(formatSourceCount(3, [
      citation("file-a", "a1"),
      citation("file-a", "a2"),
      citation("file-b", "b1"),
    ])).toBe("Sources · 2");
  });

  it("does not confuse retrieved chunks with cited files", () => {
    expect(formatSourceCount(8, [citation("file-a", "a1")])).toBe("Sources · 1");
  });

  it("does not claim uncited retrieved chunks are sources", () => {
    expect(formatSourceCount(8, [])).toBe("");
    expect(formatSourceCount(0, [])).toBe("");
  });

  it("uses file ID rather than filename as identity", () => {
    expect(formatSourceCount(2, [
      citation("file-a", "a1", "report.txt"),
      citation("file-b", "b1", "report.txt"),
    ])).toBe("Sources · 2");
  });
});
