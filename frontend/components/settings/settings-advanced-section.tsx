import { ChatApiStatusCard } from "@/components/chat/chat-api-status-card";
import { SettingsEnvCard } from "@/components/settings/settings-env-card";
import { settingsCopy } from "@/lib/user-language";

export function SettingsAdvancedSection() {
  return (
    <details className="rounded-2xl border border-border bg-surface-elevated p-4">
      <summary className="cursor-pointer text-sm font-medium text-foreground">
        {settingsCopy.advanced}
      </summary>
      <div className="mt-4 space-y-4 border-t border-border pt-4">
        <SettingsEnvCard embedded />
        <ChatApiStatusCard />
      </div>
    </details>
  );
}
