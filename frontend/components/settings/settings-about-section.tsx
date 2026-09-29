import { settingsCopy } from "@/lib/user-language";

const APP_VERSION = "0.1.0";

export function SettingsAboutSection() {
  return (
    <footer className="space-y-1 text-sm text-muted-foreground" aria-label={settingsCopy.about}>
      <p className="font-medium text-foreground">DriveMind AI · v{APP_VERSION}</p>
      <p>{settingsCopy.aboutDescription}</p>
    </footer>
  );
}
