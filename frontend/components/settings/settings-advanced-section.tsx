import { ChatApiStatusCard } from "@/components/chat/chat-api-status-card";
import { SettingsEnvCard } from "@/components/settings/settings-env-card";
import { settingsCopy } from "@/lib/user-language";

export function SettingsAdvancedSection() {
  return (
    <details className="border-b border-border pb-8">
      <summary className="cursor-pointer text-sm font-semibold text-foreground focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {settingsCopy.advanced}
      </summary>
      <div className="mt-4 space-y-4 border-t border-border pt-4">
        <SettingsEnvCard embedded />
        <ChatApiStatusCard />
      </div>
    </details>
  );
}
