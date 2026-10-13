import type { ConversationGroup, ConversationRecord } from "@/lib/conversations/types";
import { captureConversationScope, conversationStorageKey, readConversationValue, writeConversationValue, type ConversationScope } from "./scope";
import {
  deleteConversationMessages,
  conversationMessagesAreEmpty,
} from "@/lib/conversations/messages";
import { notifyConversationsChanged } from "@/lib/conversations/events";

export const DEFAULT_CONVERSATION_TITLE = "New chat";

export function isDefaultConversationTitle(title: string): boolean {
  return title === DEFAULT_CONVERSATION_TITLE || title === "New conversation";
}

function readAll(scope: ConversationScope = captureConversationScope()): ConversationRecord[] {
  const parsed = readConversationValue(scope, "conversations");
  return Array.isArray(parsed) ? parsed.filter(isConversationRecord) : [];
}
function writeAll(conversations: ConversationRecord[], scope: ConversationScope) {
  writeConversationValue(scope, "conversations", conversations);
  notifyConversationsChanged();
}

function isConversationRecord(value: unknown): value is ConversationRecord {
  if (!value || typeof value !== "object") {
    return false;
  }
  const record = value as ConversationRecord;
  return (
    typeof record.id === "string" &&
    typeof record.title === "string" &&
    typeof record.createdAt === "string" &&
    typeof record.updatedAt === "string"
  );
}

export function createConversationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function listConversations(scope: ConversationScope = captureConversationScope()): ConversationRecord[] {
  return readAll(scope).sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  );
}

export function getConversation(id: string, scope: ConversationScope = captureConversationScope()): ConversationRecord | null {
  return readAll(scope).find((c) => c.id === id) ?? null;
}

export function createConversation(title = DEFAULT_CONVERSATION_TITLE, scope: ConversationScope = captureConversationScope()): ConversationRecord {
  const now = new Date().toISOString();
  const conversation: ConversationRecord = {
    id: createConversationId(),
    title,
    createdAt: now,
    updatedAt: now,
  };

  const all = readAll(scope);
  writeAll([conversation, ...all], scope);
  return conversation;
}

/** Reuse an empty "New chat" draft instead of stacking duplicates. */
export function findEmptyDraftConversation(scope: ConversationScope = captureConversationScope()): ConversationRecord | null {
  return (
    listConversations(scope).find(
      (conversation) =>
        isDefaultConversationTitle(conversation.title) &&
        conversationMessagesAreEmpty(conversation.id, scope),
    ) ?? null
  );
}

export function getOrCreateDraftConversation(scope: ConversationScope = captureConversationScope()): ConversationRecord {
  return findEmptyDraftConversation(scope) ?? createConversation(DEFAULT_CONVERSATION_TITLE, scope);
}

/**
 * Remove empty default-titled chats from history.
 * Keeps `keepId` so the open draft is not deleted mid-session.
 */
export function pruneEmptyDraftConversations(keepId?: string, scope: ConversationScope = captureConversationScope()): number {
  const all = readAll(scope);
  const kept = all.filter((conversation) => {
    if (keepId && conversation.id === keepId) return true;
    if (!isDefaultConversationTitle(conversation.title)) return true;
    return !conversationMessagesAreEmpty(conversation.id, scope);
  });

  if (kept.length === all.length) return 0;
  writeAll(kept, scope);
  return all.length - kept.length;
}

const prunedScopes = new Set<string>();
/** One cleanup per verified account generation, never per component mount. */
export function pruneEmptyDraftConversationsOnce(scope: ConversationScope = captureConversationScope()): number {
  const key = conversationStorageKey(scope, "conversations");
  if (!key) return 0;
  const generation = `${key}:${scope.revision}`;
  if (prunedScopes.has(generation)) return 0;
  const removed = pruneEmptyDraftConversations(undefined, scope);
  if (prunedScopes.size >= 128) prunedScopes.clear();
  prunedScopes.add(generation);
  return removed;
}

export function updateConversationTitle(id: string, title: string, scope: ConversationScope = captureConversationScope()): ConversationRecord | null {
  const trimmed = title.trim();
  if (!trimmed) {
    return null;
  }

  const all = readAll(scope);
  const index = all.findIndex((c) => c.id === id);
  if (index < 0) {
    return null;
  }

  const updated: ConversationRecord = {
    ...all[index],
    title: trimmed,
    updatedAt: new Date().toISOString(),
  };
  all[index] = updated;
  writeAll(all, scope);
  return updated;
}

export function touchConversation(id: string, scope: ConversationScope = captureConversationScope()): void {
  const all = readAll(scope);
  const index = all.findIndex((c) => c.id === id);
  if (index < 0) {
    return;
  }
  all[index] = { ...all[index], updatedAt: new Date().toISOString() };
  writeAll(all, scope);
}

export function deleteConversation(id: string, scope: ConversationScope = captureConversationScope()): void {
  deleteConversationMessages(id, scope);
  writeAll(readAll(scope).filter((c) => c.id !== id), scope);
}

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

function groupLabel(updatedAt: string, now = new Date()): string {
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) {
    return "Older";
  }

  const today = startOfDay(now).getTime();
  const target = startOfDay(date).getTime();
  const diffDays = Math.round((today - target) / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return "Previous 7 days";
  if (diffDays < 30) return "Previous 30 days";
  return "Older";
}

export function groupConversationsByDate(
  conversations: ConversationRecord[],
  now = new Date(),
): ConversationGroup[] {
  const groups = new Map<string, ConversationRecord[]>();

  for (const conversation of conversations) {
    const label = groupLabel(conversation.updatedAt, now);
    const bucket = groups.get(label) ?? [];
    bucket.push(conversation);
    groups.set(label, bucket);
  }

  const order = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"];
  return order
    .filter((label) => groups.has(label))
    .map((label) => ({ label, conversations: groups.get(label) ?? [] }));
}
