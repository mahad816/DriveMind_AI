import { describe, expect, it } from "vitest";

import { buildFollowUpSuggestions } from "@/lib/chat/follow-ups";
import type { CitationItem } from "@/lib/api/types";

const citation = (filename: string): CitationItem => ({
  chunk_id: "chunk-1",
  drive_file_id: "drive-1",
  filename,
  snippet: "snippet",
  score: 0.9,
});

describe("buildFollowUpSuggestions", () => {
  it("suggests file follow-up when citations exist", () => {
    const suggestions = buildFollowUpSuggestions(
      "Tell me about resume",
      "Short answer",
      [citation("resume.pdf")],
    );

    expect(suggestions[0]).toContain("resume.pdf");
  });

  it("suggests evidence question for multiple citations", () => {
    const suggestions = buildFollowUpSuggestions(
      "Compare files",
      "Answer",
      [citation("a.pdf"), citation("b.pdf")],
    );

    expect(suggestions.some((s) => s.includes("strongest evidence"))).toBe(true);
  });

  it("caps suggestions at three", () => {
    const longAnswer = "x".repeat(500);
    const suggestions = buildFollowUpSuggestions(
      "how many files",
      longAnswer,
      [citation("a.pdf"), citation("b.pdf")],
    );

    expect(suggestions.length).toBeLessThanOrEqual(3);
  });
});
