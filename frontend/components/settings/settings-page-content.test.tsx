import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsPageContent } from "@/components/settings/settings-page-content";

vi.mock("@/lib/hooks/use-oauth-settings-callback", () => ({ useOAuthSettingsCallback: vi.fn() }));
vi.mock("@/components/settings/settings-drive-section", () => ({ SettingsDriveSection: () => <section>Google Drive</section> }));
vi.mock("@/components/settings/settings-appearance-section", () => ({ SettingsAppearanceSection: () => <section>Appearance</section> }));
vi.mock("@/components/settings/settings-advanced-section", () => ({ SettingsAdvancedSection: () => <section>Advanced</section> }));

afterEach(cleanup);

describe("Settings organization", () => {
  it("links to the existing Knowledge destination without duplicating its controls", () => {
    render(<SettingsPageContent />);
    expect(screen.getByRole("link", { name: "Open Knowledge" })).toHaveAttribute("href", "/index");
    expect(screen.queryByRole("button", { name: "Prepare knowledge" })).not.toBeInTheDocument();
  });
});
