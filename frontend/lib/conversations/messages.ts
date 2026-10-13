import type { BoundedChatRequest, ChatHistoryTurn, CitationItem } from "@/lib/api/types";
import { captureConversationScope, conversationStorageKey, readConversationValue, writeConversationValue, ConversationStorageError, type ConversationScope } from "./scope";

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

function ownerKey(conversationId: string, turnId: string, scope: ConversationScope): string {
  return JSON.stringify([scope.owner, scope.revision, conversationId, turnId]);
}

function notifyConversationMessagesChanged(conversationId: string): void {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  window.dispatchEvent(
    new CustomEvent(CONVERSATION_MESSAGES_CHANGED_EVENT, { detail: conversationId }),
  );
}

function isStoredMessage(value: unknown): value is StoredChatMessage {
  if (!value || typeof value !== "object") return false;
  const m = value as StoredChatMessage;
  return (
    typeof m.id === "string" &&
    typeof m.question === "string" &&
    (m.status === "pending" || m.status === "done" || m.status === "error") &&
    (m.answer === null || typeof m.answer === "string") &&
    (m.error === null || typeof m.error === "string") &&
    typeof m.retrievalCount === "number" && Number.isFinite(m.retrievalCount) &&
    Array.isArray(m.citations) && m.citations.every(c => c && typeof c.chunk_id === "string" && typeof c.filename === "string" && typeof c.drive_file_id === "string" && typeof c.snippet === "string" && (c.score === null || typeof c.score === "number"))
  );
}

export function getConversationMessages(conversationId: string, scope: ConversationScope = captureConversationScope()): StoredChatMessage[] {
  if (!conversationId) return [];
  const parsed = readConversationValue(scope, `conversation-messages:${conversationId}`);
  return Array.isArray(parsed) ? parsed.filter(isStoredMessage) : [];
}
/** Unknown/corrupt storage is not evidence that a draft is empty. */
export function conversationMessagesAreEmpty(conversationId: string, scope: ConversationScope): boolean {
  const parsed = readConversationValue(scope, `conversation-messages:${conversationId}`);
  return parsed === null || (Array.isArray(parsed) && parsed.length === 0);
}

export function saveConversationMessages(conversationId: string, messages: StoredChatMessage[], scope: ConversationScope = captureConversationScope()): void {
  if (!conversationId) return;
  writeConversationValue(scope, `conversation-messages:${conversationId}`, messages);
  notifyConversationMessagesChanged(conversationId);
}

/** Append a request-owned turn without replacing unrelated stored turns. */
export function appendConversationMessage(
  conversationId: string,
  message: StoredChatMessage,
  scope: ConversationScope = captureConversationScope(),
): boolean {
  if (typeof window === "undefined" || !conversationId) return false;
  const existing = getConversationMessages(conversationId, scope);
  if (existing.some((turn) => turn.id === message.id)) return false;
  saveConversationMessages(conversationId, [...existing, message], scope);
  if (message.status === "pending") livePendingTurns.add(ownerKey(conversationId, message.id, scope));
  return true;
}

/** Update one stored turn by ID; a removed conversation or turn stays removed. */
export function updateConversationMessageById(
  conversationId: string,
  turnId: string,
  updater: (current: StoredChatMessage) => StoredChatMessage,
  scope: ConversationScope = captureConversationScope(),
): boolean {
  if (typeof window === "undefined" || !conversationStorageKey(scope, `conversation-messages:${conversationId}`)) {
    return false;
  }
  const existing = getConversationMessages(conversationId, scope);
  const index = existing.findIndex((turn) => turn.id === turnId);
  if (index < 0) return false;
  const next = updater(existing[index]);
  if (next.id !== turnId) return false;
  const updated = [...existing];
  updated[index] = next;
  const key = ownerKey(conversationId, turnId, scope);
  saveConversationMessages(conversationId, updated, scope);
  if (next.status === "pending") livePendingTurns.add(key);
  else livePendingTurns.delete(key);
  return true;
}

export function releasePendingConversationMessage(conversationId: string, turnId: string, scope: ConversationScope): void {
  livePendingTurns.delete(ownerKey(conversationId, turnId, scope));
}

/** After a fresh runtime load, make abandoned pending turns retryable. */
export function recoverInterruptedConversationMessages(
  conversationId: string,
  scope: ConversationScope = captureConversationScope(),
): StoredChatMessage[] {
  const existing = getConversationMessages(conversationId, scope);
  const updated = existing.map((turn) =>
    turn.status === "pending" && !livePendingTurns.has(ownerKey(conversationId, turn.id, scope))
      ? { ...turn, status: "error" as const, error: INTERRUPTED_REQUEST_ERROR }
      : turn,
  );
  if (updated.some((turn, index) => turn !== existing[index])) {
    saveConversationMessages(conversationId, updated, scope);
  }
  return updated;
}

export function deleteConversationMessages(conversationId: string, scope: ConversationScope = captureConversationScope()): void {
  if (typeof window === "undefined" || !conversationId) return;
  for (const turn of getConversationMessages(conversationId, scope)) {
    livePendingTurns.delete(ownerKey(conversationId, turn.id, scope));
  }
  const key = conversationStorageKey(scope, `conversation-messages:${conversationId}`);
  if (!key) throw new ConversationStorageError();
  try { window.localStorage.removeItem(key); } catch { throw new ConversationStorageError(); }
  notifyConversationMessagesChanged(conversationId);
}

/** Build the newest contiguous prior-message window from one conversation only. */
export function buildChatRequestForConversation(
  conversationId: string,
  question: string,
  options?: { beforeMessageId?: string },
  scope: ConversationScope = captureConversationScope(),
): BoundedChatRequest {
  const stored = getConversationMessages(conversationId, scope);
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
