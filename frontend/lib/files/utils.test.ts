import { describe, expect, it } from "vitest";

import { buildAskAboutFileHref, fileTypeIcon, fileTypeLabel, truncatePreview } from "@/lib/files/utils";

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

describe("file type label and icon for Office and Google types", () => {
  const pptx = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  const xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

  it("labels presentations and spreadsheets by what they are, not as documents", () => {
    expect(fileTypeLabel(pptx)).toBe("Presentation");
    expect(fileTypeLabel("application/vnd.google-apps.presentation")).toBe("Presentation");
    expect(fileTypeLabel(xlsx)).toBe("Spreadsheet");
    expect(fileTypeLabel(docx)).toBe("Document");
  });

  it("gives a presentation its own icon", () => {
    expect(fileTypeIcon(pptx)).not.toBe(fileTypeIcon(docx));
    expect(fileTypeIcon(pptx)).toBe(fileTypeIcon("application/vnd.google-apps.presentation"));
  });
});
