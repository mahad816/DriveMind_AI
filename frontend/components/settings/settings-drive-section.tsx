"use client";

import { useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { UserRound } from "lucide-react";

import { SettingsSection } from "@/components/settings/settings-section";
import { buttonVariants } from "@/components/ui/button";
import { ConnectionStatusBadge } from "@/components/layout/connection-status-badge";
import { getGoogleAuthUrl } from "@/lib/api/auth";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { handleDisconnectDrive } from "@/lib/hooks/use-oauth-settings-callback";
import { getConnectedEmail } from "@/lib/settings/storage";
import { connectionStatusLabel, settingsCopy } from "@/lib/user-language";

export function SettingsDriveSection() {
  const searchParams = useSearchParams();
  const emailParam = searchParams.get("email");
  const { data, isLoading, error } = useConnectionStatus({ pollIntervalMs: 30_000 });

  const isConnected = data?.connected ?? false;
  const email = emailParam ?? getConnectedEmail();
  const initial = email?.trim().charAt(0).toUpperCase() ?? "?";

  const connectUrl = getGoogleAuthUrl();

  const statusLabel = useMemo(() => {
    if (isLoading && !data) return connectionStatusLabel.checking;
    if (error) return connectionStatusLabel.error;
    return isConnected ? connectionStatusLabel.connected : connectionStatusLabel.notConnected;
  }, [data, error, isConnected, isLoading]);

  return (
    <SettingsSection title={settingsCopy.googleDrive}>
      <div className="space-y-4">
        <div className="flex items-start gap-3">
          <div
            className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary"
            aria-hidden="true"
          >
            {isConnected && email ? initial : <UserRound className="size-4" />}
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-medium text-foreground">{statusLabel}</p>
              <ConnectionStatusBadge />
            </div>
            {isConnected && email ? (
              <p className="truncate text-sm text-muted-foreground">
                {settingsCopy.connectedAs} {email}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">{settingsCopy.notConnected}</p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {isConnected ? (
            <>
              <button
                type="button"
                className={buttonVariants({ variant: "outline" })}
                onClick={handleDisconnectDrive}
                title={settingsCopy.disconnectHelp}
              >
                {settingsCopy.disconnect}
              </button>
              <a href={connectUrl} className={buttonVariants({ variant: "secondary" })}>
                {settingsCopy.reconnect}
              </a>
            </>
          ) : (
            <a href={connectUrl} className={buttonVariants()}>
              {settingsCopy.connect}
            </a>
          )}
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>
    </SettingsSection>
  );
}
