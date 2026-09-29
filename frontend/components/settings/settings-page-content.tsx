"use client";

import { Suspense } from "react";
import Link from "next/link";

import { SettingsAboutSection } from "@/components/settings/settings-about-section";
import { SettingsAdvancedSection } from "@/components/settings/settings-advanced-section";
import { SettingsAppearanceSection } from "@/components/settings/settings-appearance-section";
import { SettingsDriveSection } from "@/components/settings/settings-drive-section";
import { PageShell } from "@/components/layout/page-shell";
import { SettingsSection } from "@/components/settings/settings-section";
import { useOAuthSettingsCallback } from "@/lib/hooks/use-oauth-settings-callback";
import { settingsCopy } from "@/lib/user-language";

function SettingsContent() {
  useOAuthSettingsCallback();

  return (
    <div className="space-y-8">
      <SettingsAppearanceSection />
      <SettingsDriveSection />
      <SettingsSection title={settingsCopy.knowledge}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            Manage the Drive knowledge used for grounded answers.
          </p>
          <Link href="/index" className="shrink-0 text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            Open Knowledge
          </Link>
        </div>
      </SettingsSection>
      <SettingsAdvancedSection />
      <SettingsAboutSection />
    </div>
  );
}

export function SettingsPageContent() {
  return (
    <PageShell
      size="md"
      className="px-5 py-10 sm:px-8 md:py-14"
      title="Settings"
      description={settingsCopy.pageDescription}
    >
      <Suspense fallback={null}>
        <SettingsContent />
      </Suspense>
    </PageShell>
  );
}
