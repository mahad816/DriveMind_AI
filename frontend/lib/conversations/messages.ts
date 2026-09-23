import type { BoundedChatRequest, ChatHistoryTurn, CitationItem } from "@/lib/api/types";

const STORAGE_PREFIX = "drivemind:conversation-messages:";
const MAX_HISTORY_MESSAGES = 8;
const MAX_HISTORY_MESSAGE_CHARS = 8_000;
const MAX_HISTORY_TOTAL_CHARS = 24_000;

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
