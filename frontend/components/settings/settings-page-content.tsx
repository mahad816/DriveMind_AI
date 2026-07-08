"use client";

import { Suspense } from "react";

import { SettingsAboutSection } from "@/components/settings/settings-about-section";
import { SettingsAdvancedSection } from "@/components/settings/settings-advanced-section";
import { SettingsAppearanceSection } from "@/components/settings/settings-appearance-section";
import { SettingsDriveSection } from "@/components/settings/settings-drive-section";
import { PageShell } from "@/components/layout/page-shell";
import { useOAuthSettingsCallback } from "@/lib/hooks/use-oauth-settings-callback";
import { settingsCopy } from "@/lib/user-language";

function SettingsContent() {
  useOAuthSettingsCallback();

  return (
    <div className="space-y-6">
      <SettingsDriveSection />
      <SettingsAppearanceSection />
      <SettingsAboutSection />
      <SettingsAdvancedSection />
    </div>
  );
}

export function SettingsPageContent() {
  return (
    <PageShell
      size="md"
      className="max-w-md"
      title="Settings"
      description={settingsCopy.pageDescription}
    >
      <Suspense fallback={null}>
        <SettingsContent />
      </Suspense>
    </PageShell>
  );
}
