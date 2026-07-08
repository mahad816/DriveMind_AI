import { describe, expect, it, beforeEach, vi } from "vitest";

import {
  createConversation,
  groupConversationsByDate,
  listConversations,
  updateConversationTitle,
} from "@/lib/conversations/storage";

describe("conversation storage", () => {
  beforeEach(() => {
    const store: Record<string, string> = {};
    const localStorage = {
      getItem(key: string) {
        return store[key] ?? null;
      },
      setItem(key: string, value: string) {
        store[key] = value;
      },
      removeItem(key: string) {
        delete store[key];
      },
      clear() {
        Object.keys(store).forEach((key) => delete store[key]);
      },
    };

    vi.stubGlobal("window", { localStorage });
  });

  it("creates and lists conversations newest first", () => {
    const first = createConversation("First");
    const second = createConversation("Second");

    const list = listConversations();
    expect(list[0]?.id).toBe(second.id);
    expect(list[1]?.id).toBe(first.id);
  });

  it("updates conversation title", () => {
    const created = createConversation("Draft");
    const updated = updateConversationTitle(created.id, "Resume questions");
    expect(updated?.title).toBe("Resume questions");
    expect(listConversations()[0]?.title).toBe("Resume questions");
  });

  it("groups conversations by relative date labels", () => {
    const now = new Date("2026-07-08T12:00:00.000Z");
    const groups = groupConversationsByDate(
      [
        {
          id: "1",
          title: "Today chat",
          createdAt: now.toISOString(),
          updatedAt: now.toISOString(),
        },
        {
          id: "2",
          title: "Yesterday chat",
          createdAt: "2026-07-07T12:00:00.000Z",
          updatedAt: "2026-07-07T12:00:00.000Z",
        },
      ],
      now,
    );

    expect(groups.map((g) => g.label)).toEqual(["Today", "Yesterday"]);
  });
});
