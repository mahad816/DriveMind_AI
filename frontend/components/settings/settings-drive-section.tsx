"use client";
import { SettingsSection } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { settingsCopy } from "@/lib/user-language";
export function SettingsDriveSection() {
  const { userId, connectDrive, logout, error: sessionError } = useApplicationSession();
  const { data, isLoading, error, refetch } = useConnectionStatus({ pollIntervalMs: 30_000 });
  return <SettingsSection title="Application account and Google Drive">
    <p>Signed in to DriveMind</p>
    <p className="break-all text-sm">Account: {userId}</p>
    <p>{error ? "Drive status unavailable" : isLoading && !data ? "Checking Google Drive…" : data?.connected ? "Google Drive connected" : "Google Drive not connected"}</p>
    {sessionError || error ? <p role="alert">{sessionError ?? error}</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button onClick={() => void connectDrive()}>{data?.connected ? "Reconnect Google Drive" : "Connect Google Drive"}</Button>
      <Button variant="outline" onClick={() => void logout()}>Sign out of DriveMind</Button>
      <Button variant="outline" onClick={() => void refetch()}>Refresh Drive status</Button>
      {data?.connected ? <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer">{settingsCopy.manageGoogleAccess}</a> : null}
    </div>
  </SettingsSection>;
}
