import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FolderOpen } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";

describe("EmptyState", () => {
  it("renders title, description, and action link", () => {
    render(
      <EmptyState
        title="No files yet"
        description="Prepare your knowledge first."
        actionLabel="Prepare knowledge"
        actionHref="/index"
        icon={FolderOpen}
      />,
    );

    expect(screen.getByRole("heading", { name: "No files yet" })).toBeInTheDocument();
    expect(screen.getByText("Prepare your knowledge first.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Prepare knowledge" })).toHaveAttribute(
      "href",
      "/index",
    );
  });
});
