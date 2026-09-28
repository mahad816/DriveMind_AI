import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationSidebar } from "@/components/layout/conversation-sidebar";
import type { ConversationGroup, ConversationRecord } from "@/lib/conversations/types";

const state = vi.hoisted(() => ({
  groups: [] as ConversationGroup[],
  rename: vi.fn(),
  remove: vi.fn(),
  newChat: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat/alpha",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/lib/hooks/use-conversations", () => ({
  useConversations: () => ({
    groups: state.groups,
    isLoading: false,
    startNewConversation: state.newChat,
    renameConversation: state.rename,
    removeConversation: state.remove,
  }),
}));
vi.mock("@/lib/hooks/use-knowledge-status", () => ({
  useKnowledgeStatus: () => ({ needsConnect: false, needsPrepare: false }),
}));

function chat(id: string, title: string): ConversationRecord {
  return {
    id,
    title,
    createdAt: "2026-09-27T09:00:00.000Z",
    updatedAt: "2026-09-27T09:00:00.000Z",
  };
}

beforeEach(() => {
  state.groups = [{ label: "Today", conversations: [chat("alpha", "Budget notes")] }];
  vi.clearAllMocks();
});
afterEach(cleanup);

describe("conversation sidebar", () => {
  it("exposes the restrained product and navigation hierarchy", () => {
    render(<ConversationSidebar />);

    expect(screen.getByText("DriveMind AI")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new chat/i })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /search chats/i })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: /recent conversations/i })).toHaveTextContent("Today");
    expect(screen.getByRole("link", { name: /Files/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Knowledge" })).toHaveAttribute("href", "/index");
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByText("Your knowledge OS")).not.toBeInTheDocument();
    expect(screen.queryByText(/Projects|Pin|model selector/i)).not.toBeInTheDocument();
  });

  it("collapses and expands the desktop navigation without changing conversations", () => {
    const originalGroups = state.groups;
    render(<ConversationSidebar />);

    expect(screen.getByRole("link", { name: /Budget notes/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /collapse sidebar/i }));
    expect(state.groups).toBe(originalGroups);
    expect(state.rename).not.toHaveBeenCalled();
    expect(state.remove).not.toHaveBeenCalled();
    expect(state.newChat).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /Files/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Knowledge/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Settings/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /expand sidebar/i }));
    expect(screen.getByRole("link", { name: /Budget notes/i })).toBeInTheDocument();
  });

  it("filters titles, then restores date-grouped results when search is cleared", () => {
    state.groups = [
      { label: "Today", conversations: [chat("alpha", "Budget notes")] },
      { label: "Yesterday", conversations: [chat("beta", "Travel plan")] },
    ];
    render(<ConversationSidebar />);

    fireEvent.change(screen.getByRole("textbox", { name: /search chats/i }), {
      target: { value: "travel" },
    });
    expect(screen.getByRole("link", { name: /Travel plan/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Budget notes/i })).not.toBeInTheDocument();
    expect(screen.getByText("Yesterday")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /clear search/i }));
    expect(screen.getByRole("link", { name: /Budget notes/i })).toBeInTheDocument();
    expect(screen.getByText("Today")).toBeInTheDocument();
  });

  it("does not offer search when there is no history", () => {
    state.groups = [];
    render(<ConversationSidebar />);
    expect(screen.queryByRole("textbox", { name: /search chats/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new chat/i })).toBeInTheDocument();
  });

  it("does not expose desktop collapse inside the mobile drawer variant", () => {
    render(<ConversationSidebar collapsible={false} />);
    expect(screen.queryByRole("button", { name: /collapse sidebar|expand sidebar/i }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Budget notes/i })).toBeInTheDocument();
  });
});
