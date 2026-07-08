import type { CitationItem } from "@/lib/api/types";

const STORAGE_PREFIX = "drivemind:conversation-messages:";

export type StoredChatMessage = {
  id: string;
  question: string;
  status: "done" | "error";
  answer: string | null;
  citations: CitationItem[];
  retrievalCount: number;
  error: string | null;
};

function storageKey(conversationId: string): string {
  return `${STORAGE_PREFIX}${conversationId}`;
}

function isStoredMessage(value: unknown): value is StoredChatMessage {
  if (!value || typeof value !== "object") return false;
  const m = value as StoredChatMessage;
  return (
    typeof m.id === "string" &&
    typeof m.question === "string" &&
    (m.status === "done" || m.status === "error")
  );
}

export function getConversationMessages(conversationId: string): StoredChatMessage[] {
  if (typeof window === "undefined" || !conversationId) return [];

  try {
    const raw = window.localStorage.getItem(storageKey(conversationId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isStoredMessage);
  } catch {
    return [];
  }
}

export function saveConversationMessages(
  conversationId: string,
  messages: StoredChatMessage[],
): void {
  if (typeof window === "undefined" || !conversationId) return;
  window.localStorage.setItem(storageKey(conversationId), JSON.stringify(messages));
}

export function deleteConversationMessages(conversationId: string): void {
  if (typeof window === "undefined" || !conversationId) return;
  window.localStorage.removeItem(storageKey(conversationId));
}
