import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageThread, type ChatTurn } from "@/components/chat/message-thread";
import type { ChatResponse } from "@/lib/api/types";

vi.mock("@/components/ui/toast-provider", () => ({
  useToast: () => ({ pushToast: vi.fn() }),
}));

afterEach(cleanup);

function thread(message: ChatTurn) {
  render(
    <MessageThread
      messages={[message]}
      onSourceSelect={vi.fn()}
      onRetry={vi.fn()}
      onRegenerate={vi.fn()}
      onFollowUp={vi.fn()}
      isSending={message.status === "loading"}
    />,
  );
}

function response(answer: string): ChatResponse {
  return {
    query_id: "query-1",
    user_id: "user-1",
    answer,
    message: answer,
    retrieval_count: 1,
    citations: [{
      chunk_id: "chunk-1",
      drive_file_id: "file-1",
      filename: "agenda.txt",
      snippet: "Meeting at noon",
      score: null,
    }],
  };
}

describe("conversation turn status", () => {
  it("shows one honest pending state without fabricated stages or fake streamed content", () => {
    thread({ id: "turn-1", question: "When is the meeting?", status: "loading", error: null });

    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.queryByText(/Reading relevant sources|Preparing answer/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Assistant answer" })).not.toBeInTheDocument();
  });

  it("keeps interruption/error distinct from the pending state", () => {
    thread({ id: "turn-1", question: "When is the meeting?", status: "error", error: "Request interrupted", response: null });

    expect(screen.getByText("Request interrupted")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("announces completion concisely without making the entire answer live", () => {
    const longAnswer = "The meeting starts at noon. Review the agenda before joining.";
    thread({ id: "turn-1", question: "When is the meeting?", status: "done", error: null, response: response(longAnswer) });

    const answer = screen.getByRole("article", { name: "Assistant answer" });
    expect(answer).toHaveTextContent(longAnswer);
    expect(answer.closest('[aria-live]')).toBeNull();
    const completion = screen.getByRole("status");
    expect(completion).toHaveTextContent(/answer ready|response ready|complete/i);
    expect(completion).not.toHaveTextContent(longAnswer);
  });

  it("retains Copy, Regenerate, and cited-source actions after completion", () => {
    thread({ id: "turn-1", question: "When is the meeting?", status: "done", error: null, response: response("At noon [1].") });

    expect(screen.getAllByText("When is the meeting?")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sources · 1/i })).toBeInTheDocument();
  });
});
