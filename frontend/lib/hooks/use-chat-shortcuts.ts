"use client";

import { useEffect } from "react";

type UseChatShortcutsOptions = {
  onNewChat: () => void;
  onFocusComposer: () => void;
  enabled?: boolean;
};

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

/** Global chat keyboard shortcuts (Cmd/Ctrl+N, Cmd/Ctrl+K). */
export function useChatShortcuts({
  onNewChat,
  onFocusComposer,
  enabled = true,
}: UseChatShortcutsOptions): void {
  useEffect(() => {
    if (!enabled) return;

    const onKeyDown = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (!mod) return;

      if (event.key.toLowerCase() === "k") {
        event.preventDefault();
        onFocusComposer();
        return;
      }

      if (event.key.toLowerCase() === "n" && !event.shiftKey) {
        if (isEditableTarget(event.target)) return;
        event.preventDefault();
        onNewChat();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled, onFocusComposer, onNewChat]);
}
