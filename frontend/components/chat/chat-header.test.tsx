import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInterface } from "@/components/chat/chat-interface";
import { createConversation, updateConversationTitle } from "@/lib/conversations/storage";

const router = { push: vi.fn(), replace: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/hooks/use-connection-status", () => ({
  useConnectionStatus: () => ({ data: { connected: true }, error: null, refetch: vi.fn() }),
}));
vi.mock("@/lib/hooks/use-knowledge-status", () => ({
  useKnowledgeStatus: () => ({ needsConnect: false, needsPrepare: false }),
}));
vi.mock("@/lib/hooks/use-chat-shortcuts", () => ({ useChatShortcuts: vi.fn() }));
vi.mock("@/components/chat/composer-dock", () => ({
  ComposerDock: () => <div data-testid="composer" />,
}));
vi.mock("@/components/chat/empty-state-hero", () => ({
  EmptyStateHero: () => <div>Empty conversation</div>,
}));
vi.mock("@/components/chat/source-panel", () => ({ SourcePanel: () => null }));

beforeEach(() => {
  const store: Record<string, string> = {};
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => { store[key] = value; },
      removeItem: (key: string) => { delete store[key]; },
      clear: () => { Object.keys(store).forEach((key) => delete store[key]); },
    },
  });
  vi.clearAllMocks();
});
afterEach(cleanup);

describe("current chat header", () => {
  it("shows the active conversation title without repeating DriveMind branding", async () => {
    const active = createConversation("Budget notes");
    render(<ChatInterface conversationId={active.id} />);

    const header = await screen.findByRole("banner");
    expect(within(header).getByText("Budget notes")).toBeInTheDocument();
    expect(within(header).queryByText("DriveMind AI")).not.toBeInTheDocument();
  });

  it("updates the title after rename and never shows the previous chat title on an empty canvas", async () => {
    const active = createConversation("Budget notes");
    const { rerender } = render(<ChatInterface conversationId={active.id} />);
    await screen.findByRole("banner");

    updateConversationTitle(active.id, "Trip notes");
    await waitFor(() => expect(within(screen.getByRole("banner")).getByText("Trip notes")).toBeInTheDocument());

    rerender(<ChatInterface />);
    expect(screen.queryByText("Trip notes")).not.toBeInTheDocument();
    expect(screen.queryByText("Budget notes")).not.toBeInTheDocument();
  });
});
