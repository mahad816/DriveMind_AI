import type { ConversationGroup, ConversationRecord } from "@/lib/conversations/types";
import { deleteConversationMessages } from "@/lib/conversations/messages";

const STORAGE_KEY = "drivemind:conversations";

function readAll(): ConversationRecord[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(isConversationRecord);
  } catch {
    return [];
  }
}

function writeAll(conversations: ConversationRecord[]) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
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

export function listConversations(): ConversationRecord[] {
  return readAll().sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  );
}

export function getConversation(id: string): ConversationRecord | null {
  return readAll().find((c) => c.id === id) ?? null;
}

export function createConversation(title = "New conversation"): ConversationRecord {
  const now = new Date().toISOString();
  const conversation: ConversationRecord = {
    id: createConversationId(),
    title,
    createdAt: now,
    updatedAt: now,
  };

  const all = readAll();
  writeAll([conversation, ...all]);
  return conversation;
}

export function updateConversationTitle(id: string, title: string): ConversationRecord | null {
  const trimmed = title.trim();
  if (!trimmed) {
    return null;
  }

  const all = readAll();
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
  writeAll(all);
  return updated;
}

export function touchConversation(id: string): void {
  const all = readAll();
  const index = all.findIndex((c) => c.id === id);
  if (index < 0) {
    return;
  }
  all[index] = { ...all[index], updatedAt: new Date().toISOString() };
  writeAll(all);
}

export function deleteConversation(id: string): void {
  deleteConversationMessages(id);
  writeAll(readAll().filter((c) => c.id !== id));
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
