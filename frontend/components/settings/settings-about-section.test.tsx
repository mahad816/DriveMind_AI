import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SettingsAboutSection } from "@/components/settings/settings-about-section";

describe("SettingsAboutSection", () => {
  it("shows product name and version", () => {
    render(<SettingsAboutSection />);

    expect(screen.getByText(/DriveMind AI · v0\.1\.0/)).toBeInTheDocument();
    expect(screen.getByText(/Your personal AI knowledge assistant/i)).toBeInTheDocument();
  });
});
