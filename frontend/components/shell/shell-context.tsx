"use client";
import { createContext, useContext, useEffect } from "react";

export type ShellApi = {
  setTitle: (title: string) => void;
  openPalette: (query?: string) => void;
  openNavigation: () => void;
};
export const ShellContext = createContext<ShellApi | null>(null);
export function useShell(): ShellApi {
  const value = useContext(ShellContext);
  if (!value) throw new Error("WorkspaceShell is required");
  return value;
}
/** Names the current page for the browser tab and the mobile top bar. */
export function usePageTitle(title: string) {
  const shell = useContext(ShellContext);
  useEffect(() => {
    document.title = `${title} · DriveMind`;
    shell?.setTitle(title);
  }, [shell, title]);
}

export const FOCUS_COMPOSER_EVENT = "drivemind:focus-composer";
export const PREFILL_COMPOSER_EVENT = "drivemind:prefill-composer";
/** Hand text to the new-chat composer without sending it (questions cost money; only an explicit Send submits). */
export function prefillComposer(text: string) {
  try { window.sessionStorage.setItem("drivemind:prefill:v1", text); } catch { /* the event still carries it */ }
  window.dispatchEvent(new CustomEvent(PREFILL_COMPOSER_EVENT, { detail: text }));
}
export function takePrefill(): string | null {
  try { const v = window.sessionStorage.getItem("drivemind:prefill:v1"); window.sessionStorage.removeItem("drivemind:prefill:v1"); return v; } catch { return null; }
}
