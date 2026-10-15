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
