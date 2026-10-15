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
      <div className="space-y-3">
        <p className="text-sm">Signed in to DriveMind with Google</p>
        <p className="text-sm leading-6 text-muted-foreground">Signing out ends this session. It does not delete your prepared documents or revoke Google Drive access.</p>
        <Button variant="outline" onClick={() => void logout()}>Sign out of DriveMind</Button>
      </div>
    </SettingsSection>
    <SettingsSection title="Google Drive">
      <div className="space-y-3">
        <p role="status" className="text-sm">{error ? "Drive status unavailable" : isLoading && !data ? "Checking Google Drive…" : data?.connected ? "Google Drive connected" : "Google Drive not connected"}</p>
        <p className="text-sm leading-6 text-muted-foreground">Read-only access lets DriveMind discover supported documents. Discovery does not prepare their content for chat.</p>
        {sessionError || error ? <p role="alert" className="text-sm">{sessionError ? "We couldn’t connect Google Drive. Check your session and try again." : "We couldn’t check Drive access. Try checking again."}</p> : null}
        <div className="flex flex-wrap gap-2">
          <Button disabled={connecting || isLoading || !!error} onClick={() => void connect()}>{connecting ? "Opening Google…" : data?.connected ? "Reconnect Google Drive" : "Connect Google Drive"}</Button>
          <Button variant="outline" onClick={() => void refetch()}>Refresh Drive status</Button>
        </div>
        {data?.connected ? <a className="inline-flex min-h-11 items-center text-sm underline underline-offset-4" href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer">{settingsCopy.manageGoogleAccess}</a> : null}
      </div>
    </SettingsSection>
  </>;
}
