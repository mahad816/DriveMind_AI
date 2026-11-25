"use client";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { useDriveStatus, useWorkspace, useResource } from "@/components/workspace/workspace-provider";
import { Banner } from "@/components/ui/controls";
import { Button } from "@/components/ui/button";

/** Persistent conditions only. Each says what happened, whether work is safe, and what to do. */
export function ConnectionBanners() {
  const session = useApplicationSession();
  const status = useDriveStatus();
  const { files } = useWorkspace();
  const inventory = useResource(files);
  const pathname = usePathname();
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  if (session.offline) {
    return <Banner tone="caution">You&apos;re offline. What&apos;s on screen stays readable. You can send questions and prepare documents again once you&apos;re back online.</Banner>;
  }
  if (session.degraded) {
    return (
      <Banner tone="caution" action={<Button size="sm" intent="quiet" onClick={() => void session.refresh()}>Try now</Button>}>
        DriveMind can&apos;t reach its server right now. You can keep reading; you can send questions and prepare documents again once it&apos;s reachable.
      </Banner>
    );
  }
  // No stored Drive connection while documents exist (status `connected` means a stored Google token): prepared
  // documents still answer, because chat reads DriveMind's own copy and never calls Drive (blueprint §6.5).
  const hasFiles = (inventory.data?.length ?? 0) > 0;
  if (status.data && !status.data.connected && hasFiles && !pathname.startsWith("/welcome") && !pathname.startsWith("/settings")) {
    return (
      <Banner tone="caution" action={
        <Button size="sm" intent="secondary" loading={connecting} disabled={!session.canMutate} onClick={async () => {
          setConnecting(true); setConnectError(null);
          try { await session.connectDrive(); } catch (error) { setConnectError((error as Error).message); setConnecting(false); }
        }}>Reconnect Google Drive</Button>}>
        Google Drive isn&apos;t connected. Prepared documents can still be used in answers; connect again to prepare new ones or check for changes.
        {connectError ? <span className="mt-1 block text-fault">{connectError}</span> : null}
      </Banner>
    );
  }
  return null;
}
