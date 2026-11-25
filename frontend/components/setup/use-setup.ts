"use client";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { useDriveStatus, useFiles } from "@/components/workspace/workspace-provider";

export type SetupState = { known: boolean; connected: boolean | null; files: number | null; ready: number | null; complete: boolean };

/** Derived from the server only (never from browser flags), so it cannot drift from reality (fixes audit L-02). */
export function useSetupState(): SetupState {
  const status = useDriveStatus();
  const files = useFiles();
  const connected = status.data ? status.data.connected : null;
  const ready = files.data ? files.data.filter(f => f.status === "indexed").length : null;
  const known = (status.data !== null || !!status.error) && (files.data !== null || !!files.error);
  return { known, connected, files: files.data?.length ?? null, ready, complete: connected === true && (ready ?? 0) > 0 };
}

/** Sends the person to setup or to a new chat once state is known. A status failure never blocks chat. */
export function useSetupDestination(enabled: boolean, fallback = "/chat") {
  const router = useRouter();
  const setup = useSetupState();
  const done = useRef(false);
  useEffect(() => {
    if (!enabled || done.current || !setup.known) return;
    done.current = true;
    const needsSetup = setup.connected === false || (setup.connected === true && setup.ready === 0);
    router.replace(needsSetup ? "/welcome" : fallback);
  }, [enabled, setup, router, fallback]);
}
