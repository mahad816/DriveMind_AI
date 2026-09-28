import { cleanup, render, screen } from "@testing-library/react";
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
});
