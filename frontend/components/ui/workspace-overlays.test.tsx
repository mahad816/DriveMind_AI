import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { CitationPreview } from "@/components/chat/citation-preview";
import { ConversationItem } from "@/components/layout/conversation-item";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";
import { ToastProvider, useToast } from "./toast-provider";

const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
vi.mock("next/navigation", () => ({ usePathname: () => "/chat" }));
afterEach(() => { cleanup(); mode.demo = false; vi.restoreAllMocks(); });

const citation = {
  drive_file_id: "00000000-0000-0000-0000-000000000111",
  chunk_id: "00000000-0000-0000-0000-000000000222",
  filename: "Research decisions.txt", snippet: "A cited passage", score: 0.9,
};
const origin = "00000000-0000-0000-0000-000000000333";
const conversation = { id: origin, title: "Research decisions", createdAt: "2026-10-15T10:00:00Z", updatedAt: "2026-10-15T10:00:00Z" };

it.each([false, true])("citation portal keeps mode, identity, keyboard and dismissal behavior (demo=%s)", async demo => {
  mode.demo = demo;
  const user = userEvent.setup(), evidence = vi.fn();
  render(<CitationPreview citation={citation} conversationId={origin} number={1} onOpenEvidence={evidence} />);
  const trigger = screen.getByRole("button", { name: "View citation 1" });
  trigger.focus();await user.keyboard("{Enter}");
  expect(screen.getByRole("dialog").classList.contains("normal-workspace")).toBe(!demo);
  expect(screen.getByText("A cited passage")).toBeVisible();
  if (demo) expect(screen.queryByRole("link", { name: "Open source" })).toBeNull();
  else {
    const link = screen.getByRole("link", { name: "Open source" });
    expect(link).toHaveAttribute("href", `/sources/${citation.chunk_id}?conversation=${origin}`);
    expect(link.getAttribute("href")).not.toContain(citation.drive_file_id);
    expect(link).toHaveClass("overlay-action");
  }
  await user.click(screen.getByRole("button", { name: "View full evidence" }));
  expect(evidence).toHaveBeenCalledExactlyOnceWith(citation);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(trigger).toHaveFocus();
});

it("citation popup dismisses on an outside click without invoking an action", async () => {
  const user = userEvent.setup(), evidence = vi.fn();
  render(<><button>Outside</button><CitationPreview citation={citation} number={1} onOpenEvidence={evidence} /></>);
  await user.click(screen.getByRole("button", { name: "View citation 1" }));
  await user.click(screen.getByRole("button", { name: "Outside" }));
  expect(screen.queryByRole("dialog")).toBeNull();expect(evidence).not.toHaveBeenCalled();
});

it.each([false, true])("conversation menu scopes normal mode and retains exact rename/delete targets (demo=%s)", async demo => {
  mode.demo = demo;
  const user = userEvent.setup(), rename = vi.fn(), remove = vi.fn();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<ConversationItem conversation={conversation} onRename={rename} onDelete={remove} />);
  const trigger = screen.getByRole("button", { name: "Conversation options" });
  trigger.focus();await user.keyboard("{Enter}");
  expect(screen.getByRole("menu", { name: "Conversation options" }).classList.contains("normal-workspace")).toBe(!demo);
  await user.click(screen.getByRole("menuitem", { name: /delete/i }));
  expect(confirm).toHaveBeenCalledWith('Delete "Research decisions"? This cannot be undone.');expect(remove).not.toHaveBeenCalled();
  if (!screen.queryByRole("menu")) { trigger.focus(); await user.keyboard("{Enter}"); }
  await user.click(screen.getByRole("menuitem", { name: /rename/i }));
  const input = screen.getByRole("textbox", { name: "Rename conversation" });expect(input).toHaveFocus();
  fireEvent.change(input, { target: { value: "Updated decisions" } });await user.keyboard("{Enter}");
  expect(rename).toHaveBeenCalledExactlyOnceWith(origin, "Updated decisions");
});

it.each([false, true])("tooltip is scoped by mode and opens from keyboard focus (demo=%s)", async demo => {
  mode.demo = demo;const user = userEvent.setup();
  render(<TooltipProvider><Tooltip><TooltipTrigger>Details</TooltipTrigger><TooltipContent>Read document details</TooltipContent></Tooltip></TooltipProvider>);
  await user.tab();const tooltip = await screen.findByText("Read document details");
  expect(tooltip.classList.contains("normal-workspace")).toBe(!demo);expect(tooltip).toHaveTextContent("Read document details");
  await user.keyboard("{Escape}");await waitFor(() => expect(screen.queryByText("Read document details")).toBeNull());
});

function ToastExample() {
  const { pushToast } = useToast();
  return <button onClick={() => pushToast({ title: "Document copied", description: "Ready to paste", variant: "success", durationMs: 100 })}>Notify</button>;
}
it.each([false, true])("toast keeps live announcements, expiry and explicit mode scope (demo=%s)", async demo => {
  mode.demo = demo;const user = userEvent.setup();render(<ToastProvider><ToastExample /></ToastProvider>);
  await user.click(screen.getByRole("button", { name: "Notify" }));const toast = screen.getByRole("status");
  expect(toast.closest(".normal-workspace") !== null).toBe(!demo);
  expect(toast.parentElement).toHaveAttribute("aria-live", "polite");expect(toast.parentElement).toHaveAttribute("aria-relevant", "additions");
  expect(toast).toHaveTextContent("Ready to paste");await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
});
