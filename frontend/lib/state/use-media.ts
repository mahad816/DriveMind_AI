"use client";
import { useSyncExternalStore } from "react";

/** Server and first client render assume the narrow layout; it settles after hydration without a flash of content. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    listener => { const m = window.matchMedia(query); m.addEventListener("change", listener); return () => m.removeEventListener("change", listener); },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
export function useVisible(): boolean {
  return useSyncExternalStore(
    listener => { document.addEventListener("visibilitychange", listener); return () => document.removeEventListener("visibilitychange", listener); },
    () => !document.hidden,
    () => true,
  );
}
