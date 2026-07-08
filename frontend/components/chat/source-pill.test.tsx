import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SourcePill } from "@/components/chat/source-pill";

describe("SourcePill", () => {
  it("renders filename and handles click", async () => {
    const onClick = vi.fn();
    render(<SourcePill label="spec.pdf" onClick={onClick} />);

    const button = screen.getByRole("button", { name: /spec\.pdf/i });
    button.click();

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
