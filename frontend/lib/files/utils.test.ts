import { describe, expect, it } from "vitest";

import { buildAskAboutFileHref, truncatePreview } from "@/lib/files/utils";

describe("file utils", () => {
  it("builds ask-about href with encoded file name", () => {
    expect(buildAskAboutFileHref({ name: "Resume 2025.pdf" })).toBe(
      "/chat?ask=Tell%20me%20about%20%22Resume%202025.pdf%22",
    );
  });

  it("truncates long preview text", () => {
    const long = "a".repeat(500);
    const result = truncatePreview(long, 100);
    expect(result.length).toBe(101);
    expect(result.endsWith("…")).toBe(true);
  });
});
