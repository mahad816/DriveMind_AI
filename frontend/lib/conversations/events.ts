/** Browser event fired when conversation list or titles change in localStorage. */

export const CONVERSATIONS_CHANGED_EVENT = "drivemind:conversations-changed";

export function notifyConversationsChanged(): void {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  window.dispatchEvent(new Event(CONVERSATIONS_CHANGED_EVENT));
}
