import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SourcePanel } from "@/components/chat/source-panel";
import { getSourceChunk } from "@/lib/api/sources";
import type { CitationItem, SourceChunkRead } from "@/lib/api/types";

vi.mock("@/lib/api/sources", () => ({ getSourceChunk: vi.fn() }));

function citation(chunkId: string): CitationItem {
  return {
    chunk_id: chunkId,
    drive_file_id: "file-a",
    filename: "notes.txt",
    snippet: `Preview ${chunkId}`,
    score: null,
  };
}

function detail(chunkId: string): SourceChunkRead {
  return {
    chunk_id: chunkId,
    drive_file_id: "file-a",
    filename: "notes.txt",
    mime_type: "text/plain",
    chunk_index: chunkId === "chunk-a1" ? 0 : 1,
    text: `Full text ${chunkId}`,
    modified_at: "2026-09-28T10:00:00Z",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

beforeEach(() => vi.mocked(getSourceChunk).mockReset());
afterEach(cleanup);

describe("citation source detail", () => {
  it("fetches the selected chunk and distinguishes loading from a fetch error", async () => {
    const user = userEvent.setup();
    const pending = deferred<SourceChunkRead>();
    vi.mocked(getSourceChunk).mockReturnValueOnce(pending.promise);
    const onOpenChange = vi.fn();
    render(<SourcePanel citation={citation("chunk-a1")} open onOpenChange={onOpenChange} />);

    expect(getSourceChunk).toHaveBeenCalledWith("chunk-a1");
    expect(screen.queryByText("Unable to load source")).not.toBeInTheDocument();
    pending.resolve(detail("chunk-a1"));
    expect(await screen.findByText(/Full text chunk-a1/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open in (google )?drive/i })).toHaveAttribute(
      "href",
      expect.stringContaining("file-a"),
    );

    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(onOpenChange.mock.calls.some(([open]) => open === false)).toBe(true));
  });

  it("uses the new chunk identity and never presents prior detail as current evidence", async () => {
    vi.mocked(getSourceChunk).mockResolvedValueOnce(detail("chunk-a1"));
    const next = deferred<SourceChunkRead>();
    vi.mocked(getSourceChunk).mockReturnValueOnce(next.promise);
    const view = render(<SourcePanel citation={citation("chunk-a1")} open onOpenChange={vi.fn()} />);
    expect(await screen.findByText(/Full text chunk-a1/)).toBeInTheDocument();

    view.rerender(<SourcePanel citation={citation("chunk-a2")} open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(getSourceChunk).toHaveBeenCalledWith("chunk-a2"));
    expect(screen.queryByText(/Full text chunk-a1/)).not.toBeInTheDocument();
    next.resolve(detail("chunk-a2"));
    expect(await screen.findByText(/Full text chunk-a2/)).toBeInTheDocument();
  });

  it("does not let a late response replace the currently selected citation", async () => {
    const first = citation("chunk-a1");
    const second = citation("chunk-a2");
    const firstRequest = deferred<SourceChunkRead>();
    const secondRequest = deferred<SourceChunkRead>();
    vi.mocked(getSourceChunk)
      .mockReturnValueOnce(firstRequest.promise)
      .mockReturnValueOnce(secondRequest.promise);

    const view = render(
      <SourcePanel citation={first} citations={[first, second]} open onOpenChange={vi.fn()} />,
    );
    expect(getSourceChunk).toHaveBeenCalledWith("chunk-a1");

    view.rerender(
      <SourcePanel citation={second} citations={[first, second]} open onOpenChange={vi.fn()} />,
    );
    await waitFor(() => expect(getSourceChunk).toHaveBeenCalledWith("chunk-a2"));
    await act(async () => { secondRequest.resolve(detail("chunk-a2")); });
    expect(await screen.findByText(/Full text chunk-a2/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Citation 2: notes.txt/ })).toHaveAttribute("aria-pressed", "true");

    await act(async () => { firstRequest.resolve(detail("chunk-a1")); });
    expect(screen.getByText(/Full text chunk-a2/)).toBeInTheDocument();
    expect(screen.queryByText(/Full text chunk-a1/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Citation 2: notes.txt/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a source error without claiming the source loaded", async () => {
    vi.mocked(getSourceChunk).mockRejectedValueOnce(new Error("Source temporarily unavailable"));
    render(<SourcePanel citation={citation("chunk-a1")} open onOpenChange={vi.fn()} />);

    expect(await screen.findByText("Source temporarily unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/Full text chunk-a1/)).not.toBeInTheDocument();
  });
});
