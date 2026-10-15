"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { listDriveFiles } from "@/lib/api/files";
import { sessionOwner, sessionRevision, SESSION_REQUESTS_INVALIDATED_EVENT } from "@/lib/api/session-events";

import { INVENTORY_DISPLAY_EVENT, EMPTY_INVENTORY_COUNTS, inventoryCounts, inventoryDisplayVersion } from "@/lib/knowledge/inventory-display";
import type { InventoryCounts, InventoryNotice } from "@/lib/knowledge/inventory-display";

type Readiness = "checking" | "empty" | "ready" | "unavailable";

/** Read the same authorized inventory used by Files. No Drive dependency or polling. */
export function useIndexedKnowledge(owner: string | null, revision: number) {
  const [result, setResult] = useState<{ owner: string; revision: number; status: Readiness; counts: InventoryCounts } | null>(null);
  const request = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    request.current?.abort();
    if (!owner || sessionOwner() !== owner || sessionRevision() !== revision) return;
    const abort = new AbortController();
    request.current = abort;
    const live = () => !abort.signal.aborted && sessionOwner() === owner && sessionRevision() === revision;
    setResult({ owner, revision, status: "checking", counts: EMPTY_INVENTORY_COUNTS });
    let read = inventoryDisplayVersion();
    try {
      const operation = listDriveFiles(abort.signal);
      read = inventoryDisplayVersion();
      const inventory = await operation;
      const counts = inventoryCounts(inventory, owner);
      if (live() && read === inventoryDisplayVersion()) setResult({ owner, revision, counts, status: counts.indexed > 0 ? "ready" : "empty" });
    } catch {
      if (live() && read === inventoryDisplayVersion()) setResult({ owner, revision, status: "unavailable", counts: EMPTY_INVENTORY_COUNTS });
    }
  }, [owner, revision]);
  useEffect(() => {
    const update = (event: Event) => {
      const notice = (event as CustomEvent<InventoryNotice>).detail;
      if (notice.owner !== owner || notice.revision !== revision || sessionOwner() !== owner || sessionRevision() !== revision) return;
      setResult({ owner, revision, counts: notice.counts ?? EMPTY_INVENTORY_COUNTS,
        status: !notice.counts ? "unavailable" : notice.counts.indexed > 0 ? "ready" : "empty" });
    };
    const invalidate = () => { request.current?.abort(); setResult(null); };
    window.addEventListener(INVENTORY_DISPLAY_EVENT, update);
    window.addEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, invalidate);
    return () => { window.removeEventListener(INVENTORY_DISPLAY_EVENT, update); window.removeEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, invalidate); };
  }, [owner, revision]);
  useEffect(() => { void refresh(); return () => request.current?.abort(); }, [refresh]);
  const status = result?.owner === owner && result.revision === revision ? result.status : "checking";
  return { status, refresh, counts: result?.owner === owner && result.revision === revision ? result.counts : EMPTY_INVENTORY_COUNTS };
}
