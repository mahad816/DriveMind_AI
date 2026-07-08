import { describe, expect, it } from "vitest";

import { formatRelativeTime } from "@/lib/time/relative";

describe("formatRelativeTime", () => {
  it("returns minutes for recent updates", () => {
    const now = new Date("2026-07-08T12:00:00.000Z");
    const updatedAt = "2026-07-08T11:50:00.000Z";
    expect(formatRelativeTime(updatedAt, now)).toBe("10m ago");
  });

  it("returns short date for older updates", () => {
    const now = new Date("2026-07-08T12:00:00.000Z");
    const updatedAt = "2026-06-01T12:00:00.000Z";
    expect(formatRelativeTime(updatedAt, now)).toMatch(/Jun/);
  });
});
