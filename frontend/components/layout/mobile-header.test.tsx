import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MobileHeader } from "@/components/layout/mobile-header";

vi.mock("@/components/layout/conversation-sidebar", () => ({
  ConversationSidebar: ({ onNavigate }: { onNavigate?: () => void }) => (
    <nav aria-label="Mobile navigation">
      <button type="button" onClick={onNavigate}>Open Travel plan</button>
      <a href="/files" onClick={onNavigate}>Files</a>
    </nav>
  ),
}));

afterEach(cleanup);

describe("mobile shell navigation", () => {
  it("opens the drawer from a compact branded header and closes it after navigation", async () => {
    const user = userEvent.setup();
    render(<MobileHeader />);

    expect(screen.getByText("DriveMind AI")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open navigation menu" }));
    expect(screen.getByRole("navigation", { name: "Mobile navigation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Files" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Travel plan" }));
    expect(screen.queryByRole("navigation", { name: "Mobile navigation" })).not.toBeInTheDocument();
  });
});
