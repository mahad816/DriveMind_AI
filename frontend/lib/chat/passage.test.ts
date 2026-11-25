import { describe, expect, it } from "vitest";
import { answerForClipboard, locateSnippet } from "./passage";

describe("locateSnippet", () => {
  const text = "Totals. Allocated: 2,400. Spent to date: 1,630 (sensors 980,\ntransport 410). Remaining: 770.";
  it("finds an exact occurrence even when whitespace differs", () => {
    const parts = locateSnippet(text, "Spent to date: 1,630 (sensors 980, transport 410).");
    expect(parts?.match).toBe("Spent to date: 1,630 (sensors 980,\ntransport 410).");
    expect(parts!.before + parts!.match + parts!.after).toBe(text);
  });
  it("ignores a trailing ellipsis added to a shortened snippet", () => {
    expect(locateSnippet(text, "Spent to date: 1,630…")?.match).toBe("Spent to date: 1,630");
  });
  it("never highlights a near match or a different passage", () => {
    expect(locateSnippet(text, "Spent so far: 1,630 on sensors")).toBeNull();
    expect(locateSnippet(text, "Remaining")).toBeNull();
  });
  it("treats regex characters in snippets literally", () => {
    expect(locateSnippet("a (b) c [d] e*f", "(b) c [d] e*f")?.match).toBe("(b) c [d] e*f");
  });
});

describe("answerForClipboard", () => {
  it("removes markers and lists cited files once", () => {
    expect(answerForClipboard("About 770 is left [1]. Transects cost 520 [1][2].", ["Budget", "Budget", "Plan"]))
      .toBe("About 770 is left. Transects cost 520.\n\nSources:\n- Budget\n- Plan");
  });
});
