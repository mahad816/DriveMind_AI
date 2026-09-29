import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingAwareHomeRedirect, OnboardingGate } from "@/components/onboarding/onboarding-gate";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";

const replace = vi.fn();
let pathname = "/";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ replace }),
}));
vi.mock("@/lib/hooks/use-knowledge-status", () => ({ useKnowledgeStatus: vi.fn() }));

function status(setupState: "checking" | "not_connected" | "connected_not_ready" | "preparing" | "ready" | "error") {
  return {
    setupState,
    jobError: null,
    isConnected: setupState === "ready",
    needsConnect: setupState === "not_connected",
    isReady: setupState === "ready",
    needsPrepare: setupState === "connected_not_ready",
    fileStats: { total: 0, indexed: 0, failed: 0, skipped: 0 },
    lastPreparedAt: null,
    lastPreparedLabel: null,
    refresh: vi.fn(),
    isLoading: setupState === "checking",
    error: setupState === "error" ? "Unavailable" : null,
  };
}

describe("setup-aware entry routing", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    pathname = "/";
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("checking"));
  });

  it("waits for status before redirecting from the root", () => {
    render(<OnboardingAwareHomeRedirect />);
    expect(replace).not.toHaveBeenCalled();
  });

  it("routes confirmed not-ready state to onboarding", async () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("connected_not_ready"));
    render(<OnboardingAwareHomeRedirect />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/onboarding"));
  });

  it("routes confirmed disconnection to onboarding", async () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("not_connected"));
    render(<OnboardingAwareHomeRedirect />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/onboarding"));
  });

  it("routes active preparation to the setup progress experience", async () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("preparing"));
    render(<OnboardingAwareHomeRedirect />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/onboarding"));
  });

  it("routes ready state to chat even without a browser-local completion flag", async () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("ready"));
    render(<OnboardingAwareHomeRedirect />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/chat"));
  });

  it("keeps a status error at root with an honest retry, not a setup or chat redirect", () => {
    const current = status("error");
    vi.mocked(useKnowledgeStatus).mockReturnValue(current);
    render(<OnboardingAwareHomeRedirect />);

    expect(screen.getByText("Knowledge status unavailable")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry status check" }));
    expect(current.refresh).toHaveBeenCalledOnce();
    expect(replace).not.toHaveBeenCalled();
  });

  it("does not let a stale browser-local completion flag bypass confirmed not-ready state", async () => {
    pathname = "/chat";
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("not_connected"));
    render(<OnboardingGate><p>Chat</p></OnboardingGate>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/onboarding"));
    expect(screen.queryByText("Chat")).not.toBeInTheDocument();
  });

  it("does not briefly show chat while readiness is being checked", () => {
    pathname = "/chat";
    render(<OnboardingGate><p>Chat</p></OnboardingGate>);
    expect(screen.getByText("Checking your Drive knowledge…")).toBeInTheDocument();
    expect(screen.queryByText("Chat")).not.toBeInTheDocument();
  });

  it("does not treat a failed status request as confirmed disconnection", () => {
    pathname = "/chat";
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("error"));
    render(<OnboardingGate><p>Chat</p></OnboardingGate>);
    expect(replace).not.toHaveBeenCalled();
  });
});
