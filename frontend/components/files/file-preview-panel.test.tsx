import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "@/components/files/file-preview-panel";
import { fetchFileTextPreview } from "@/lib/files/preview";
import { prepareSingleFile } from "@/lib/knowledge/prepare-file";
import type { DriveFileRead } from "@/lib/api/types";

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
  beforeEach(() => vi.clearAllMocks());
  afterEach(cleanup);

  it("keeps file actions and metadata visible while showing available preview text", async () => {
    vi.mocked(fetchFileTextPreview).mockResolvedValue("First line\nSecond line");
    render(<FilePreviewPanel file={file} />);

    expect(screen.getByRole("heading", { name: file.name })).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask about this file" })).toHaveAttribute(
      "href", "/chat?ask=Tell%20me%20about%20%22Machine_Learning_Notes.txt%22",
    );
    expect(screen.getByRole("link", { name: "Open in Google Drive" })).toHaveAttribute(
      "href", "https://drive.google.com/file/d/drive-file-1/view",
    );
    expect(screen.getByRole("link", { name: "Open in Google Drive" })).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("button", { name: "Prepare this file for chat" })).not.toBeInTheDocument();

    const preview = screen.getByRole("region", { name: "File preview" });
    await waitFor(() => expect(preview).toHaveTextContent("First line Second line"));
    expect(preview.querySelector("blockquote")).toBeNull();
    expect(within(screen.getByRole("region", { name: "File details" })).getByText(file.folder_path!)).toBeInTheDocument();
    expect(screen.queryByText("Ask AI")).not.toBeInTheDocument();
  });

  it("keeps unavailable preview calm and preserves contextual preparation behavior", async () => {
    vi.mocked(fetchFileTextPreview).mockResolvedValue(null);
    let rejectPrepare: (reason?: unknown) => void = () => {};
    vi.mocked(prepareSingleFile).mockReturnValue(new Promise<void>((_, reject) => { rejectPrepare = reject; }));
    render(<FilePreviewPanel file={{ ...file, status: "failed" }} />);

    const preview = screen.getByRole("region", { name: "File preview" });
    expect(await within(preview).findByText("Preview isn't available for this file. You can still ask questions about it.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask about this file" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Prepare this file for chat" }));
    expect(prepareSingleFile).toHaveBeenCalledWith(file.id);
    expect(screen.getByRole("button", { name: "Preparing this file…" })).toBeDisabled();
    rejectPrepare(new Error("Preparation unavailable"));
    expect(await screen.findByText("Preparation unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare this file for chat" })).toBeInTheDocument();
  });

  it("keeps a useful no-selection state", () => {
    render(<FilePreviewPanel file={null} />);
    expect(screen.getByText("Select a file")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ask about this file" })).not.toBeInTheDocument();
  });
});
