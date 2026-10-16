"use client";

import { DEMO_MODE } from "@/lib/demo";

import { Suspense } from "react";
import Link from "next/link";

import { SettingsAboutSection } from "@/components/settings/settings-about-section";
import { SettingsAppearanceSection } from "@/components/settings/settings-appearance-section";
import { SettingsDriveSection } from "@/components/settings/settings-drive-section";
import { PageShell } from "@/components/layout/page-shell";
import { SettingsSection } from "@/components/settings/settings-section";
import { useOAuthSettingsCallback } from "@/lib/hooks/use-oauth-settings-callback";
import { settingsCopy } from "@/lib/user-language";

function NormalOAuthCallback() {
  useOAuthSettingsCallback();
  return null;
}

function SettingsContent() {
  return (
    <div className={DEMO_MODE ? "space-y-8" : "space-y-6"}>
      {DEMO_MODE ? <SettingsAppearanceSection /> : null}
      {!DEMO_MODE ? <><NormalOAuthCallback /><SettingsDriveSection /></> : <p>Public demo · fictional HarborDesk sample corpus. No Google Drive connection required.</p>}
      {!DEMO_MODE ? <SettingsAppearanceSection /> : null}
      <SettingsSection title={settingsCopy.knowledge}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            {DEMO_MODE ? "Browse the controlled sample knowledge used for grounded answers." : "Manage documents prepared for chat."}
          </p>
          <Link href={DEMO_MODE ? "/index" : "/files"} className="shrink-0 text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {DEMO_MODE ? "Open Knowledge" : "Manage files"}
          </Link>
        </div>
      </SettingsSection>
      <SettingsAboutSection />
    </div>
  );
}

export function SettingsPageContent() {
  return (
    <PageShell
      size="md"
      className={DEMO_MODE ? "px-5 py-10 sm:px-8 md:py-14" : "gap-6 px-4 py-6 sm:px-6 md:py-8"}
      title="Settings"
      description={DEMO_MODE ? "Public demo preferences" : settingsCopy.pageDescription}
    >
      <Suspense fallback={null}>
        <SettingsContent />
      </Suspense>
    </PageShell>
  );
}
