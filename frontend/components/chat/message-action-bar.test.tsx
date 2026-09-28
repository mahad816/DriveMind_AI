import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageActionBar } from "@/components/chat/message-action-bar";
import type { CitationItem } from "@/lib/api/types";

vi.mock("@/components/ui/toast-provider", () => ({
  useToast: () => ({ pushToast: vi.fn() }),
}));

afterEach(cleanup);

function citation(fileId: string, chunkId: string, filename = "notes.txt"): CitationItem {
  return {
    chunk_id: chunkId,
    drive_file_id: fileId,
    filename,
    snippet: "A cited passage",
    score: null,
  };
}

describe("answer source actions", () => {
  it("offers the number of files actually cited, not retrieved chunks", () => {
    render(
      <MessageActionBar
        answer="An answer [1] [2]"
        citations={[citation("file-a", "a1"), citation("file-b", "b1", "plan.txt")]}
        retrievalCount={8}
        onSourceSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Sources · 2" })).toBeInTheDocument();
    expect(screen.queryByText(/Based on 8 sources/i)).not.toBeInTheDocument();
  });

  it("keeps separate cited passages available even when they share a file", () => {
    const onSourceSelect = vi.fn();
    const first = citation("file-a", "a1");
    const second = citation("file-a", "a2");

    render(
      <MessageActionBar
        answer="Two passages [1] [2]"
        citations={[first, second]}
        retrievalCount={2}
        onSourceSelect={onSourceSelect}
      />,
    );

    const passageActions = screen.getAllByRole("button", { name: /notes\.txt/i });
    expect(passageActions).toHaveLength(2);
    for (const action of passageActions) fireEvent.click(action);
    expect(onSourceSelect.mock.calls.map(([selected]) => selected.chunk_id)).toEqual(["a1", "a2"]);
  });

  it("does not show a source warning or count when there are no citations", () => {
    render(<MessageActionBar answer="Hello." citations={[]} retrievalCount={0} />);

    expect(screen.queryByText(/No sources found/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sources\s*·\s*\d|Based on \d+ sources?/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("does not present retrieved but uncited chunks as sources", () => {
    render(<MessageActionBar answer="An answer." citations={[]} retrievalCount={8} />);

    expect(screen.queryByText(/No sources found|Sources\s*·\s*\d|Based on \d+ sources?/i))
      .not.toBeInTheDocument();
  });

  it("renders a direct or history-style answer without a source-error state", () => {
    render(<MessageActionBar answer="The last question was about lunch." citations={[]} retrievalCount={0} />);

    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
    expect(screen.queryByText(/source/i)).not.toBeInTheDocument();
  });
});
