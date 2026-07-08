import { SettingsSection } from "@/components/settings/settings-section";
import { ThemeToggle } from "@/components/settings/theme-toggle";
import { settingsCopy } from "@/lib/user-language";

export function SettingsAppearanceSection() {
  return (
    <SettingsSection title={settingsCopy.appearance}>
      <ThemeToggle />
    </SettingsSection>
  );
}
