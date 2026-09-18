import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PrepareKnowledgeView } from "@/components/knowledge/prepare-knowledge-view";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { prepareKnowledge } from "@/lib/knowledge/prepare";

vi.mock("@/lib/knowledge/prepare", () => ({ prepareKnowledge: vi.fn() }));
vi.mock("@/lib/hooks/use-knowledge-status", () => ({ useKnowledgeStatus: vi.fn() }));
vi.mock("@/lib/knowledge/storage", () => ({ setLastPreparedAt: vi.fn() }));
vi.mock("@/lib/onboarding/storage", () => ({ markOnboardingComplete: vi.fn() }));
vi.mock("@/components/knowledge/prepare-progress", () => ({
  PrepareProgress: () => <div>prepare progress</div>,
}));
vi.mock("@/components/knowledge/advanced-diagnostics", () => ({
  AdvancedDiagnostics: () => <div>advanced diagnostics</div>,
}));

describe("PrepareKnowledgeView", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useKnowledgeStatus).mockReturnValue({
      isConnected: true,
      needsConnect: false,
      isReady: false,
      needsPrepare: true,
      fileStats: { total: 0, indexed: 0, failed: 0, skipped: 0 },
      lastPreparedAt: null,
      lastPreparedLabel: null,
      refresh: vi.fn().mockResolvedValue(undefined),
      isLoading: false,
      error: null,
    });
  });

  it("shows a ready state with the ingestion warning after healthy files finish", async () => {
    vi.mocked(prepareKnowledge).mockResolvedValue({
      warning: "15 of 60 files failed during ingestion.",
    });
    render(<PrepareKnowledgeView />);

    fireEvent.click(screen.getByRole("button", { name: "Set up my assistant" }));

    expect(
      await screen.findByText("Setup completed with some file failures"),
    ).toBeInTheDocument();
    expect(screen.getByText("15 of 60 files failed during ingestion.")).toBeInTheDocument();
    expect(
      screen.getByText("Other eligible files were prepared and are available for search."),
    ).toBeInTheDocument();
    expect(screen.getByText("Your assistant is ready")).toBeInTheDocument();
    expect(screen.queryByText("Setup failed")).not.toBeInTheDocument();
  });

  it("does not show the partial warning after a fully successful setup", async () => {
    vi.mocked(prepareKnowledge).mockResolvedValue({ warning: null });
    render(<PrepareKnowledgeView />);

    fireEvent.click(screen.getByRole("button", { name: "Set up my assistant" }));

    expect(await screen.findByText("Your assistant is ready")).toBeInTheDocument();
    expect(screen.queryByText("Setup completed with some file failures")).not.toBeInTheDocument();
  });
});
