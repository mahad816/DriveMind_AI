import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConversationItem } from "@/components/layout/conversation-item";

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

describe("ConversationItem", () => {
  it("renders title, relative time, and chat link", () => {
    render(
      <ConversationItem
        conversation={{
          id: "abc-123",
          title: "Resume questions",
          createdAt: "2026-07-08T10:00:00.000Z",
          updatedAt: "2026-07-08T11:00:00.000Z",
        }}
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
});
