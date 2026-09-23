import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInterface } from "@/components/chat/chat-interface";
import { askQuestion } from "@/lib/api/chat";
import type { ChatResponse } from "@/lib/api/types";
import { getConversationMessages, saveConversationMessages } from "@/lib/conversations/messages";
import {
  createConversation,
  deleteConversation,
  getConversation,
} from "@/lib/conversations/storage";

vi.mock("next/navigation", () => {
  const router = { push: vi.fn(), replace: vi.fn() };
  const searchParams = new URLSearchParams();
  return { useRouter: () => router, useSearchParams: () => searchParams };
});
vi.mock("@/lib/api/chat", () => ({ askQuestion: vi.fn() }));
vi.mock("@/lib/hooks/use-connection-status", () => {
  const value = { data: { connected: true }, error: null, refetch: vi.fn() };
  return { useConnectionStatus: () => value };
});
vi.mock("@/lib/hooks/use-knowledge-status", () => ({
  useKnowledgeStatus: () => ({ needsConnect: false, needsPrepare: false }),
}));
vi.mock("@/lib/hooks/use-conversations", () => {
  const value = {
    startNewConversation: vi.fn(),
    renameConversation: vi.fn(),
    bumpConversation: vi.fn(),
  };
  return { useConversations: () => value };
});
vi.mock("@/lib/hooks/use-chat-shortcuts", () => ({ useChatShortcuts: vi.fn() }));
vi.mock("@/components/chat/composer-dock", () => ({
  ComposerDock: ({
    value,
    onChange,
    onSubmit,
    isLoading,
  }: {
    value: string;
    onChange: (value: string) => void;
    onSubmit: () => void;
    isLoading: boolean;
  }) => (
    <div>
      <input aria-label="Question" value={value} onChange={(event) => onChange(event.target.value)} />
      <button type="button" onClick={onSubmit} disabled={isLoading}>Send</button>
    </div>
  ),
}));
vi.mock("@/components/chat/message-thread", () => ({
  MessageThread: ({
    messages,
    onRetry,
  }: {
    messages: {
      id: string;
      question: string;
      status: string;
      response?: { answer: string };
    }[];
    onRetry: (id: string, question: string) => void;
  }) => (
    <div>
      {messages.map((message) => (
        <div key={message.id} data-testid={`turn-${message.id}`}>
          <span>{message.question}</span>
          <span>{message.response?.answer ?? message.status}</span>
          <button type="button" onClick={() => onRetry(message.id, message.question)}>
            Retry {message.id}
          </button>
        </div>
      ))}
    </div>
  ),
}));
vi.mock("@/components/chat/empty-state-hero", () => ({
  EmptyStateHero: () => <div>No messages</div>,
}));
vi.mock("@/components/chat/source-panel", () => ({ SourcePanel: () => null }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function answer(text: string): ChatResponse {
  return {
    query_id: "result-id",
    user_id: "user-id",
    answer: text,
    citations: [],
    retrieval_count: 0,
    message: text,
  };
}

function send(question: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Question" }), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("in-flight conversation ownership", () => {
  beforeEach(() => {
    const store: Record<string, string> = {};
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => store[key] ?? null,
        setItem: (key: string, value: string) => { store[key] = value; },
        removeItem: (key: string) => { delete store[key]; },
        clear: () => { Object.keys(store).forEach((key) => delete store[key]); },
      },
    });
    vi.mocked(askQuestion).mockReset();
  });
  afterEach(cleanup);

  it("keeps a pending A turn and its eventual answer in A after switching to B", async () => {
    const chatA = createConversation("Travel");
    const chatB = createConversation("Cooking");
    const pending = deferred<ChatResponse>();
    vi.mocked(askQuestion).mockReturnValueOnce(pending.promise);
    const view = render(<ChatInterface conversationId={chatA.id} />);

    send("Where does the ferry depart?");
    await waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getConversationMessages(chatA.id)).toHaveLength(1));
    expect(getConversationMessages(chatA.id)[0]).toMatchObject({
      question: "Where does the ferry depart?",
      status: "pending",
    });

    view.rerender(<ChatInterface conversationId={chatB.id} />);
    await screen.findByText("No messages");
    await act(async () => pending.resolve(answer("From the north pier.")));

    expect(getConversationMessages(chatA.id)).toMatchObject([
      { question: "Where does the ferry depart?", status: "done", answer: "From the north pier." },
    ]);
    expect(getConversationMessages(chatB.id)).toEqual([]);
    expect(screen.queryByText("From the north pier.")).not.toBeInTheDocument();
  });

  it("updates A once if the user returns before A finishes", async () => {
    const chatA = createConversation("Garden");
    const chatB = createConversation("Schedule");
    const pending = deferred<ChatResponse>();
    vi.mocked(askQuestion).mockReturnValueOnce(pending.promise);
    const view = render(<ChatInterface conversationId={chatA.id} />);

    send("When does the garden open?");
    await waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(1));
    view.unmount();
    const reopenedView = render(<ChatInterface conversationId={chatB.id} />);
    reopenedView.rerender(<ChatInterface conversationId={chatA.id} />);
    expect(await screen.findByText("When does the garden open?")).toBeInTheDocument();
    await act(async () => pending.resolve(answer("At nine.")));

    expect(await screen.findByText("At nine.")).toBeInTheDocument();
    expect(getConversationMessages(chatA.id)).toHaveLength(1);
    expect(getConversationMessages(chatA.id)[0]).toMatchObject({ status: "done", answer: "At nine." });
    reopenedView.rerender(<ChatInterface conversationId={chatB.id} />);
    reopenedView.rerender(<ChatInterface conversationId={chatA.id} />);
    expect(await screen.findByText("At nine.")).toBeInTheDocument();
  });

  it("allows A and B to settle out of order without crossing ownership", async () => {
    const chatA = createConversation("Maps");
    const chatB = createConversation("Music");
    const pendingA = deferred<ChatResponse>();
    const pendingB = deferred<ChatResponse>();
    vi.mocked(askQuestion).mockReturnValueOnce(pendingA.promise).mockReturnValueOnce(pendingB.promise);
    const view = render(<ChatInterface conversationId={chatA.id} />);

    send("Where is the station?");
    await waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(1));
    view.rerender(<ChatInterface conversationId={chatB.id} />);
    send("Which album is listed?");
    await waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(2));
    await act(async () => pendingB.resolve(answer("The blue album.")));
    await act(async () => pendingA.resolve(answer("Beside the market.")));

    expect(getConversationMessages(chatA.id)).toMatchObject([
      { question: "Where is the station?", answer: "Beside the market." },
    ]);
    expect(getConversationMessages(chatB.id)).toMatchObject([
      { question: "Which album is listed?", answer: "The blue album." },
    ]);
  });

  it("records an error only in the originating chat after a switch", async () => {
    const chatA = createConversation("Archive");
    const chatB = createConversation("Notes");
    const pending = deferred<ChatResponse>();
    vi.mocked(askQuestion).mockReturnValueOnce(pending.promise);
    const view = render(<ChatInterface conversationId={chatA.id} />);

    send("Open the meeting agenda");
    await waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(1));
    view.rerender(<ChatInterface conversationId={chatB.id} />);
    await act(async () => pending.reject(new Error("Request failed")));

    expect(getConversationMessages(chatA.id)).toMatchObject([
      { question: "Open the meeting agenda", status: "error", error: "Request failed" },
    ]);
    expect(getConversationMessages(chatB.id)).toEqual([]);
  });

  it("does not recreate a deleted origin when its response arrives", async () => {
    const chatA = createConversation("Temporary");
    const chatB = createConversation("Permanent");
    const pending = deferred<ChatResponse>();
    vi.mocked(askQuestion).mockReturnValueOnce(pending.promise);
    const view = render(<ChatInterface conversationId={chatA.id} />);

    send("Find the sketch");
    await waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getConversationMessages(chatA.id)[0]?.status).toBe("pending"));
    view.rerender(<ChatInterface conversationId={chatB.id} />);
    deleteConversation(chatA.id);
    await act(async () => pending.resolve(answer("The sketch is in the archive.")));

    expect(getConversation(chatA.id)).toBeNull();
    expect(getConversationMessages(chatA.id)).toEqual([]);
    expect(getConversationMessages(chatB.id)).toEqual([]);
  });

  it("settles a retried turn in place after a switch, preserving later turns", async () => {
    const chatA = createConversation("Events");
    const chatB = createConversation("Images");
    saveConversationMessages(chatA.id, [
      { id: "first", question: "When is the exhibit?", status: "error", answer: null, citations: [], retrievalCount: 0, error: "Try again" },
      { id: "later", question: "Where is it?", status: "done", answer: "Hall C", citations: [], retrievalCount: 0, error: null },
    ]);
    const pending = deferred<ChatResponse>();
    vi.mocked(askQuestion).mockReturnValueOnce(pending.promise);
    const view = render(<ChatInterface conversationId={chatA.id} />);

    fireEvent.click(await screen.findByRole("button", { name: "Retry first" }));
    await waitFor(() => expect(askQuestion).toHaveBeenCalledTimes(1));
    view.rerender(<ChatInterface conversationId={chatB.id} />);
    await act(async () => pending.resolve(answer("Saturday.")));

    expect(getConversationMessages(chatA.id).map((turn) => turn.id)).toEqual(["first", "later"]);
    expect(getConversationMessages(chatA.id)[0]).toMatchObject({ status: "done", answer: "Saturday." });
    expect(getConversationMessages(chatA.id)[1]).toMatchObject({ answer: "Hall C" });
    expect(getConversationMessages(chatB.id)).toEqual([]);
  });

  it("marks an orphaned pending turn interrupted on a fresh mount without losing its question", async () => {
    const chat = createConversation("Drafts");
    saveConversationMessages(chat.id, [{
      id: "orphan",
      question: "Find the itinerary",
      status: "pending",
      answer: null,
      citations: [],
      retrievalCount: 0,
      error: null,
    }]);

    render(<ChatInterface conversationId={chat.id} />);

    await waitFor(() => expect(getConversationMessages(chat.id)[0]).toMatchObject({
      id: "orphan",
      question: "Find the itinerary",
      status: "error",
    }));
    expect(await screen.findByText("Find the itinerary")).toBeInTheDocument();
    expect(askQuestion).not.toHaveBeenCalled();
  });
});
