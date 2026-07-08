import { SettingsSection } from "@/components/settings/settings-section";
import { settingsCopy } from "@/lib/user-language";

const APP_VERSION = "0.1.0";

export function SettingsAboutSection() {
  return (
    <SettingsSection title={settingsCopy.about}>
      <div className="space-y-1 text-sm">
        <p className="font-medium text-foreground">DriveMind AI · v{APP_VERSION}</p>
        <p className="text-muted-foreground">{settingsCopy.aboutDescription}</p>
      </div>
    </SettingsSection>
  );
}
