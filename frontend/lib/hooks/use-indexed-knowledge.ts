"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { listDriveFiles } from "@/lib/api/files";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";

type Readiness = "checking" | "empty" | "ready" | "unavailable";

/** Read the same authorized inventory used by Files. No Drive dependency or polling. */
export function useIndexedKnowledge(owner: string | null, revision: number) {
  const [result, setResult] = useState<{ owner: string; revision: number; status: Readiness } | null>(null);
  const request = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    request.current?.abort();
    if (!owner || sessionOwner() !== owner || sessionRevision() !== revision) return;
    const abort = new AbortController();
    request.current = abort;
    const live = () => !abort.signal.aborted && sessionOwner() === owner && sessionRevision() === revision;
    setResult({ owner, revision, status: "checking" });
    try {
      const inventory = await listDriveFiles(abort.signal);
      if (!Array.isArray(inventory.files) || inventory.files.some(file => file.user_id !== owner))
        throw new Error("Invalid inventory owner");
      if (live()) setResult({ owner, revision, status: inventory.files.some(file => file.status === "indexed") ? "ready" : "empty" });
    } catch {
      if (live()) setResult({ owner, revision, status: "unavailable" });
    }
  }, [owner, revision]);
  useEffect(() => { void refresh(); return () => request.current?.abort(); }, [refresh]);
  const status = result?.owner === owner && result.revision === revision ? result.status : "checking";
  return { status, refresh };
}
