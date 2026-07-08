import { describe, expect, it } from "vitest";

import { isNavItemActive } from "@/lib/navigation";

describe("isNavItemActive", () => {
  it("marks chat active on /chat", () => {
    expect(isNavItemActive("/chat", "/chat")).toBe(true);
  });

  it("marks chat active on source viewer routes", () => {
    expect(isNavItemActive("/sources/abc-123", "/chat")).toBe(true);
  });

  it("marks index active only on index routes", () => {
    expect(isNavItemActive("/index", "/index")).toBe(true);
    expect(isNavItemActive("/chat", "/index")).toBe(false);
  });

  it("supports nested paths for non-chat routes", () => {
    expect(isNavItemActive("/settings/advanced", "/settings")).toBe(true);
  });
});
