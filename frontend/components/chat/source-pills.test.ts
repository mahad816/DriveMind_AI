import { describe, expect, it } from "vitest";

import { uniqueCitationsByFilename } from "@/components/chat/source-pills";
import type { CitationItem } from "@/lib/api/types";

function citation(filename: string, chunkId: string): CitationItem {
  return {
    chunk_id: chunkId,
    drive_file_id: `drive-${chunkId}`,
    filename,
    snippet: "snippet",
    score: 0.9,
  };
}

describe("uniqueCitationsByFilename", () => {
  it("keeps the first citation per filename", () => {
    const result = uniqueCitationsByFilename([
      citation("spec.pdf", "chunk-1"),
      citation("spec.pdf", "chunk-2"),
      citation("notes.docx", "chunk-3"),
    ]);

    expect(result).toHaveLength(2);
    expect(result[0]?.chunk_id).toBe("chunk-1");
    expect(result[1]?.chunk_id).toBe("chunk-3");
  });

  it("dedupes case-insensitively", () => {
    const result = uniqueCitationsByFilename([
      citation("Resume.PDF", "chunk-1"),
      citation("resume.pdf", "chunk-2"),
    ]);

    expect(result).toHaveLength(1);
    expect(result[0]?.chunk_id).toBe("chunk-1");
  });
});
