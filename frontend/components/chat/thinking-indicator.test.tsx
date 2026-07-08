import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ThinkingIndicator } from "@/components/chat/thinking-indicator";

describe("ThinkingIndicator", () => {
  it("exposes accessible status text", () => {
    render(<ThinkingIndicator />);

    expect(screen.getByRole("status", { name: "Thinking" })).toBeInTheDocument();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
  });
});
