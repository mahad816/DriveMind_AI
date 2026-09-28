import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssistantMessage } from "@/components/chat/assistant-message";
import type { ChatResponse, CitationItem } from "@/lib/api/types";

vi.mock("@/components/ui/toast-provider", () => ({
  useToast: () => ({ pushToast: vi.fn() }),
}));

afterEach(cleanup);

function citation(fileId: string, chunkId: string, filename: string, snippet: string): CitationItem {
  return { drive_file_id: fileId, chunk_id: chunkId, filename, snippet, score: 0.99 };
}

function response(answer: string, citations: CitationItem[], retrievalCount = 8): ChatResponse {
  return {
    query_id: "query-1",
    user_id: "user-1",
    answer,
    message: answer,
    citations,
    retrieval_count: retrievalCount,
  };
}

const first = citation("file-a", "chunk-a1", "field-notes.txt", "First cited passage");
const second = citation("file-a", "chunk-a2", "field-notes.txt", "Second cited passage");
const third = citation("file-b", "chunk-b1", "plan.pdf", "Third cited passage");

describe("answer citation interaction", () => {
  it("maps keyboard-accessible inline markers to the backend citation array order", async () => {
    const user = userEvent.setup();
    render(
      <AssistantMessage
        response={response("First claim [1]. Second claim [2].", [first, second])}
        onSourceSelect={vi.fn()}
      />,
    );

    const markerOne = screen.getByRole("button", { name: /view citation 1/i });
    const markerTwo = screen.getByRole("button", { name: /view citation 2/i });
    markerTwo.focus();
    expect(markerTwo).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("Second cited passage")).toBeInTheDocument();
    await user.click(markerOne);
    expect(screen.getByText("First cited passage")).toBeInTheDocument();
  });

  it("shows cited evidence and a real Drive action without retrieval internals", () => {
    render(
      <AssistantMessage
        response={response("The plan says this [1].", [third])}
        onSourceSelect={vi.fn()}
      />,
    );

    const filenamesBeforePreview = screen.queryAllByText("plan.pdf").length;
    fireEvent.click(screen.getByRole("button", { name: /view citation 1/i }));
    expect(screen.getAllByText("plan.pdf").length).toBeGreaterThan(filenamesBeforePreview);
    expect(screen.getByText("Third cited passage")).toBeInTheDocument();
    const driveLink = screen.getByRole("link", { name: /open in (google )?drive/i });
    expect(driveLink).toHaveAttribute("href", expect.stringContaining("file-b"));
    expect(screen.queryByText(/chunk-b1|0\.99|BM25|RRF|rerank|evidence grade|route name/i))
      .not.toBeInTheDocument();
  });

  it("counts cited files without discarding same-file cited passages", () => {
    render(
      <AssistantMessage
        response={response("One [1], two [2], three [3].", [first, second, third])}
        onSourceSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Sources · 2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /view citation 2/i }));
    expect(screen.getByText("Second cited passage")).toBeInTheDocument();
  });

  it("leaves invalid brackets, ordinary Markdown links, and lists intact", () => {
    render(
      <AssistantMessage
        response={response(
          "There were [42] records and [3] mismatches. An unmatched [ remains. [Read the report](https://example.com).\n\n- Year [2025]\n- Supported [1]",
          [first, second],
        )}
        onSourceSelect={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /view citation (3|42|2025)/i })).not.toBeInTheDocument();
    expect(screen.getByText(/There were \[42\] records and \[3\] mismatches/)).toBeInTheDocument();
    expect(screen.getByText(/An unmatched \[/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read the report" })).toHaveAttribute("href", "https://example.com");
    expect(within(screen.getByRole("list")).getByText(/Year \[2025\]/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /view citation 1/i })).toBeInTheDocument();
  });

  it("does not invent cited sources for an uncited answer with retrieval candidates", () => {
    render(
      <AssistantMessage
        response={response("A direct answer.", [], 8)}
        onSourceSelect={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /sources|view citation/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/no sources found|based on 8 sources/i)).not.toBeInTheDocument();
  });
});
