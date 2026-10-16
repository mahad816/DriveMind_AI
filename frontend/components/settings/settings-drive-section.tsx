"use client";
import { useState } from "react";
import { SettingsSection } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { settingsCopy } from "@/lib/user-language";
export function SettingsDriveSection() {
  const { connectDrive, logout, error: sessionError } = useApplicationSession();
  const { data, isLoading, error, refetch } = useConnectionStatus({ pollIntervalMs: 30_000 });
  const [connecting, setConnecting] = useState(false);
  const connect = async () => { if (connecting) return; setConnecting(true); try { await connectDrive(); } finally { setConnecting(false); } };
  return <>
    <SettingsSection title="Account">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <p className="text-sm font-medium">Signed in to DriveMind with Google</p>
          <p className="max-w-md text-sm leading-6 text-muted-foreground">Signing out ends this session. Prepared documents and Google Drive permissions are kept.</p>
        </div>
        <Button variant="outline" className="shrink-0 self-start" onClick={() => void logout()}>Sign out of DriveMind</Button>
      </div>
    </SettingsSection>
    <SettingsSection title="Google Drive">
      <div className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p role="status" className="text-sm font-medium">{error ? "Drive status unavailable" : isLoading && !data ? "Checking Google Drive…" : data?.connected ? "Google Drive connected" : "Google Drive not connected"}</p>
          <Button className="shrink-0 self-start" disabled={connecting || isLoading || !!error} onClick={() => void connect()}>{connecting ? "Opening Google…" : data?.connected ? "Reconnect Google Drive" : "Connect Google Drive"}</Button>
        </div>
        <p className="max-w-lg text-sm leading-6 text-muted-foreground">Read-only access. Discovering files does not prepare their content for chat.</p>
        {sessionError || error ? <p role="alert" className="text-sm">{sessionError ? "We couldn’t connect Google Drive. Check your session and try again." : "We couldn’t check Drive access. Try checking again."}</p> : null}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button variant="ghost" onClick={() => void refetch()}>Refresh Drive status</Button>
          {data?.connected ? <a className="inline-flex min-h-11 items-center text-sm underline underline-offset-4" href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer">{settingsCopy.manageGoogleAccess}</a> : null}
        </div>
      </div>
    </SettingsSection>
  </>;
}
