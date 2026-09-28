import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmptyStateHero } from "@/components/chat/empty-state-hero";

afterEach(cleanup);

describe("new-chat state", () => {
  it("introduces DriveMind once with a concise prompt and a small set of examples", () => {
    render(
      <EmptyStateHero
        needsConnect={false}
        needsPrepare={false}
        isSending={false}
        onSuggestionClick={vi.fn()}
      />,
    );

    expect(screen.getAllByText("DriveMind AI")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "What can I help you find?" })).toBeInTheDocument();
    const examples = screen.getAllByRole("button");
    expect(examples.length).toBeGreaterThanOrEqual(2);
    expect(examples.length).toBeLessThanOrEqual(3);
    for (const example of examples) expect(example).toHaveAccessibleName();
  });

  it("retains truthful connect and prepare guidance when knowledge is not ready", () => {
    const { rerender } = render(
      <EmptyStateHero needsConnect needsPrepare={false} isSending={false} onSuggestionClick={vi.fn()} />,
    );
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");

    rerender(
      <EmptyStateHero needsConnect={false} needsPrepare isSending={false} onSuggestionClick={vi.fn()} />,
    );
    expect(screen.getByRole("link")).toHaveAttribute("href", "/index");
  });
});
