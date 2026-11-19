import { StrictMode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { DriveDiscovery } from "./drive-discovery";
import { getDriveSyncStatus, syncDriveMetadata } from "@/lib/api/indexing";
import { setSessionOwner } from "@/lib/api/session-events";
const owner = "00000000-0000-0000-0000-000000000065";
vi.mock("@/components/providers/application-session-provider", () => ({ useApplicationSession: () => ({ userId: "00000000-0000-0000-0000-000000000065" }) }));
vi.mock("@/lib/api/indexing", async original => ({ ...await original<typeof import("@/lib/api/indexing")>(), getDriveSyncStatus: vi.fn(), syncDriveMetadata: vi.fn() }));
beforeEach(() => {
  Object.defineProperty(navigator, "locks", { configurable: true, value: {
    request: async (_name: string, callback: () => unknown) => callback(),
  } });
  vi.clearAllMocks(); setSessionOwner(owner);
  const storage = new Map<string, string>();
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string, v: string) => storage.set(k, v), removeItem: (k: string) => storage.delete(k) } });
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: null });
});
afterEach(() => { cleanup(); setSessionOwner(null); });
it("has keyboard-operable metadata discovery with an announced outcome, including StrictMode", async () => {
  render(<StrictMode><DriveDiscovery /></StrictMode>);
  const action = screen.getByRole("button", { name: "Check Drive for files / changes" });
  await waitFor(() => expect(action).toBeEnabled()); expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  vi.mocked(syncDriveMetadata).mockRejectedValue(new Error("Unknown"));
  const user = userEvent.setup(); action.focus(); await user.keyboard("{Enter}");
  expect(await screen.findByText(/could not be confirmed/)).toBeInTheDocument(); expect(action).toBeDisabled();
  expect(syncDriveMetadata).toHaveBeenCalledExactlyOnceWith(false, expect.any(AbortSignal), expect.any(Function));
});
it("shows connection guidance and no discovery mutation when disconnected", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: false, job: null }); render(<DriveDiscovery />);
  expect(await screen.findByRole("link", { name: "Connect or check Drive access" })).toHaveAttribute("href", "/onboarding");
  expect(screen.getByRole("button", { name: "Check Drive for files / changes" })).toBeDisabled(); expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("compact discovery separates a status read from an explicit metadata check", async () => {
  render(<DriveDiscovery compact />);
  const action = screen.getByRole("button", { name: "Check for files" });
  await waitFor(() => expect(action).toBeEnabled());
  expect(screen.getByText("File details only; no content is prepared.")).toBeInTheDocument();
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  const reads = vi.mocked(getDriveSyncStatus).mock.calls.length;
  await userEvent.click(screen.getByRole("button", { name: "Check status" }));
  await waitFor(() => expect(vi.mocked(getDriveSyncStatus).mock.calls.length).toBeGreaterThan(reads));
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  vi.mocked(syncDriveMetadata).mockRejectedValue(new Error("Unknown acknowledgement"));
  await userEvent.click(action);
  expect(await screen.findByText(/could not be confirmed/)).toBeInTheDocument();
  expect(action).toBeDisabled();
  expect(syncDriveMetadata).toHaveBeenCalledExactlyOnceWith(false, expect.any(AbortSignal), expect.any(Function));
});

const failedMessage = "The Drive check failed. No documents were prepared. You can start a new check after reviewing your connection.";
const jobId = "00000000-0000-0000-0000-000000000123";
const discoveryKey = `drivemind:discovery:v1:${owner}`;
function discoveryJob(status: "running" | "completed" | "failed", recoveryRequired = false) {
  return { id: jobId, user_id: owner, operation: "SYNC" as const, status, recovery_required: recoveryRequired,
    processed: 2, total: 5, started_at: null, completed_at: null,
    error: status === "failed" ? "Synthetic discovery failure" : null, created_at: "", updated_at: "" };
}

