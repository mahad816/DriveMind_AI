import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PrepareKnowledgeView } from "./prepare-knowledge-view";
import { prepareKnowledge } from "@/lib/knowledge/prepare";
vi.mock("@/lib/knowledge/prepare", () => ({ prepareKnowledge: vi.fn() }));
afterEach(cleanup);
it("offers metadata browsing without any bulk preparation entry point", () => {
  render(<PrepareKnowledgeView />);
  expect(screen.getByRole("link", { name: "Browse files" })).toHaveAttribute("href", "/files");
  expect(screen.getByRole("link", { name: "Open chat" })).toHaveAttribute("href", "/chat");
  expect(screen.queryByRole("button")).toBeNull(); expect(prepareKnowledge).not.toHaveBeenCalled();
});
