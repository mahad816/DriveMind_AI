import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInterface } from "@/components/chat/chat-interface";
import { getSourceChunk } from "@/lib/api/sources";
import type { CitationItem, SourceChunkRead } from "@/lib/api/types";
import { getConversationMessages, saveConversationMessages, type StoredChatMessage } from "@/lib/conversations/messages";
import { createConversation } from "@/lib/conversations/storage";

vi.mock("next/navigation", () => ({
  useRouter: (() => {
    const router = { push: vi.fn(), replace: vi.fn() };
    return () => router;
  })(),
  useSearchParams: (() => {
    const params = new URLSearchParams();
    return () => params;
  })(),
}));
vi.mock("@/lib/hooks/use-connection-status", () => {
  const value = { data: { connected: true }, error: null, refetch: vi.fn() };
  return { useConnectionStatus: () => value };
});
vi.mock("@/lib/hooks/use-knowledge-status", () => ({
  useKnowledgeStatus: () => ({ needsConnect: false, needsPrepare: false }),
}));
vi.mock("@/lib/hooks/use-conversations", () => {
  const value = {
    conversations: [],
    startNewConversation: vi.fn(),
    renameConversation: vi.fn(),
    bumpConversation: vi.fn(),
  };
  return { useConversations: () => value };
});
vi.mock("@/lib/hooks/use-chat-shortcuts", () => ({ useChatShortcuts: vi.fn() }));
vi.mock("@/lib/api/sources", () => ({ getSourceChunk: vi.fn() }));
vi.mock("@/components/ui/toast-provider", () => ({
  useToast: () => ({ pushToast: vi.fn() }),
}));

const first: CitationItem = {
  chunk_id: "chunk-a1",
  drive_file_id: "file-a",
  filename: "notes.txt",
  snippet: "First passage",
  score: null,
};
const second: CitationItem = {
  chunk_id: "chunk-a2",
  drive_file_id: "file-a",
  filename: "notes.txt",
  snippet: "Second passage",
  score: null,
};
const third: CitationItem = {
  chunk_id: "chunk-b1",
  drive_file_id: "file-b",
  filename: "schedule.pdf",
  snippet: "Third passage",
  score: null,
};

function detail(citation: CitationItem): SourceChunkRead {
  return {
    chunk_id: citation.chunk_id,
    drive_file_id: citation.drive_file_id,
    filename: citation.filename,
    mime_type: "text/plain",
    chunk_index: 0,
    text: `Full ${citation.snippet}`,
    modified_at: "2026-09-28T10:00:00Z",
  };
}

function done(id: string, answer: string, citations: CitationItem[]): StoredChatMessage {
  return {
    id,
    question: `Question ${id}`,
    status: "done",
    answer,
    citations,
    retrievalCount: 8,
    error: null,
  };
}

function openConversation(messages: StoredChatMessage[]) {
  const conversation = createConversation("Evidence");
  saveConversationMessages(conversation.id, messages);
  render(<ChatInterface conversationId={conversation.id} />);
  return conversation.id;
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
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
  vi.mocked(getSourceChunk).mockReset();
  vi.mocked(getSourceChunk).mockImplementation(async (chunkId) => {
    const citation = [first, second, third].find((item) => item.chunk_id === chunkId);
    if (!citation) throw new Error("Unknown source");
    return detail(citation);
  });
});
afterEach(cleanup);

describe("answer-wide evidence", () => {
  it("opens Sources with every cited passage while counting distinct cited files", async () => {
    const user = userEvent.setup();
    const conversationId = openConversation([
      done("turn-one", "Three claims [1] [2] [3].", [first, second, third]),
    ]);
    const answer = await screen.findByRole("article", { name: "Assistant answer" });

    await user.click(await screen.findByRole("button", { name: "Sources · 2" }));
    const panel = screen.getByRole("dialog");
    expect(within(panel).getByRole("button", { name: /citation 1|passage 1/i })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /citation 2|passage 2/i })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /citation 3|passage 3/i })).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: /citation 2|passage 2/i }));
    await waitFor(() => expect(getSourceChunk).toHaveBeenCalledWith("chunk-a2"));
    expect(await within(panel).findByText(/Full Second passage/)).toBeInTheDocument();
    expect(answer).toBeInTheDocument();
    expect(answer).toHaveTextContent("Three claims");
    expect(within(answer).getByRole("button", { name: "View citation 1", hidden: true })).toBeInTheDocument();
    expect(within(answer).getByRole("button", { name: "View citation 2", hidden: true })).toBeInTheDocument();
    expect(within(answer).getByRole("button", { name: "View citation 3", hidden: true })).toBeInTheDocument();
    expect(getConversationMessages(conversationId)).toHaveLength(1);
  });

  it("opens an inline marker in its answer's evidence context focused on that chunk", async () => {
    const user = userEvent.setup();
    openConversation([done("turn-one", "The second source says this [2].", [first, second])]);

    await user.click(await screen.findByRole("button", { name: /view citation 2/i }));
    expect(await screen.findByText(/Second passage/)).toBeInTheDocument();
    expect(screen.queryByText(/Full First passage/)).not.toBeInTheDocument();
  });

  it("closes without changing chat and does not carry one answer's evidence into another", async () => {
    const user = userEvent.setup();
    const turns = [
      done("turn-one", "First answer [1].", [first]),
      done("turn-two", "Second answer [1].", [third]),
    ];
    const conversationId = openConversation(turns);
    const answers = await screen.findAllByRole("article", { name: "Assistant answer" });

    const firstSources = within(answers[0]).getByRole("button", { name: "Sources · 1" });
    await user.click(firstSources);
    expect(await screen.findByText(/Full First passage/)).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(firstSources).toHaveFocus();

    await user.click(within(answers[1]).getByRole("button", { name: "Sources · 1" }));
    expect(await screen.findByText(/Full Third passage/)).toBeInTheDocument();
    expect(screen.queryByText(/Full First passage/)).not.toBeInTheDocument();
    expect(getConversationMessages(conversationId)).toEqual(turns);
  });

  it("keeps the answer visible if source detail fails", async () => {
    const user = userEvent.setup();
    vi.mocked(getSourceChunk).mockRejectedValueOnce(new Error("Source temporarily unavailable"));
    openConversation([done("turn-one", "An answer [1].", [first])]);
    const answer = await screen.findByRole("article", { name: "Assistant answer" });

    await user.click(await screen.findByRole("button", { name: "Sources · 1" }));
    expect(await screen.findByText("Source temporarily unavailable")).toBeInTheDocument();
    expect(answer).toBeInTheDocument();
    expect(answer).toHaveTextContent("An answer");
    expect(within(answer).getByRole("button", { name: "View citation 1", hidden: true })).toBeInTheDocument();
  });
});
