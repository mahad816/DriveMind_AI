import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { FilePreviewSheet } from "./file-preview-sheet";
import type { DriveFileRead } from "@/lib/api/types";
const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
vi.mock("@/lib/files/preview", () => ({ fetchFileTextPreview: vi.fn(async () => null) }));
afterEach(() => { cleanup(); mode.demo = false; });
const file: DriveFileRead = {
  id: "synthetic-file", user_id: "synthetic-owner", drive_file_id: "synthetic-drive",
  name: "A long document title about interviews, constraints and architecture before the private beta launch.txt",
  mime_type: "text/plain", folder_path: "Research / A long folder path / Decisions",
  modified_at: "2026-10-15T10:00:00Z", indexed_at: null, status: "discovered",
  created_at: "2026-10-15T10:00:00Z", updated_at: "2026-10-15T10:00:00Z",
};
it("keeps the long title, actions and metadata in one keyboard-accessible inspector and closes normally", async () => {
  const onOpenChange = vi.fn();
  const user = userEvent.setup();
  render(<FilePreviewSheet file={file} open onOpenChange={onOpenChange} />);
  const inspector = screen.getByRole("region", { name: "File inspector" });
  expect(within(inspector).getByRole("heading", { name: file.name })).toBeInTheDocument();
  expect(within(inspector).getByRole("link", { name: "Open in Google Drive" })).toHaveAttribute("href", "https://drive.google.com/file/d/synthetic-drive/view");
  expect(within(inspector).getByText(file.folder_path!)).toBeInTheDocument();
  expect(inspector).toHaveAttribute("tabindex", "0");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onOpenChange).toHaveBeenCalledWith(false, expect.anything());
});
it("retains demo preview behavior without adding the private inspector scope", () => {
  mode.demo = true;
  render(<FilePreviewSheet file={file} open onOpenChange={vi.fn()} />);
  expect(screen.getByRole("dialog")).not.toHaveClass("normal-workspace");
  expect(screen.getByRole("link", { name: "Ask about this file" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Open in Google Drive" })).toBeNull();
  expect(screen.queryByRole("region", { name: "File inspector" })).toBeNull();
});
