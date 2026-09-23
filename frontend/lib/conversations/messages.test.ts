import { describe, expect, it, beforeEach, vi } from "vitest";

import {
  deleteConversationMessages,
  getConversationMessages,
  saveConversationMessages,
  type StoredChatMessage,
} from "@/lib/conversations/messages";

type HistoryRequest = {
  question: string;
  conversation_id: string;
  history: { role: "user" | "assistant"; text: string }[];
  history_window_complete: boolean;
};

async function buildHistoryRequest(
  conversationId: string,
  question: string,
  options?: { beforeMessageId?: string },
): Promise<HistoryRequest> {
  // RED boundary: a pure request builder should read only the active chat's storage.
  const conversationMessages = await import("@/lib/conversations/messages");
  const builder = (conversationMessages as Record<string, unknown>).buildChatRequestForConversation;
  expect(builder).toBeTypeOf("function");
  return (builder as (
    id: string,
    currentQuestion: string,
    options?: { beforeMessageId?: string },
  ) => HistoryRequest)(conversationId, question, options);
}

function storedMessage(
  id: string,
  question: string,
  answer: string | null,
  status: "done" | "error" = "done",
): StoredChatMessage {
  return {
    id,
    question,
    status,
    answer,
    citations: [],
    retrievalCount: 0,
    error: status === "error" ? "Request failed" : null,
  };
}

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

describe("EXP-03 bounded current-conversation request", () => {
  beforeEach(() => {
    const store: Record<string, string> = {};
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (key: string) => store[key] ?? null,
        setItem: (key: string, value: string) => { store[key] = value; },
        removeItem: (key: string) => { delete store[key]; },
      },
    });
  });

  it("keeps prior user and completed assistant turns in chronological order", async () => {
    saveConversationMessages("chat-travel", [
      storedMessage("m1", "Where is the ferry terminal?", "At the east pier."),
      storedMessage("m2", "What time does it open?", "It opens at 08:00."),
    ]);

    const request = await buildHistoryRequest("chat-travel", "What did you last say?");

    expect(request).toEqual({
      question: "What did you last say?",
      conversation_id: "chat-travel",
      history: [
        { role: "user", text: "Where is the ferry terminal?" },
        { role: "assistant", text: "At the east pier." },
        { role: "user", text: "What time does it open?" },
        { role: "assistant", text: "It opens at 08:00." },
      ],
      history_window_complete: true,
    });
  });

  it("does not attach another chat's messages when switching conversations", async () => {
    saveConversationMessages("chat-a", [storedMessage("a1", "Tax deadline?", "April.")]);
    saveConversationMessages("chat-b", [storedMessage("b1", "Recipe time?", "30 minutes.")]);

    const request = await buildHistoryRequest("chat-b", "What did I just ask?");

    expect(request.conversation_id).toBe("chat-b");
    expect(request.history).toEqual([
      { role: "user", text: "Recipe time?" },
      { role: "assistant", text: "30 minutes." },
    ]);
  });

  it("sends empty complete history for a new conversation", async () => {
    const request = await buildHistoryRequest("new-chat", "What was my last question?");

    expect(request.history).toEqual([]);
    expect(request.history_window_complete).toBe(true);
    expect(request.conversation_id).toBe("new-chat");
  });

  it("includes failed user requests but not nonexistent assistant replies", async () => {
    saveConversationMessages("chat-images", [
      storedMessage("m1", "Describe my mountain image", null, "error"),
    ]);

    const request = await buildHistoryRequest("chat-images", "What did I ask?");

    expect(request.history).toEqual([
      { role: "user", text: "Describe my mountain image" },
    ]);
  });

  it("ignores loading placeholders that are not completed conversation turns", async () => {
    window.localStorage.setItem(
      "drivemind:conversation-messages:chat-pending",
      JSON.stringify([
        storedMessage("m1", "Find the museum hours", "Open until 18:00."),
        { id: "m2", question: "A pending question", status: "loading" },
      ]),
    );

    const request = await buildHistoryRequest("chat-pending", "What did you say?");

    expect(request.history).toEqual([
      { role: "user", text: "Find the museum hours" },
      { role: "assistant", text: "Open until 18:00." },
    ]);
  });

  it("excludes the regenerated turn and all later turns", async () => {
    saveConversationMessages("chat-meetings", [
      storedMessage("m1", "When is the meeting?", "Tuesday."),
      storedMessage("m2", "Who attends?", "The planning team."),
      storedMessage("m3", "Where?", "Room 4."),
    ]);

    const request = await buildHistoryRequest("chat-meetings", "Who attends?", {
      beforeMessageId: "m2",
    });

    expect(request.history).toEqual([
      { role: "user", text: "When is the meeting?" },
      { role: "assistant", text: "Tuesday." },
    ]);
  });

  it("keeps the newest eight messages and flags omitted older history", async () => {
    saveConversationMessages("chat-weather", Array.from({ length: 6 }, (_, index) =>
      storedMessage(`m${index}`, `Weather question ${index}`, `Weather answer ${index}`),
    ));

    const request = await buildHistoryRequest("chat-weather", "What did you say?");

    expect(request.history).toHaveLength(8);
    expect(request.history[0]).toEqual({ role: "user", text: "Weather question 2" });
    expect(request.history.at(-1)).toEqual({ role: "assistant", text: "Weather answer 5" });
    expect(request.history_window_complete).toBe(false);
  });

  it("does not truncate or substitute an older turn for oversized latest text", async () => {
    saveConversationMessages("chat-large", [
      storedMessage("m1", "Short question", "Short answer"),
      storedMessage("m2", "Another question", "x".repeat(8_001)),
    ]);

    const request = await buildHistoryRequest("chat-large", "Repeat your answer");

    expect(request.history).toEqual([]);
    expect(request.history_window_complete).toBe(false);
  });

  it("stops at the 24000-character budget without clipping a message", async () => {
    saveConversationMessages("chat-budget", [
      storedMessage("m1", "A".repeat(8_000), "B".repeat(8_000)),
      storedMessage("m2", "C".repeat(8_000), "D".repeat(8_000)),
    ]);

    const request = await buildHistoryRequest("chat-budget", "Repeat the last reply");

    expect(request.history.map((turn) => turn.text)).toEqual([
      "B".repeat(8_000), "C".repeat(8_000), "D".repeat(8_000),
    ]);
    expect(request.history_window_complete).toBe(false);
  });
});
