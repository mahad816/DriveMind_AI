"use client";

import { useSearchParams } from "next/navigation";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button, buttonVariants } from "@/components/ui/button";
import { getGoogleAuthUrl } from "@/lib/api/auth";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { handleDisconnectDrive } from "@/lib/hooks/use-oauth-settings-callback";
import { getConnectedEmail } from "@/lib/settings/storage";
import { connectionStatusLabel, settingsCopy } from "@/lib/user-language";

export function SettingsDriveSection() {
  const searchParams = useSearchParams();
  const emailParam = searchParams.get("email");
  const { data, isLoading, error, refetch } = useConnectionStatus({ pollIntervalMs: 30_000 });

  const isConnected = data?.connected ?? false;
  const statusUnavailable = Boolean(error) || (!isLoading && !data);
  const email = emailParam ?? getConnectedEmail();
  const connectUrl = getGoogleAuthUrl();

  const statusLabel = statusUnavailable
    ? connectionStatusLabel.error
    : isLoading && !data
      ? connectionStatusLabel.checking
      : isConnected
        ? connectionStatusLabel.connected
        : connectionStatusLabel.notConnected;

  return (
    <SettingsSection title={settingsCopy.googleDrive}>
      <div className="space-y-4">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
          <div className="min-w-0 space-y-1">
            <p className="text-sm font-medium text-foreground">{statusLabel}</p>
            {isConnected && email ? (
              <p className="break-all text-sm text-muted-foreground">
                {settingsCopy.connectedAs} {email}
              </p>
            ) : !statusUnavailable && data?.connected === false ? (
              <p className="text-sm text-muted-foreground">{settingsCopy.notConnected}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {statusUnavailable ? (
              <Button type="button" variant="outline" onClick={() => void refetch()}>Retry connection check</Button>
            ) : isLoading && !data ? null : isConnected ? (
              <>
                <button
                  type="button"
                  className={buttonVariants({ variant: "outline" })}
                  onClick={handleDisconnectDrive}
                  title={settingsCopy.disconnectHelp}
                >
                  {settingsCopy.manageGoogleAccess}
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
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>
    </SettingsSection>
  );
}
