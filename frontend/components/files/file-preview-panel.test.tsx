import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "@/components/files/file-preview-panel";
import { fetchFileTextPreview } from "@/lib/files/preview";
import { prepareSingleFile } from "@/lib/knowledge/prepare-file";
import type { DriveFileRead } from "@/lib/api/types";

const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", async (original) => ({ ...await original<typeof import("@/lib/demo")>(), get DEMO_MODE() { return mode.demo; } }));

vi.mock("@/lib/files/preview", () => ({ fetchFileTextPreview: vi.fn() }));
vi.mock("@/lib/knowledge/prepare-file", () => ({ prepareSingleFile: vi.fn() }));

const file: DriveFileRead = {
  id: "file-1",
  user_id: "user-1",
  drive_file_id: "drive-file-1",
  name: "Machine_Learning_Notes.txt",
  mime_type: "text/plain",
  folder_path: "/DriveMind_Eval_Corpus",
  modified_at: "2026-09-18T12:00:00Z",
  indexed_at: "2026-09-19T12:00:00Z",
  status: "indexed",
  created_at: "2026-09-18T12:00:00Z",
  updated_at: "2026-09-19T12:00:00Z",
};

describe("selected-file inspector", () => {
  beforeEach(() => { mode.demo = false; vi.clearAllMocks(); });
  afterEach(cleanup);

  it("keeps file actions and metadata visible while showing available preview text", async () => {
    vi.mocked(fetchFileTextPreview).mockResolvedValue("First line\nSecond line");
    render(<FilePreviewPanel file={file} />);

    expect(screen.getByRole("heading", { name: file.name })).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open chat" })).toHaveAttribute(
      "href", "/chat",
    );
    expect(screen.getByRole("link", { name: "Open in Google Drive" })).toHaveAttribute(
      "href", "https://drive.google.com/file/d/drive-file-1/view",
    );
    expect(screen.getByRole("link", { name: "Open in Google Drive" })).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("button", { name: "Prepare this file for chat" })).not.toBeInTheDocument();

    const inspector = screen.getByRole("region", { name: "File inspector" });
    expect(inspector).toHaveAttribute("tabindex", "0");
    expect(within(inspector).getByRole("link", { name: "Open in Google Drive" })).toBeInTheDocument();
    const preview = screen.getByRole("region", { name: "File preview" });
    expect(preview).toHaveTextContent("Browsing shows metadata only");
    expect(fetchFileTextPreview).not.toHaveBeenCalled();
    expect(preview.querySelector("blockquote")).toBeNull();
    expect(within(screen.getByRole("region", { name: "File details" })).getByText(file.folder_path!)).toBeInTheDocument();
    expect(screen.queryByText("Ask AI")).not.toBeInTheDocument();
  });

  it("does not download or prepare a discovered file", () => {
    render(<FilePreviewPanel file={{ ...file, status: "discovered" }} />);
    expect(screen.getByText(/Select this document to review/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Select for preparation" })).toHaveAttribute("href", `/prepare?file=${file.id}`);
    expect(screen.queryByRole("button", { name: "Prepare this file for chat" })).toBeNull();
    expect(fetchFileTextPreview).not.toHaveBeenCalled(); expect(prepareSingleFile).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Open chat" })).toBeNull();
  });

  it("preserves separate anonymous demo ask links without indexing actions", () => {
    mode.demo = true;
    vi.mocked(fetchFileTextPreview).mockResolvedValue(null);
    render(<FilePreviewPanel file={file} />);
    expect(screen.getByRole("link", { name: "Ask about this file" })).toHaveAttribute(
      "href", "/chat?ask=Tell%20me%20about%20%22Machine_Learning_Notes.txt%22",
    );
    expect(screen.queryByRole("button", { name: "Prepare this file for chat" })).toBeNull();
    expect(prepareSingleFile).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "File inspector" })).toBeNull();
  });

  it("keeps a useful no-selection state", () => {
    render(<FilePreviewPanel file={null} />);
    expect(screen.getByText("Select a file")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ask about this file" })).not.toBeInTheDocument();
  });
});
