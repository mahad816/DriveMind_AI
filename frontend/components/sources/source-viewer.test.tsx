import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SourceViewer } from "@/components/sources/source-viewer";
import { getSourceChunk } from "@/lib/api/sources";
import { ApiError } from "@/lib/api/errors";
import type { SourceChunkRead } from "@/lib/api/types";

vi.mock("@/lib/api/sources", () => ({ getSourceChunk: vi.fn() }));
vi.mock("@/lib/demo", () => ({ DEMO_MODE: false }));

const source: SourceChunkRead = {
  chunk_id: "synthetic-chunk", drive_file_id: "internal-file-uuid",
  filename: "Owner sample.txt", mime_type: "text/plain", chunk_index: 0,
  text: "Authorized sample excerpt", modified_at: "2026-10-14T10:00:00Z",
};

beforeEach(() => { vi.mocked(getSourceChunk).mockReset(); });
afterEach(cleanup);

it("renders authorized source data without provider-ID or question-URL fabrication", async () => {
  vi.mocked(getSourceChunk).mockResolvedValue(source);
  const { container } = render(<SourceViewer chunkId={source.chunk_id} />);
  await screen.findByText(/Authorized sample excerpt/);
  expect(getSourceChunk).toHaveBeenCalledWith(source.chunk_id);
  const links = [...container.querySelectorAll("a")].map((link) => link.getAttribute("href"));
  expect(links).toContain("/chat");
  expect(links.some((href) => href?.includes("?ask=") || href?.includes("drive.google.com"))).toBe(false);
});

it("does not invent source contents when the session has expired", async () => {
  vi.mocked(getSourceChunk).mockRejectedValue(new ApiError(401, "Sign in required"));
  render(<SourceViewer chunkId={source.chunk_id} />);
  await screen.findByText("Sign in required");
  expect(screen.queryByText(/Authorized sample excerpt/)).not.toBeInTheDocument();
  expect(screen.queryByText(source.filename)).not.toBeInTheDocument();
});

it("discards a late source result after unmount", async () => {
  let resolve!: (value: SourceChunkRead) => void;
  vi.mocked(getSourceChunk).mockReturnValue(new Promise((done) => { resolve = done; }));
  const mounted = render(<SourceViewer chunkId={source.chunk_id} />);
  await waitFor(() => expect(getSourceChunk).toHaveBeenCalledOnce());
  mounted.unmount();
  resolve(source);
  await waitFor(() => expect(screen.queryByText(/Authorized sample excerpt/)).not.toBeInTheDocument());
});
