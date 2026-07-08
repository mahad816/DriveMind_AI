import { describe, expect, it } from "vitest";

import { formatSourceCount } from "@/lib/chat/source-label";
import type { CitationItem } from "@/lib/api/types";

describe("formatSourceCount", () => {
  it("handles zero sources", () => {
    expect(formatSourceCount(0, [])).toBe("No sources found");
  });

  it("uses singular for one source", () => {
    expect(
      formatSourceCount(1, [
        {
          chunk_id: "1",
          drive_file_id: "d1",
          filename: "resume.pdf",
          snippet: "",
          score: 1,
        },
      ]),
    ).toBe("Based on 1 source");
  });

  it("deduplicates files in count", () => {
    const citations: CitationItem[] = [
      {
        chunk_id: "1",
        drive_file_id: "d1",
        filename: "resume.pdf",
        snippet: "",
        score: 1,
      },
      {
        chunk_id: "2",
        drive_file_id: "d1",
        filename: "resume.pdf",
        snippet: "",
        score: 0.9,
      },
    ];

    expect(formatSourceCount(2, citations)).toBe("Based on 2 sources");
  });
});
