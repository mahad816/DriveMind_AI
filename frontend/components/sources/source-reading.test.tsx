import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SourcePage from "@/app/sources/[chunkId]/page";
import { SourceViewer } from "./source-viewer";
import { SourceTrustPanel } from "./source-trust-panel";
import { getSourceChunk } from "@/lib/api/sources";

const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
vi.mock("@/lib/api/sources", () => ({ getSourceChunk: vi.fn() }));
afterEach(() => { cleanup(); mode.demo = false; vi.mocked(getSourceChunk).mockReset(); });
const chunk = "00000000-0000-0000-0000-000000000222", origin = "00000000-0000-0000-0000-000000000333";
const source = { chunk_id: chunk, drive_file_id: "internal-sql-file", filename: "Research decisions.txt", mime_type: "text/plain", chunk_index: 0, text: "The source passage remains exactly the evidence supplied by the authorized endpoint.", modified_at: "2026-10-16T10:00:00Z" };

it("standalone normal source has one page H1, a subordinate filename and authorized return context", async () => {
  vi.mocked(getSourceChunk).mockResolvedValue(source);
  render(await SourcePage({ params: Promise.resolve({ chunkId: chunk }), searchParams: Promise.resolve({ conversation: origin }) }));
  await screen.findByRole("heading", { level: 2, name: source.filename });
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByRole("link", { name: "Back to conversation" })).toHaveAttribute("href", `/chat/${origin}`);
  expect(getSourceChunk).toHaveBeenCalledExactlyOnceWith(chunk);
  expect(screen.getByText(`“${source.text}”`, { selector: "blockquote" }).textContent).toBe(`“${source.text}”`);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("does not announce ordinary loading as an urgent error", () => {
  vi.mocked(getSourceChunk).mockReturnValue(new Promise(() => {}));
  render(<SourceViewer chunkId={chunk} />);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText(source.text)).toBeNull();
});

it("announces a genuine source failure once without inventing evidence", async () => {
  vi.mocked(getSourceChunk).mockRejectedValue(new Error("Source temporarily unavailable"));
  render(<SourceViewer chunkId={chunk} conversationId={origin} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Source temporarily unavailable");
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(screen.queryByText(source.text)).toBeNull();
  expect(screen.getByRole("link", { name: "Back to conversation" })).toHaveAttribute("href", `/chat/${origin}`);
});

it("supports an explicit heading level in embedded contexts", () => {
  render(<SourceTrustPanel filename={source.filename} excerpt={source.text} askHref="/chat" headingLevel={3} />);
  expect(screen.getByRole("heading", { level: 3, name: source.filename })).toBeInTheDocument();
});

it("preserves the legacy demo heading and error presentation", () => {
  mode.demo = true;
  render(<SourceTrustPanel filename={source.filename} excerpt="" askHref="/chat" error="Sample unavailable" />);
  expect(screen.getByRole("heading", { level: 1, name: source.filename })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText("Sample unavailable")).toBeInTheDocument();
});
