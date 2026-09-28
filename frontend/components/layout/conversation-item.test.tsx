import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationItem } from "@/components/layout/conversation-item";

const navigation = vi.hoisted(() => ({
  pathname: "/chat",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: vi.fn(), replace: navigation.replace }),
}));
vi.mock("@/lib/conversations/storage", () => ({ listConversations: () => [] }));

const conversation = {
  id: "abc-123",
  title: "Resume questions",
  createdAt: "2026-07-08T10:00:00.000Z",
  updatedAt: "2026-07-08T11:00:00.000Z",
};

beforeEach(() => {
  navigation.pathname = "/chat";
  vi.clearAllMocks();
});
afterEach(cleanup);

describe("ConversationItem", () => {
  it("renders title, relative time, and chat link", () => {
    render(
      <ConversationItem
        conversation={conversation}
        onRename={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByRole("link", { name: /Resume questions/i })).toHaveAttribute(
      "href",
      "/chat/abc-123",
    );
    expect(screen.getByText(/ago|Just now|Jul/i)).toBeInTheDocument();
  });

  it("marks only the selected conversation active and keeps it active through rename", () => {
    navigation.pathname = "/chat/abc-123";
    const onRename = vi.fn();
    const onNavigate = vi.fn();
    const { rerender } = render(
      <ConversationItem conversation={conversation} onNavigate={onNavigate} onRename={onRename} onDelete={vi.fn()} />,
    );
    expect(screen.getByRole("link", { name: /Resume questions/i })).toHaveAttribute("aria-current", "page");

    fireEvent.click(screen.getByRole("button", { name: "Conversation options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /rename/i }));
    expect(screen.getByRole("textbox", { name: /rename conversation/i })).toHaveFocus();
    fireEvent.change(screen.getByRole("textbox", { name: /rename conversation/i }), {
      target: { value: "Trip questions" },
    });
    fireEvent.keyDown(screen.getByRole("textbox", { name: /rename conversation/i }), { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith("abc-123", "Trip questions");
    expect(onNavigate).not.toHaveBeenCalled();
    rerender(
      <ConversationItem conversation={{ ...conversation, title: "Trip questions" }} onRename={onRename} onDelete={vi.fn()} />,
    );
    expect(screen.getByRole("link", { name: /Trip questions/i })).toHaveAttribute("aria-current", "page");

    navigation.pathname = "/chat/another";
    rerender(
      <ConversationItem conversation={{ ...conversation, title: "Trip questions" }} onRename={onRename} onDelete={vi.fn()} />,
    );
    expect(screen.getByRole("link", { name: /Trip questions/i })).not.toHaveAttribute("aria-current");
  });

  it("opens an accessible menu by keyboard and closes it with Escape without navigating", async () => {
    const onNavigate = vi.fn();
    render(
      <ConversationItem conversation={conversation} onNavigate={onNavigate} onRename={vi.fn()} onDelete={vi.fn()} />,
    );

    const trigger = screen.getByRole("button", { name: "Conversation options" });
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("menuitem", { name: /rename/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /delete/i })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("deleting the active chat retains the current empty-canvas fallback", () => {
    navigation.pathname = "/chat/abc-123";
    const onDelete = vi.fn();
    const onNavigate = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <ConversationItem conversation={conversation} onNavigate={onNavigate} onRename={vi.fn()} onDelete={onDelete} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Conversation options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /delete/i }));
    expect(onDelete).toHaveBeenCalledWith("abc-123");
    expect(navigation.replace).toHaveBeenCalledWith("/chat");
    expect(onNavigate).not.toHaveBeenCalled();
    vi.mocked(window.confirm).mockRestore();
  });
});
