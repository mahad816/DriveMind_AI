vi.mock("@/components/providers/application-session-provider", () => ({
  useApplicationSession: () => ({ userId: "00000000-0000-0000-0000-000000000065", connectDrive: vi.fn(), logout: vi.fn(), error: null }),
}));
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsDriveSection } from "@/components/settings/settings-drive-section";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: vi.fn() }));
vi.mock("@/lib/settings/storage", () => ({ getConnectedEmail: () => null }));

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
