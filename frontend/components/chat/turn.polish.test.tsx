import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CompletedTurn } from "./turn";
import { ShortcutsDialog } from "@/components/shell/shortcuts-dialog";
const citation = { chunk_id: "chunk", drive_file_id: "file", filename: "Synthetic.txt", snippet: "Synthetic evidence", chunk_index: 0, score: 1 };
const props = { id: "turn", question: "What happened?", answer: "A result [1].", citations: [citation], conversationId: null, onOpenSources: vi.fn(), wide: true };
beforeEach(() => { Element.prototype.scrollIntoView = vi.fn(); });
afterEach(cleanup);
it("folds old sources and opens them when the reader follows an inline citation", () => {
  render(<CompletedTurn {...props} current={false} />);
  const toggle = screen.getByRole("button", { name: /Sources ·/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
  fireEvent.click(document.querySelector("button[data-citation]")!);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("note", { name: "Source 1: Synthetic.txt" })).toBeInTheDocument();
  fireEvent.click(toggle);
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
});
it("keeps current sources open and offers Ask again only when permitted", () => {
  const ask = vi.fn();
  const { rerender } = render(<CompletedTurn {...props} onAskAgain={ask} />);
  expect(screen.getByRole("button", { name: /Sources ·/ })).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("button", { name: "Ask again" }));
  expect(ask).toHaveBeenCalledOnce();
  rerender(<CompletedTurn {...props} current={false} />);
  expect(screen.queryByRole("button", { name: "Ask again" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Sources ·/ })).toHaveAttribute("aria-expanded", "false");
});
it("lists keyboard shortcuts in an accessible dialog", async () => {
  render(<ShortcutsDialog open onOpenChange={vi.fn()} />);
  expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  expect(screen.getByText("Send the question")).toBeInTheDocument();
  expect(screen.getByText("New line in the question")).toBeInTheDocument();
});
