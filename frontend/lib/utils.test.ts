import { expect, it } from "vitest";
import { cn } from "./utils";

it("keeps a text colour next to a custom font size (regression: invisible primary button label)", () => {
  expect(cn("text-label text-archive-ink", "text-body")).toBe("text-archive-ink text-body");
  expect(cn("text-ink", "text-graphite")).toBe("text-graphite");
});
