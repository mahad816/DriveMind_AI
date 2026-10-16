const actions = vi.hoisted(() => ({ connectDrive: vi.fn(), logout: vi.fn() }));
vi.mock("@/components/providers/application-session-provider", () => ({
  useApplicationSession: () => ({ userId: "00000000-0000-0000-0000-000000000065", connectDrive: actions.connectDrive, logout: actions.logout, error: null }),
}));
import { cleanup, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsDriveSection } from "@/components/settings/settings-drive-section";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: vi.fn() }));
vi.mock("@/lib/settings/storage", () => ({ getConnectedEmail: () => null }));

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("Google Drive access actions", () => {
  it("describes the Google permissions link without claiming an in-app disconnect", () => {
    vi.mocked(useConnectionStatus).mockReturnValue({
      data: { connected: true, job: null },
      isLoading: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
    });

    render(<SettingsDriveSection />);

    expect(screen.queryByText(/00000000-0000/)).toBeNull();
    expect(screen.getByRole("heading", { name: "Account" })).toBeInTheDocument();
    expect(screen.getByText("Manage Google access")).toBeInTheDocument();
    expect(screen.queryByText("Disconnect")).not.toBeInTheDocument();
  });

  it("shows a connection error and retry instead of a fake disconnected state", () => {
    const refetch = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useConnectionStatus).mockReturnValue({
      data: null,
      isLoading: false,
      error: "Connection check failed",
      refetch,
    });
    render(<SettingsDriveSection />);

    expect(screen.getByText("Drive status unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Not connected")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Connect Google Drive" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh Drive status" }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});

it("groups account and Drive controls under named sections without changing their actions", async () => {
  const refetch = vi.fn().mockResolvedValue(undefined);
  vi.mocked(useConnectionStatus).mockReturnValue({ data: { connected: true, job: null }, isLoading: false, error: null, refetch });
  render(<SettingsDriveSection />);
  const account = within(screen.getByRole("region", { name: "Account" }));
  const drive = within(screen.getByRole("region", { name: "Google Drive" }));
  expect(account.getByRole("heading", { level: 2, name: "Account" })).toBeInTheDocument();
  expect(account.getByText(/Prepared documents and Google Drive permissions are kept/)).toBeInTheDocument();
  expect(drive.getByRole("status")).toHaveTextContent("Google Drive connected");
  expect(drive.getByText(/Read-only access/)).toBeInTheDocument();
  fireEvent.click(drive.getByRole("button", { name: "Refresh Drive status" }));
  expect(refetch).toHaveBeenCalledOnce(); expect(actions.connectDrive).not.toHaveBeenCalled();
  expect(drive.getByRole("link", { name: "Manage Google access" })).toHaveAttribute("href", "https://myaccount.google.com/permissions");
  fireEvent.click(drive.getByRole("button", { name: "Reconnect Google Drive" }));
  expect(actions.connectDrive).toHaveBeenCalledOnce();
  await waitFor(() => expect(drive.getByRole("button", { name: "Reconnect Google Drive" })).toBeEnabled());
  fireEvent.click(account.getByRole("button", { name: "Sign out of DriveMind" }));
  expect(actions.logout).toHaveBeenCalledOnce();
});
it("keeps disconnected and loading status truthful with the existing connect prerequisites", () => {
  vi.mocked(useConnectionStatus).mockReturnValue({ data: { connected: false, job: null }, isLoading: false, error: null, refetch: vi.fn() });
  const view = render(<SettingsDriveSection />);
  expect(screen.getByRole("status")).toHaveTextContent("Google Drive not connected");
  expect(screen.getByRole("button", { name: "Connect Google Drive" })).toBeEnabled();
  expect(screen.queryByRole("link", { name: "Manage Google access" })).toBeNull();
  vi.mocked(useConnectionStatus).mockReturnValue({ data: null, isLoading: true, error: null, refetch: vi.fn() });
  view.rerender(<SettingsDriveSection />);
  expect(screen.getByRole("status")).toHaveTextContent("Checking Google Drive…");
  expect(screen.getByRole("button", { name: "Connect Google Drive" })).toBeDisabled();
  expect(actions.connectDrive).not.toHaveBeenCalled(); expect(actions.logout).not.toHaveBeenCalled();
});
