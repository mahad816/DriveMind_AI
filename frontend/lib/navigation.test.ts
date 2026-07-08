import { describe, expect, it } from "vitest";

import {
  isChatRoute,
  isConversationActive,
  isNewChatActive,
  isUtilityNavActive,
} from "@/lib/navigation";

describe("navigation helpers", () => {
  it("detects chat routes including sources", () => {
    expect(isChatRoute("/chat")).toBe(true);
    expect(isChatRoute("/chat/abc-123")).toBe(true);
    expect(isChatRoute("/sources/chunk-1")).toBe(true);
    expect(isChatRoute("/files")).toBe(false);
  });

  it("marks new chat active only on /chat", () => {
    expect(isNewChatActive("/chat")).toBe(true);
    expect(isNewChatActive("/chat/abc")).toBe(false);
  });

  it("marks conversation active on /chat/[id]", () => {
    expect(isConversationActive("/chat/abc-123", "abc-123")).toBe(true);
    expect(isConversationActive("/chat/other", "abc-123")).toBe(false);
  });

  it("marks files active on nested file routes", () => {
    expect(isUtilityNavActive("/files", "/files")).toBe(true);
    expect(isUtilityNavActive("/files/abc", "/files")).toBe(true);
    expect(isUtilityNavActive("/chat", "/files")).toBe(false);
  });

  it("marks settings active on nested settings routes", () => {
    expect(isUtilityNavActive("/settings", "/settings")).toBe(true);
    expect(isUtilityNavActive("/settings/advanced", "/settings")).toBe(true);
  });
});
