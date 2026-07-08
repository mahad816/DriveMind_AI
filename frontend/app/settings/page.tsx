import { Suspense } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { PageHeader } from "@/components/layout/page-header";
import { DriveConnectionCard } from "@/components/settings/drive-connection-card";
import { SettingsEnvCard } from "@/components/settings/settings-env-card";
import { ThemeToggle } from "@/components/settings/theme-toggle";

export default function SettingsPage() {
  return (
    <PageContainer size="lg">
      <PageHeader
        title="Settings"
        description="Connect Google Drive and configure your workspace."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          <Suspense fallback={null}>
            <DriveConnectionCard />
          </Suspense>
          <SettingsEnvCard />
        </div>

        <div className="space-y-6">
          <ThemeToggle />
        </div>
      </div>
    </PageContainer>
  );
}
