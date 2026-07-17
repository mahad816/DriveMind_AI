import { describe, expect, it, beforeEach, vi } from "vitest";

import { saveConversationMessages } from "@/lib/conversations/messages";
import {
  createConversation,
  findEmptyDraftConversation,
  getOrCreateDraftConversation,
  groupConversationsByDate,
  listConversations,
  pruneEmptyDraftConversations,
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

  it("reuses an empty New chat draft instead of creating duplicates", () => {
    const first = getOrCreateDraftConversation();
    const second = getOrCreateDraftConversation();
    expect(second.id).toBe(first.id);
    expect(listConversations()).toHaveLength(1);
    expect(findEmptyDraftConversation()?.id).toBe(first.id);
  });

  it("prunes empty New chat drafts but keeps chats with messages", () => {
    const empty = createConversation();
    const titled = createConversation("Resume questions");
    const withMessages = createConversation();
    saveConversationMessages(withMessages.id, [
      {
        id: "m1",
        question: "Hello",
        status: "done",
        answer: "Hi",
        citations: [],
        retrievalCount: 0,
        error: null,
      },
    ]);

    const removed = pruneEmptyDraftConversations();
    expect(removed).toBe(1);
    const ids = listConversations().map((c) => c.id);
    expect(ids).toContain(titled.id);
    expect(ids).toContain(withMessages.id);
    expect(ids).not.toContain(empty.id);
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
