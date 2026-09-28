import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssistantMessage } from "@/components/chat/assistant-message";
import type { ChatResponse } from "@/lib/api/types";

vi.mock("@/components/ui/toast-provider", () => ({
  useToast: () => ({ pushToast: vi.fn() }),
}));

afterEach(cleanup);

function answer(markdown: string): ChatResponse {
  return {
    query_id: "query-1",
    user_id: "user-1",
    answer: markdown,
    message: markdown,
    citations: [],
    retrieval_count: 0,
  };
}

describe("assistant Markdown", () => {
  it("keeps inline code inside prose instead of wrapping it in a block", () => {
    render(
      <AssistantMessage
        response={answer("Use `drive_file_id` here.")}
        onSourceSelect={vi.fn()}
      />,
    );

    const inlineCode = screen.getByText("drive_file_id", { selector: "code" });
    expect(inlineCode.closest("pre")).toBeNull();
  });

  it("renders a fenced code block without nested pre elements", () => {
    const { container } = render(
      <AssistantMessage
        response={answer("```text\nfirst line\nsecond line\n```")}
        onSourceSelect={vi.fn()}
      />,
    );
    const blocks = container.querySelectorAll("pre");
    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.querySelector("code")).toHaveTextContent("first line");
    expect(blocks[0]?.querySelector("pre")).toBeNull();
  });

  it("does not execute or render raw HTML supplied in an answer", () => {
    const { container } = render(
      <AssistantMessage response={answer('<script>alert("unsafe")</script>')} onSourceSelect={vi.fn()} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container).toHaveTextContent('<script>alert("unsafe")</script>');
  });

  it("renders a GFM table in a separate accessible overflow region from prose", () => {
    render(
      <AssistantMessage
        response={answer("A short comparison.\n\n| Item | Cost |\n| --- | --- |\n| Train | Low |\n\nA closing note.")}
        onSourceSelect={vi.fn()}
      />,
    );

    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Item" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "Low" })).toBeInTheDocument();
    const tableRegion = table.closest('[role="region"]');
    expect(tableRegion).not.toBeNull();
    expect(tableRegion).toHaveAccessibleName();
    expect(tableRegion).toHaveAttribute("tabindex", "0");
    expect(tableRegion).not.toHaveTextContent("A short comparison.");
    expect(tableRegion).not.toHaveTextContent("A closing note.");
  });

  it("preserves common Markdown heading levels", () => {
    render(
      <AssistantMessage
        response={answer("# Overview\n\n## Details\n\n### Notes")}
        onSourceSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Details" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Notes" })).toBeInTheDocument();
  });

  it("preserves nested lists, quotes, rules, and accessible links", () => {
    render(
      <AssistantMessage
        response={answer(
          "- Parent\n  - Child\n\n1. First\n2. Second\n\n> A quoted note\n\n---\n\n[Open reference](https://example.com)",
        )}
        onSourceSelect={vi.fn()}
      />,
    );

    const lists = screen.getAllByRole("list");
    expect(lists.some((list) => list.tagName === "UL")).toBe(true);
    expect(lists.some((list) => list.tagName === "OL")).toBe(true);
    const parent = screen.getByText("Parent").closest("li");
    expect(parent?.querySelector("ul li")).toHaveTextContent("Child");
    expect(screen.getByText("A quoted note").closest("blockquote")).not.toBeNull();
    expect(document.querySelector("hr")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Open reference" })).toHaveAttribute("href", "https://example.com");
  });

  it("preserves valid Markdown link attributes", () => {
    render(
      <AssistantMessage
        response={answer('[Drive](https://example.com "Google Drive")')}
        onSourceSelect={vi.fn()}
      />,
    );

    const link = screen.getByRole("link", { name: "Drive" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("title", "Google Drive");
  });
});
