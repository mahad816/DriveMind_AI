import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PrepareKnowledgeView } from "@/components/knowledge/prepare-knowledge-view";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { prepareKnowledge } from "@/lib/knowledge/prepare";

vi.mock("@/lib/knowledge/prepare", () => ({ prepareKnowledge: vi.fn() }));
vi.mock("@/lib/knowledge/storage", () => ({ setLastPreparedAt: vi.fn() }));
vi.mock("@/lib/hooks/use-knowledge-status", () => ({ useKnowledgeStatus: vi.fn() }));
vi.mock("@/lib/api/auth", () => ({ getGoogleAuthUrl: () => "/api/v1/auth/google" }));
vi.mock("@/components/knowledge/advanced-diagnostics", () => ({
  AdvancedDiagnostics: () => <div>advanced diagnostics</div>,
}));

function status(setupState: "checking" | "not_connected" | "connected_not_ready" | "preparing" | "ready" | "error") {
  return {
    setupState,
    jobError: null,
    isConnected: setupState === "connected_not_ready" || setupState === "preparing" || setupState === "ready",
    needsConnect: setupState === "not_connected",
    isReady: setupState === "ready",
    needsPrepare: setupState === "connected_not_ready",
    fileStats: { total: 0, indexed: 0, failed: 0, skipped: 0 },
    lastPreparedAt: null,
    lastPreparedLabel: null,
    refresh: vi.fn().mockResolvedValue(undefined),
    isLoading: setupState === "checking",
    error: setupState === "error" ? "Could not check Google Drive connection" : null,
  };
}

describe("PrepareKnowledgeView", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("connected_not_ready"));
  });

  it("shows a confirmed disconnected state and a real Connect action", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("not_connected"));
    render(<PrepareKnowledgeView />);

    expect(screen.getByText("Not connected")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect Google Drive" })).toHaveAttribute("href", "/api/v1/auth/google");
    expect(screen.queryByRole("button", { name: "Prepare knowledge" })).not.toBeInTheDocument();
  });

  it("shows preparation only when connected but not ready", () => {
    render(<PrepareKnowledgeView />);
    expect(screen.getByText("Knowledge needs preparation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare knowledge" })).toBeEnabled();
  });

  it("does not auto-start preparation and shows one truthful pending state", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("preparing"));
    render(<PrepareKnowledgeView />);
    expect(prepareKnowledge).not.toHaveBeenCalled();
    expect(screen.getByText("Preparing your knowledge…")).toBeInTheDocument();
    expect(screen.queryByText(/% complete/)).not.toBeInTheDocument();
  });

  it("shows real indexed and failed file counts when ready", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue({
      ...status("ready"),
      fileStats: { total: 5, indexed: 3, failed: 2, skipped: 0 },
    });
    render(<PrepareKnowledgeView />);
    expect(screen.getByText("3 files ready")).toBeInTheDocument();
    expect(screen.getByText("2 files need attention")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start chatting" })).toHaveAttribute("href", "/chat");
  });

  it("refreshes status without starting preparation", () => {
    const current = status("connected_not_ready");
    vi.mocked(useKnowledgeStatus).mockReturnValue(current);
    render(<PrepareKnowledgeView />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    expect(current.refresh).toHaveBeenCalledOnce();
    expect(prepareKnowledge).not.toHaveBeenCalled();
  });

  it("keeps connection/status errors distinct from disconnection", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue(status("error"));
    render(<PrepareKnowledgeView />);
    expect(screen.getByText("Knowledge status unavailable")).toBeInTheDocument();
    expect(screen.getByText("Could not check Google Drive connection")).toBeInTheDocument();
    expect(screen.queryByText("Not connected")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry status check" })).toBeInTheDocument();
  });

  it("keeps a confirmed Drive connection visible when only file status is unavailable", () => {
    vi.mocked(useKnowledgeStatus).mockReturnValue({
      ...status("error"),
      isConnected: true,
      error: "Could not load file status",
    });
    render(<PrepareKnowledgeView />);
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Knowledge status unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Not connected")).not.toBeInTheDocument();
  });

  it("reports a completed run without claiming ready when no file is indexed", async () => {
    vi.mocked(prepareKnowledge).mockResolvedValue({ warning: null });
    render(<PrepareKnowledgeView />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare knowledge" }));

    await waitFor(() => expect(screen.getByText("Preparation finished, but no files are ready yet.")).toBeInTheDocument());
    expect(screen.queryByText("Knowledge ready")).not.toBeInTheDocument();
  });

  it("shows partial preparation warnings without inventing an indexed count", async () => {
    vi.mocked(prepareKnowledge).mockResolvedValue({ warning: "15 of 60 files failed during ingestion." });
    render(<PrepareKnowledgeView />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare knowledge" }));

    expect(await screen.findByText("15 of 60 files failed during ingestion.")).toBeInTheDocument();
    expect(screen.queryByText(/files ready/)).not.toBeInTheDocument();
  });
});
