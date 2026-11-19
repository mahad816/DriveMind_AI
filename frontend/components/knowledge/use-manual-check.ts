"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Visible result for a user-pressed "Check status". `run` performs the real check;
 * `fingerprint` reads the controller's CURRENT state (not a stale render closure) so the
 * note can say honestly whether anything changed. Without this, a check that finds the same
 * message again looks exactly like a button that did nothing.
 */
export function useManualCheck(run: () => Promise<unknown>, fingerprint: () => string) {
  const [checking, setChecking] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const check = async () => {
    const before = fingerprint();
    setChecking(true); setNote("Checking…");
    try { await run(); } catch { /* controllers report their own errors through their state */ }
    if (!alive.current) return;
    const at = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setChecking(false);
    setNote(`Checked at ${at}. ${fingerprint() === before ? "No change." : "Status updated."}`);
  };
  return { checking, note, check };
}
