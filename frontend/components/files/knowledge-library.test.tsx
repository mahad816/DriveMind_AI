import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeLibrary } from "@/components/files/knowledge-library";
import { listDriveFiles } from "@/lib/api/files";
import type { DriveFileListResponse, DriveFileRead } from "@/lib/api/types";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";

vi.mock("@/lib/api/files", () => ({ listDriveFiles: vi.fn() }));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: vi.fn() }));
vi.mock("@/components/files/file-preview-panel", () => ({ FilePreviewPanel: () => null }));
vi.mock("@/components/files/file-preview-sheet", () => ({ FilePreviewSheet: () => null }));

const atlas: DriveFileRead = {
  id: "atlas-id",
  user_id: "user-id",
  drive_file_id: "atlas-drive-id",
  name: "Project Atlas.pdf",
  mime_type: "application/pdf",
  folder_path: "Projects",
  modified_at: "2026-01-15T12:00:00Z",
  indexed_at: "2026-01-16T12:00:00Z",
  status: "indexed",
  created_at: "2026-01-15T12:00:00Z",
  updated_at: "2026-01-16T12:00:00Z",
};
const roadmap: DriveFileRead = {
  ...atlas,
  id: "roadmap-id",
  drive_file_id: "roadmap-drive-id",
  name: "Roadmap.docx",
  mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  status: "discovered",
};

function connection(connected: boolean, error: string | null = null) {
  vi.mocked(useConnectionStatus).mockReturnValue({
    data: { connected, job: null },
    isLoading: false,
    error,
    refetch: vi.fn().mockResolvedValue(undefined),
  });
}

describe("Files browser", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    connection(true);
  });

  it("shows loading without claiming there are no files", () => {
    vi.mocked(listDriveFiles).mockReturnValue(new Promise(() => {}));
    render(<KnowledgeLibrary />);

    expect(screen.getByText("Loading files…")).toBeInTheDocument();
    expect(screen.queryByText("No Drive files found")).not.toBeInTheDocument();
  });

  it("renders real file metadata and keeps search and status filters functional", async () => {
    vi.mocked(listDriveFiles).mockResolvedValue({ files: [atlas, roadmap], total: 2 });
    render(<KnowledgeLibrary />);

    expect(await screen.findByText("Project Atlas.pdf")).toBeInTheDocument();
    expect(screen.getByText("Roadmap.docx")).toBeInTheDocument();
    expect(screen.getByText("2 Drive files found")).toBeInTheDocument();
    expect(screen.getByText(/PDF · .*2026/)).toBeInTheDocument();

    const filters = within(screen.getByRole("group", { name: "Filter files by status" }));
    fireEvent.click(filters.getByRole("button", { name: "Ready (1)" }));
    expect(screen.getByText("Project Atlas.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Roadmap.docx")).not.toBeInTheDocument();

    fireEvent.click(filters.getByRole("button", { name: "All (2)" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Search files" }), { target: { value: "Roadmap" } });
    await waitFor(() => expect(screen.queryByText("Project Atlas.pdf")).not.toBeInTheDocument());
    expect(screen.getByText("Roadmap.docx")).toBeInTheDocument();
  });

  it("distinguishes an empty Drive file list from a search with no matches", async () => {
    vi.mocked(listDriveFiles).mockResolvedValue({ files: [], total: 0 });
    const view = render(<KnowledgeLibrary />);
    expect(await screen.findByText("No Drive files found")).toBeInTheDocument();

    const files: DriveFileListResponse = { files: [atlas], total: 1 };
    vi.mocked(listDriveFiles).mockResolvedValue(files);
    view.unmount();
    render(<KnowledgeLibrary />);
    expect(await screen.findByText("Project Atlas.pdf")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search files" }), { target: { value: "nonexistent" } });
    expect(await screen.findByText("No files match your search or filter.")).toBeInTheDocument();
    expect(screen.queryByText("No Drive files found")).not.toBeInTheDocument();
  });

  it("does not present a failed connection check as confirmed disconnection", () => {
    connection(false, "Network unavailable");
    render(<KnowledgeLibrary />);
    expect(screen.getByText("Couldn’t check your Drive connection")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry connection check" })).toBeInTheDocument();
    expect(screen.queryByText("Connect Google Drive")).not.toBeInTheDocument();
  });

  it("contains a file-list error and offers a real retry", async () => {
    vi.mocked(listDriveFiles).mockRejectedValueOnce(new Error("File service unavailable"));
    vi.mocked(listDriveFiles).mockResolvedValueOnce({ files: [atlas], total: 1 });
    render(<KnowledgeLibrary />);

    expect(await screen.findByText("Could not load files")).toBeInTheDocument();
    expect(screen.getByText("File service unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Connect Google Drive")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading files" }));
    expect(await screen.findByText("Project Atlas.pdf")).toBeInTheDocument();
  });

  it("offers the existing settings route only for confirmed disconnection", () => {
    connection(false);
    render(<KnowledgeLibrary />);
    expect(screen.getByRole("link", { name: "Connect in Settings" })).toHaveAttribute("href", "/settings");
  });
});