it("compact mode announces a latest failed SYNC and keeps connection-review guidance without submitting", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("failed") });
  render(<DriveDiscovery compact />);
  const failure = await screen.findByText(failedMessage);
  expect(failure).toBeVisible(); expect(failure).toHaveAttribute("role", "status");
  expect(failure).toHaveAttribute("aria-live", "polite");
  expect(screen.getByText("2 of 5 metadata updates processed")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Check for files" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Check status" })).toBeEnabled();
  expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("compact mode observes an exact running job becoming failed without creating or retrying a job", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("running") });
  render(<DriveDiscovery compact />);
  expect(await screen.findByText("Drive discovery in progress.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Check for files" })).toBeDisabled();
  expect(JSON.parse(window.localStorage.getItem(discoveryKey)!)).toMatchObject({ jobId });
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("failed") });
  await userEvent.click(screen.getByRole("button", { name: "Check status" }));
  const failure = await screen.findByText(failedMessage);
  expect(failure).toHaveTextContent(failedMessage); expect(failure).toBeVisible();
  expect(failure).toHaveAttribute("aria-live", "polite");
  expect(getDriveSyncStatus).toHaveBeenLastCalledWith(jobId, expect.any(AbortSignal));
  expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("compact routine idle keeps its redundant guidance hidden and performs no SYNC", async () => {
  render(<DriveDiscovery compact />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Check for files" })).toBeEnabled());
  expect(screen.queryByText("Discover supported documents without preparing their content.")).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByText("File details only; no content is prepared.")).toBeVisible();
  expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("compact completed discovery retains its live success message and completion callback", async () => {
  const done = vi.fn();
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("completed") });
  render(<DriveDiscovery compact onComplete={done} />);
  expect(await screen.findByText("Drive check completed. 2 metadata updates processed.")).toHaveAttribute("role", "status");
  expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  expect(done).toHaveBeenCalledOnce(); expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("compact recovery-required failures stay blocked with their existing review guidance", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("failed", true) });
  render(<DriveDiscovery compact />);
  expect(await screen.findByText("Existing work needs review before discovery can continue. Ask the beta owner for help.")).toHaveAttribute("role", "status");
  expect(screen.getByRole("button", { name: "Check for files" })).toBeDisabled();
  expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("compact unknown acceptance remains announced and never replays the saved intent", async () => {
  const pending = { jobId: null, submissionId: "synthetic-submission" };
  window.localStorage.setItem(discoveryKey, JSON.stringify(pending));
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("completed") });
  render(<DriveDiscovery compact />);
  expect(await screen.findByText(/The discovery request could not be confirmed/)).toHaveAttribute("role", "status");
  expect(screen.getByRole("button", { name: "Check for files" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Check status" }));
  expect(JSON.parse(window.localStorage.getItem(discoveryKey)!)).toEqual(pending);
  expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("compact disconnected discovery preserves connection guidance and disables submission", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: false, job: null });
  render(<DriveDiscovery compact />);
  expect(await screen.findByRole("link", { name: "Connect or check Drive access" })).toHaveAttribute("href", "/onboarding");
  expect(screen.getByRole("button", { name: "Check for files" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Check status" })).toBeEnabled();
  expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("Files header uses the existing discovery controller, preserves uncertain receipts and never submits on observation", async () => {
  const intent = { jobId: null, submissionId: "header-uncertain" };
  window.localStorage.setItem(discoveryKey, JSON.stringify(intent));
  render(<DriveDiscovery filesHeader />);
  expect(await screen.findByText(/The discovery request could not be confirmed/)).toHaveAttribute("aria-live", "polite");
  expect(screen.getByRole("button", { name: "Sync Drive" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Check sync status" }));
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  expect(JSON.parse(window.localStorage.getItem(discoveryKey)!)).toEqual(intent);
});
it("Files header explicitly submits metadata sync through the existing receipt-aware action", async () => {
  render(<DriveDiscovery filesHeader />);
  const sync = screen.getByRole("button", { name: "Sync Drive" });
  await waitFor(() => expect(sync).toBeEnabled());
  vi.mocked(syncDriveMetadata).mockRejectedValue(new Error("Unknown acknowledgement"));
  await userEvent.click(sync);
  expect(await screen.findByText(/could not be confirmed/)).toBeInTheDocument();
  expect(syncDriveMetadata).toHaveBeenCalledExactlyOnceWith(false, expect.any(AbortSignal), expect.any(Function));
  expect(sync).toBeDisabled();
});

it("KI-010/KI-011 in the UI: a finished preparation does not block the button; unfinished work explains itself", async () => {
  const uid = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
  const entry = { fileId: uid(1), runId: uid(51), frame: "frame", receipts: ["INGEST", "CHUNK", "BUILD"].map((stage, i) => ({ stage, submissionId: uid(500 + i), jobId: uid(11 + i) })), result: "ready" };
  const record = (current: number, entries: unknown[]) => ({ schemaVersion: 2, owner, batchId: uid(200), current, entries });
  const prep = `drivemind:preparation:v1:${owner}`;
  // Unfinished: the user is told why, and the backend is never called.
  window.localStorage.setItem(prep, JSON.stringify(record(0, [{ ...entry, receipts: [], result: "pending" }])));
  render(<DriveDiscovery compact />);
  const action = screen.getByRole("button", { name: "Check for files" });
  await waitFor(() => expect(action).toBeEnabled());
  await userEvent.click(action);
  expect(await screen.findByText(/document preparation is unfinished/)).toHaveAttribute("role", "status");
  expect(screen.queryByText(/verify your connection/i)).toBeNull();
  expect(syncDriveMetadata).not.toHaveBeenCalled();
  cleanup();
  // Finished: the same click now submits the sync.
  window.localStorage.setItem(prep, JSON.stringify(record(1, [entry])));
  vi.mocked(syncDriveMetadata).mockResolvedValue({ job_id: uid(900), status: "queued", message: "Accepted" });
  render(<DriveDiscovery compact />);
  const again = screen.getByRole("button", { name: "Check for files" });
  await waitFor(() => expect(again).toBeEnabled());
  await userEvent.click(again);
  await waitFor(() => expect(syncDriveMetadata).toHaveBeenCalledOnce());
  expect(window.localStorage.getItem(prep)).toBeNull();
});

it("KI-012 in the UI: pressing Check status mid-poll gives visible feedback, joins the read, and never submits", async () => {
  let release!: (v: { connected: boolean; job: null }) => void;
  const pending = new Promise<{ connected: boolean; job: null }>(r => { release = r; });
  vi.mocked(getDriveSyncStatus).mockResolvedValueOnce({ connected: true, job: null });   // the initial mount read
  render(<DriveDiscovery compact />);
  const check = screen.getByRole("button", { name: "Check status" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Check for files" })).toBeEnabled());
  vi.mocked(getDriveSyncStatus).mockClear();
  vi.mocked(getDriveSyncStatus).mockImplementation(() => pending);
  await userEvent.click(check);
  expect(screen.getByText("Checking…")).toHaveAttribute("role", "status");   // immediate acknowledgement
  expect(check).toBeDisabled();                                              // cannot be spammed
  expect(getDriveSyncStatus).toHaveBeenCalledOnce();
  release({ connected: true, job: null });
  expect(await screen.findByText(/Checked at .*\. No change\./)).toHaveAttribute("role", "status");
  expect(check).toBeEnabled();
  expect(syncDriveMetadata).not.toHaveBeenCalled();
});

it("KI-012 in the UI: when the check finds something new the note says the status was updated", async () => {
  render(<DriveDiscovery compact />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Check for files" })).toBeEnabled());
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("completed") });
  await userEvent.click(screen.getByRole("button", { name: "Check status" }));
  expect(await screen.findByText(/Checked at .*\. Status updated\./)).toBeInTheDocument();
});

it("KI-012 in the UI: a repeat click that finds the same blocked message still visibly shows a check happened", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("failed", true) });
  render(<DriveDiscovery compact />);
  await screen.findByText("Existing work needs review before discovery can continue. Ask the beta owner for help.");
  await userEvent.click(screen.getByRole("button", { name: "Check status" }));
  expect(await screen.findByText(/Checked at .*\. No change\./)).toBeInTheDocument();
});

it("KI-012 in the UI: the files-header 'Check sync status' button gives the same feedback", async () => {
  vi.mocked(getDriveSyncStatus).mockResolvedValue({ connected: true, job: discoveryJob("running") });   // a sync in progress keeps the feedback area visible
  render(<DriveDiscovery filesHeader />);
  await screen.findByText("Drive discovery in progress.");
  await userEvent.click(screen.getByRole("button", { name: "Check sync status" }));
  expect(await screen.findByText(/Checked at .*\. No change\./)).toBeInTheDocument();
});
