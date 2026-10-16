vi.mock("@/components/providers/application-session-provider", () => ({
  useApplicationSession: () => ({ userId: "00000000-0000-0000-0000-000000000065", connectDrive: vi.fn(), logout: vi.fn(), error: null }),
}));
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingFlow } from "@/components/onboarding/onboarding-flow";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/hooks/use-knowledge-status", () => ({ useKnowledgeStatus: vi.fn() }));
vi.mock("@/lib/onboarding/storage", () => ({
  markOnboardingComplete: vi.fn(),
  setOnboardingOAuthPending: vi.fn(),
}));
vi.mock("@/components/knowledge/prepare-knowledge-view", () => ({
  PrepareKnowledgeView: () => <button type="button">Prepare knowledge</button>,
}));

function status(setupState: "checking" | "not_connected" | "connected_not_ready" | "preparing" | "ready" | "error") {
  return {
    setupState,
    jobError: null,
    isConnected: setupState !== "not_connected" && setupState !== "error" && setupState !== "checking",
    needsConnect: setupState === "not_connected",
    isReady: setupState === "ready",
    needsPrepare: setupState === "connected_not_ready",
    fileStats: { total: 0, indexed: 0, failed: 0, skipped: 0 },
    lastPreparedAt: null,
    lastPreparedLabel: null,
    refresh: vi.fn().mockResolvedValue(undefined),
    isLoading: setupState === "checking",
    error: setupState === "error" ? "Connection check failed" : null,
  };
}

afterEach(cleanup);

describe("OnboardingFlow", () => {

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("checking"));
  });

  it("shows sign-in, connection, discovery and future preparation distinctly", () => {
    render(<OnboardingFlow />);
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText("Checking your Drive connection…")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });
  it("offers connection only for confirmed disconnection", async () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("not_connected")); render(<OnboardingFlow />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Google Drive" }));
    expect(screen.getByRole("button", { name: "Connect Google Drive" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Prepare knowledge" })).toBeNull();
  });
  it("offers file browsing with zero indexed documents and no preparation action", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("connected_not_ready")); render(<OnboardingFlow />);
    expect(screen.getByRole("link", { name: "Browse and discover files" })).toHaveAttribute("href", "/files");
    expect(screen.queryByRole("button", { name: "Prepare knowledge" })).toBeNull();
  });
  it("preserves chat access for an indexed user", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue({ ...status("ready"), fileStats: { total: 2, indexed: 1, failed: 0, skipped: 0 } });
    render(<OnboardingFlow />); expect(screen.getByRole("link", { name: "Start chatting" })).toHaveAttribute("href", "/chat");
  });
  it("does not turn an unavailable check into a disconnected state", () => {
    const current = status("error"); vi.mocked(useKnowledgeStatus).mockReturnValue(current); render(<OnboardingFlow />);
    expect(screen.queryByRole("button", { name: "Connect Google Drive" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry status check" })); expect(current.refresh).toHaveBeenCalledOnce();
  });
});

it("describes reviewed selection of up to five without automatic processing", () => {
  vi.mocked(useKnowledgeStatus).mockReturnValue(status("connected_not_ready")); render(<OnboardingFlow />);
  expect(screen.getByText(/Choose up to five documents, review, then prepare one at a time/)).toBeInTheDocument();
  expect(screen.getByText(/Discovering files is separate/)).toBeInTheDocument();
});
it("keeps prepared knowledge available while reconnecting Drive", () => {
  vi.mocked(useKnowledgeStatus).mockReturnValue({ ...status("ready"), isConnected: false, fileStats: { total: 2, indexed: 1, failed: 0, skipped: 0 } });
  render(<OnboardingFlow />); expect(screen.getByRole("link", { name: "Start chatting" })).toHaveAttribute("href", "/chat");
  expect(screen.getByRole("button", { name: "Connect Google Drive" })).toBeInTheDocument();
});
