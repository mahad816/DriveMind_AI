import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UserMessage } from "@/components/chat/user-message";

afterEach(cleanup);

describe("user message", () => {
  it("shows one readable plain-text contribution, distinct from an assistant answer", () => {
    const prompt = "Please find the meeting summary and the budget notes. **Keep this literal.**";
    render(<UserMessage content={prompt} />);

    expect(screen.getAllByText(prompt)).toHaveLength(1);
    expect(screen.queryByRole("strong")).not.toBeInTheDocument();
    const message = screen.getByRole("article", { name: /your message/i });
    expect(message).toHaveTextContent(prompt);
    expect(screen.queryByRole("article", { name: /assistant answer/i })).not.toBeInTheDocument();
  });
});
