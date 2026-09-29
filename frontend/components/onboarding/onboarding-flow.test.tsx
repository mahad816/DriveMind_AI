import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingFlow } from "@/components/onboarding/onboarding-flow";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { markOnboardingComplete } from "@/lib/onboarding/storage";

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

describe("OnboardingFlow", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("checking"));
  });

  it("shows a restrained two-step journey while checking", () => {
    render(<OnboardingFlow />);
    expect(screen.getByRole("heading", { name: "Set up your Drive knowledge" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Checking your Drive connection…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start chatting" })).not.toBeInTheDocument();
  });

  it("offers Connect when Drive is confirmed disconnected", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("not_connected"));
    render(<OnboardingFlow />);
    expect(screen.getByRole("button", { name: "Connect Google Drive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prepare knowledge" })).not.toBeInTheDocument();
  });

  it("offers Prepare when connected but not ready", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("connected_not_ready"));
    render(<OnboardingFlow />);
    expect(screen.getByRole("heading", { name: "Prepare your knowledge" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare knowledge" })).toBeInTheDocument();
  });

  it("shows preparation without claiming completion or a percentage", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("preparing"));
    render(<OnboardingFlow />);
    expect(screen.getByRole("heading", { name: "Preparing your knowledge…" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start chatting" })).not.toBeInTheDocument();
    expect(screen.queryByText(/% complete/)).not.toBeInTheDocument();
  });

  it("offers Start chatting only after indexed files make knowledge ready", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue({
      ...status("ready"),
      fileStats: { total: 2, indexed: 1, failed: 0, skipped: 1 },
    });
    render(<OnboardingFlow />);
    expect(screen.getByText("1 file ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start chatting" }));
    expect(markOnboardingComplete).toHaveBeenCalledOnce();
    expect(push).toHaveBeenCalledWith("/chat");
  });

  it("treats status failure as unavailable, not disconnected", () => {
    const current = status("error");
    vi.mocked(useKnowledgeStatus).mockReturnValue(current);
    render(<OnboardingFlow />);
    expect(screen.getByText("Knowledge status unavailable")).toBeInTheDocument();
    expect(screen.getByText("Connection check failed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect Google Drive" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry status check" }));
    expect(current.refresh).toHaveBeenCalledOnce();
  });

  it("retains the completed connection step when only knowledge status fails", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue({
      ...status("error"),
      isConnected: true,
      error: "Could not load file status",
    });
    render(<OnboardingFlow />);
    expect(screen.getByText("Knowledge status unavailable")).toBeInTheDocument();
    expect(screen.getByText("Could not load file status")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect Google Drive" })).not.toBeInTheDocument();
  });
});
