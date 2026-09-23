import type { BoundedChatRequest, ChatHistoryTurn, CitationItem } from "@/lib/api/types";

const STORAGE_PREFIX = "drivemind:conversation-messages:";
const MAX_HISTORY_MESSAGES = 8;
const MAX_HISTORY_MESSAGE_CHARS = 8_000;
const MAX_HISTORY_TOTAL_CHARS = 24_000;

export type StoredChatMessage = {
  id: string;
  question: string;
  status: "pending" | "done" | "error";
  answer: string | null;
  citations: CitationItem[];
  retrievalCount: number;
  error: string | null;
};

export const CONVERSATION_MESSAGES_CHANGED_EVENT = "drivemind:conversation-messages-changed";
export const INTERRUPTED_REQUEST_ERROR = "Previous request was interrupted.";

// Runtime ownership only; stored messages remain the durable source of truth.
const livePendingTurns = new Set<string>();

function ownerKey(conversationId: string, turnId: string): string {
  return JSON.stringify([conversationId, turnId]);
}

function notifyConversationMessagesChanged(conversationId: string): void {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  window.dispatchEvent(
    new CustomEvent(CONVERSATION_MESSAGES_CHANGED_EVENT, { detail: conversationId }),
  );
}

function storageKey(conversationId: string): string {
  return `${STORAGE_PREFIX}${conversationId}`;
}

function isStoredMessage(value: unknown): value is StoredChatMessage {
  if (!value || typeof value !== "object") return false;
  const m = value as StoredChatMessage;
  return (
    typeof m.id === "string" &&
    typeof m.question === "string" &&
    (m.status === "pending" || m.status === "done" || m.status === "error")
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
  notifyConversationMessagesChanged(conversationId);
}

/** Append a request-owned turn without replacing unrelated stored turns. */
export function appendConversationMessage(
  conversationId: string,
  message: StoredChatMessage,
): boolean {
  if (typeof window === "undefined" || !conversationId) return false;
  const existing = getConversationMessages(conversationId);
  if (existing.some((turn) => turn.id === message.id)) return false;
  saveConversationMessages(conversationId, [...existing, message]);
  if (message.status === "pending") livePendingTurns.add(ownerKey(conversationId, message.id));
  return true;
}

/** Update one stored turn by ID; a removed conversation or turn stays removed. */
export function updateConversationMessageById(
  conversationId: string,
  turnId: string,
  updater: (current: StoredChatMessage) => StoredChatMessage,
): boolean {
  if (typeof window === "undefined" || !window.localStorage.getItem(storageKey(conversationId))) {
    return false;
  }
  const existing = getConversationMessages(conversationId);
  const index = existing.findIndex((turn) => turn.id === turnId);
  if (index < 0) return false;
  const next = updater(existing[index]);
  if (next.id !== turnId) return false;
  const updated = [...existing];
  updated[index] = next;
  const key = ownerKey(conversationId, turnId);
  saveConversationMessages(conversationId, updated);
  if (next.status === "pending") livePendingTurns.add(key);
  else livePendingTurns.delete(key);
  return true;
}

/** After a fresh runtime load, make abandoned pending turns retryable. */
export function recoverInterruptedConversationMessages(
  conversationId: string,
): StoredChatMessage[] {
  const existing = getConversationMessages(conversationId);
  const updated = existing.map((turn) =>
    turn.status === "pending" && !livePendingTurns.has(ownerKey(conversationId, turn.id))
      ? { ...turn, status: "error" as const, error: INTERRUPTED_REQUEST_ERROR }
      : turn,
  );
  if (updated.some((turn, index) => turn !== existing[index])) {
    saveConversationMessages(conversationId, updated);
  }
  return updated;
}

export function deleteConversationMessages(conversationId: string): void {
  if (typeof window === "undefined" || !conversationId) return;
  for (const turn of getConversationMessages(conversationId)) {
    livePendingTurns.delete(ownerKey(conversationId, turn.id));
  }
  window.localStorage.removeItem(storageKey(conversationId));
  notifyConversationMessagesChanged(conversationId);
}

/** Build the newest contiguous prior-message window from one conversation only. */
export function buildChatRequestForConversation(
  conversationId: string,
  question: string,
  options?: { beforeMessageId?: string },
): BoundedChatRequest {
  const stored = getConversationMessages(conversationId);
  const beforeIndex = options?.beforeMessageId
    ? stored.findIndex((message) => message.id === options.beforeMessageId)
    : stored.length;
  if (beforeIndex < 0) {
    return {
      question,
      conversation_id: conversationId,
      history: [],
      history_window_complete: false,
    };
  }

  const priorTurns = stored.slice(0, beforeIndex).flatMap<ChatHistoryTurn>((message) => {
    if (message.status === "pending") return [];
    const turns: ChatHistoryTurn[] = [{ role: "user", text: message.question }];
    if (message.status === "done" && message.answer) {
      turns.push({ role: "assistant", text: message.answer });
    }
    return turns;
  });

  const history: ChatHistoryTurn[] = [];
  let totalChars = 0;
  for (let index = priorTurns.length - 1; index >= 0; index -= 1) {
    const turn = priorTurns[index];
    if (
      history.length >= MAX_HISTORY_MESSAGES ||
      turn.text.length === 0 ||
      turn.text.length > MAX_HISTORY_MESSAGE_CHARS ||
      totalChars + turn.text.length > MAX_HISTORY_TOTAL_CHARS
    ) {
      break;
    }
    history.unshift(turn);
    totalChars += turn.text.length;
  }

  return {
    question,
    conversation_id: conversationId,
    history,
    history_window_complete: history.length === priorTurns.length,
  };
}
