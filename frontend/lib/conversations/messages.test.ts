import { describe, expect, it, beforeEach, vi } from "vitest";

import {
  deleteConversationMessages,
  getConversationMessages,
  saveConversationMessages,
} from "@/lib/conversations/messages";

describe("conversation messages storage", () => {
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

  it("saves and loads messages for a conversation", () => {
    saveConversationMessages("conv-1", [
      {
        id: "m1",
        question: "Tell me about Far611",
        status: "done",
        answer: "Cherry blossoms",
        citations: [],
        retrievalCount: 1,
        error: null,
      },
    ]);

    const loaded = getConversationMessages("conv-1");
    expect(loaded).toHaveLength(1);
    expect(loaded[0].question).toBe("Tell me about Far611");
  });

  it("deletes messages with the conversation", () => {
    saveConversationMessages("conv-2", [
      {
        id: "m1",
        question: "Hi",
        status: "done",
        answer: "Hello",
        citations: [],
        retrievalCount: 0,
        error: null,
      },
    ]);

    deleteConversationMessages("conv-2");
    expect(getConversationMessages("conv-2")).toEqual([]);
  });
});
