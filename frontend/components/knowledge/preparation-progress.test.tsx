import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { PreparationProgress } from "./preparation-progress";
import type { DriveFileRead, IndexingJobRead } from "@/lib/api/types";
import type { PreparationQueueState } from "@/lib/knowledge/preparation-queue";
import { preparationFrame } from "@/lib/knowledge/single-file-preparation";

const owner = "00000000-0000-0000-0000-000000000065";
const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
function fixture() {
  const files: DriveFileRead[] = [0, 1, 2].map(n => ({ id: id(n + 1), user_id: owner, drive_file_id: `drive-${n}`, name: `Architecture decisions ${n + 1}.txt`, mime_type: "text/plain", status: "indexing", folder_path: "Engineering", modified_at: "2026-01-01", indexed_at: null, created_at: "", updated_at: "" }));
  files[1].status = "discovered"; files[2].status = "discovered";
  const job: IndexingJobRead = { id: id(100), user_id: owner, file_id: files[0].id, operation: "INGEST", status: "running", total: 1, processed: 0, succeeded: 0, failed: 0, skipped: 0, recovery_required: false, started_at: null, completed_at: null, created_at: "", updated_at: "", error: null };
  const state: PreparationQueueState = { phase: "progress", message: "Preparation stage in progress.", queue: { schemaVersion: 2, owner, batchId: id(200), current: 0, entries: files.map((f, n) => ({ fileId: f.id, frame: preparationFrame(f), runId: id(300 + n), result: "pending", receipts: n === 0 ? [{ stage: "INGEST", submissionId: id(400), jobId: job.id }] : [] })) }, child: { phase: "active", file: files[0], job, stage: "INGEST", message: "Preparation stage in progress.", canRelease: false } };
  const props = { owner, state, inventory: files, metadataError: false, actionError: null, working: false, canConfirm: false, onConfirm: vi.fn(), onCheck: vi.fn(), onClose: vi.fn(), onLeave: vi.fn(), onBack: vi.fn() };
  return { files, job, state, props };
}
afterEach(cleanup);
it("shows one authoritative progress panel and locates exact stages under the active file", () => {
  const f = fixture(); render(<PreparationProgress {...f.props} />);
  expect(screen.getAllByRole("region", { name: "Preparation progress" })).toHaveLength(1);
  expect(screen.getByText("1 active")).toBeInTheDocument();
  expect(screen.getByText("2 awaiting confirmation")).toBeInTheDocument();
  const stages = screen.getByRole("list", { name: "Processing stages" });
  expect(stages.previousElementSibling).toHaveTextContent(f.files[0].name);
  expect(stages.closest("li")).toHaveClass("is-active");
  expect(within(stages).getByText(/Reading document/)).toHaveTextContent("In progress");
  expect(screen.queryByRole("button", { name: "Check status" })).toBeNull();
  expect(screen.queryByRole("progressbar")).toBeNull();
});
it("distinguishes server-queued work from a locally waiting document", () => {
  const f = fixture(); f.job.status = "queued"; render(<PreparationProgress {...f.props} />);
  expect(screen.queryByText("1 active")).toBeNull(); expect(screen.getByText("1 queued")).toBeInTheDocument();
  expect(screen.getAllByText("Waiting")).toHaveLength(2);
  expect(screen.getByText("Queued", { selector: ".preparation-file-status span" })).toBeInTheDocument();
});
it("falls back to general Preparing when an exact job cannot be established", () => {
  const f = fixture(); f.job.id = id(999); render(<PreparationProgress {...f.props} />);
  expect(screen.queryByRole("list", { name: "Processing stages" })).toBeNull();
  expect(screen.getByText("Preparing", { selector: ".preparation-file-status span" })).toBeInTheDocument();
});
it("does not mark an intermediate completed job Ready and requires keyboard confirmation", async () => {
  const f = fixture(); Object.assign(f.job, { status: "completed", processed: 1, succeeded: 1 }); f.state.child!.phase = "continue"; f.props.canConfirm = true;
  render(<PreparationProgress {...f.props} />);
  expect(screen.queryByText("Ready", { selector: ".preparation-file-status span" })).toBeNull();
  expect(screen.getByText("0 of 3")).toBeInTheDocument();
  expect(screen.getByText("Awaiting confirmation")).toBeInTheDocument();
  const action = screen.getByRole("button", { name: "Continue preparation" }); action.focus(); await userEvent.keyboard("{Enter}");
  expect(f.props.onConfirm).toHaveBeenCalledOnce();
});
it.each(["failed", "skipped"] as const)("keeps %s persistent and preserves earlier Ready results without Retry", result => {
  const f = fixture(); f.files[0].status = "indexed"; f.state.queue!.entries[0].result = "ready"; f.state.queue!.current = 1;
  f.state.queue!.entries[1].result = result; f.state.phase = "stopped"; f.state.child = { ...f.state.child!, file: f.files[1], phase: result, canRelease: true };
  f.state.message = result === "failed" ? "This stage failed. Ask the beta owner to review it before retrying." : "This document was skipped. It may not contain searchable text.";
  render(<PreparationProgress {...f.props} />);
  expect(screen.getByRole("alert")).toHaveTextContent(f.state.message);
  expect(screen.getByText("Ready", { selector: ".preparation-file-status span" })).toBeInTheDocument();
  expect(screen.getByText(result === "failed" ? "Failed" : "Skipped", { selector: ".preparation-file-status span" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Retry|Prepare next/ })).toBeNull();
  expect(screen.getByRole("button", { name: "End preparation" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Start chatting" })).toHaveAttribute("href", "/chat");
});
it("shows clean completion with Ready rows, chat and one Back action while retaining safe release", () => {
  const f = fixture(); f.state.phase = "complete"; f.state.child = null; f.state.queue!.current = 3;
  f.files.forEach(file => { file.status = "indexed"; }); f.state.queue!.entries.forEach(entry => { entry.result = "ready"; });
  render(<PreparationProgress {...f.props} />);
  expect(screen.getByRole("heading", { name: "Documents ready" })).toBeInTheDocument();
  expect(screen.getAllByText("Ready", { selector: ".preparation-file-status span" })).toHaveLength(3);
  expect(screen.queryByText(/0 active|0 queued/)).toBeNull();
  expect(screen.getAllByRole("button", { name: "Back to files" })).toHaveLength(1);
  expect(screen.getByRole("link", { name: "Start chatting" })).toHaveAttribute("href", "/chat");
  fireEvent.click(screen.getByRole("button", { name: "Back to files" })); expect(f.props.onBack).toHaveBeenCalledOnce(); expect(f.props.onClose).not.toHaveBeenCalled();
});
it("suppresses stage and success claims on uncertain responses or missing metadata", () => {
  const f = fixture(); f.state.phase = "blocked"; f.state.child!.phase = "unknown";
  f.state.message = "The request could not be confirmed. Check status; do not submit it again.";
  const view = render(<PreparationProgress {...f.props} />);
  expect(screen.getByRole("alert")).toHaveTextContent(f.state.message);
  expect(screen.queryByRole("list", { name: "Processing stages" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Continue|Retry|End preparation/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Check status" })); expect(f.props.onCheck).toHaveBeenCalledOnce();
  view.rerender(<PreparationProgress {...f.props} inventory={null} metadataError />);
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(screen.queryByRole("link", { name: "Start chatting" })).toBeNull();
  expect(screen.getAllByText("Document details unavailable")).toHaveLength(3);
});
it("does not restore Ready after a metadata change or a blocked history check", () => {
  const f = fixture(); f.state.phase = "complete"; f.state.queue!.current = 3; f.state.child = null;
  f.state.queue!.entries.forEach(entry => { entry.result = "ready"; }); f.files.forEach(file => { file.status = "indexed"; });
  f.files[0].modified_at = "2026-02-01";
  const view = render(<PreparationProgress {...f.props} />);
  expect(screen.queryByRole("heading", { name: "Documents ready" })).toBeNull();
  f.state.phase = "blocked"; view.rerender(<PreparationProgress {...f.props} />);
  expect(screen.queryByText("Ready", { selector: ".preparation-file-status span" })).toBeNull();
});

it("announces initial metadata verification without flashing a failure or unverified completion", () => {
  const f = fixture(); f.state.phase = "complete"; f.state.child = null; f.state.queue!.current = 3;
  f.state.queue!.entries.forEach(entry => { entry.result = "ready"; });
  render(<PreparationProgress {...f.props} inventory={null} />);
  expect(screen.getByRole("heading", { name: "Checking preparation" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("heading", { name: "Documents ready" })).toBeNull();
  expect(screen.getByRole("button", { name: "Close completed preparation" })).toBeDisabled();
  expect(screen.getAllByRole("status")).toHaveLength(1);
});
