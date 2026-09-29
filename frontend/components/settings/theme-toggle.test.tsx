import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "@/components/settings/theme-toggle";
import { useTheme } from "next-themes";

vi.mock("next-themes", () => ({ useTheme: vi.fn() }));

afterEach(cleanup);

describe("Appearance setting", () => {
  it("shows supported modes and applies the selected mode", () => {
    const setTheme = vi.fn();
    vi.mocked(useTheme).mockReturnValue({ theme: "system", themes: ["system", "light", "dark"], setTheme });
    render(<ThemeToggle />);

    expect(screen.getByRole("tab", { name: "System" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Dark" }));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });
});
