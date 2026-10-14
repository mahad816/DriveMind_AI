import { describe, expect, it } from "vitest";

import { buildAskAboutFileHref, truncatePreview } from "@/lib/files/utils";

describe("file utils", () => {
  it("normal navigation never includes private file names", () => {
    expect(buildAskAboutFileHref({ name: "Resume 2025.pdf" })).toBe(
      "/chat",
    );
  });

  it("truncates long preview text", () => {
    const long = "a".repeat(500);
    const result = truncatePreview(long, 100);
    expect(result.length).toBe(101);
    expect(result.endsWith("…")).toBe(true);
  });
});
