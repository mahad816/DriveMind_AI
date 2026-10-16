import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AnswerMarkdown } from "./answer-markdown";

const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
afterEach(() => { cleanup(); mode.demo = false; });
const origin = "00000000-0000-0000-0000-000000000333";
const citation = { drive_file_id: "00000000-0000-0000-0000-000000000111", chunk_id: "00000000-0000-0000-0000-000000000222", filename: "Evidence.txt", snippet: "Verified passage", score: 0.9 };

it.each([false, true])("retains prose, emphasis and structured Markdown in either mode (demo=%s)", demo => {
  mode.demo = demo;
  const { container } = render(<AnswerMarkdown content={'Opening **evidence** and *context* with `inline_code`.\n\n## Findings\n\n- First item\n  - Nested item\n\n| Name | Result |\n| --- | --- |\n| Trial | Ready |\n\n```ts\nconst prepared = true;\n```\n\n> Quoted explanation.\n\nClosing paragraph.'} />);
  expect(container.querySelector(".answer-markdown > p")?.textContent).toBe("Opening evidence and context with inline_code.");
  expect(container.querySelector("strong")).toHaveTextContent("evidence");
  expect(container.querySelector("em")).toHaveTextContent("context");
  expect(screen.getByRole("heading", { level: 2, name: "Findings" })).toBeInTheDocument();
  expect(container.querySelectorAll("ul")).toHaveLength(2);
  expect(container.querySelector("ul ul li")).toHaveTextContent("Nested item");
  expect(within(screen.getByRole("table")).getByRole("cell", { name: "Ready" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Answer table" })).toHaveAttribute("tabindex", "0");
  expect(container.querySelector("pre code")?.textContent).toBe("const prepared = true;\n");
  expect(container.querySelector("pre pre")).toBeNull();
  expect(container.querySelector("blockquote p")?.textContent).toBe("Quoted explanation.");
  expect(container.querySelector(".normal-workspace")).toBeNull(); // No theme boundary is injected into shared demo markup.
});

it.each([false, true])("preserves exact short text and partial-answer updates (demo=%s)", demo => {
  mode.demo = demo;
  const view = render(<AnswerMarkdown content="A brief answer." />);
  expect(view.container.textContent).toBe("A brief answer.");
  view.rerender(<AnswerMarkdown content="A brief answer. A second sentence with a longer explanation." />);
  expect(view.container.textContent).toBe("A brief answer. A second sentence with a longer explanation.");
  expect(view.container.querySelectorAll("p")).toHaveLength(1);
});

it("retains the exact citation action and constrained conversation destination in prose", async () => {
  const selected = vi.fn(), user = userEvent.setup();
  const { container } = render(<AnswerMarkdown content="The evidence supports this claim [1]." citations={[citation]} conversationId={origin} onSourceSelect={selected} />);
  expect(container.querySelector("p")?.textContent).toBe("The evidence supports this claim [1].");
  await user.click(screen.getByRole("button", { name: "View citation 1" }));
  expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("href", `/sources/${citation.chunk_id}?conversation=${origin}`);
  await user.click(screen.getByRole("button", { name: "View full evidence" }));
  expect(selected).toHaveBeenCalledExactlyOnceWith(citation, [citation]);
});
