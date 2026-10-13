import { DEMO_MODE } from "@/lib/demo";
import { sessionOwner, sessionRevision, SESSION_TRANSITION_KEY } from "@/lib/api/session-events";

export type ConversationScope = {
  readonly owner: string | null;
  readonly revision: number;
  readonly transition: string | null;
};

export class ConversationStorageError extends Error {
  constructor() {
    super("Conversation storage is unavailable. These changes could not be saved. Please retry after verifying your session and browser storage.");
  }
}

function transition(): string | null {
  try {
    return window.localStorage.getItem(SESSION_TRANSITION_KEY);
  } catch {
    return null;
  }
}

export function captureConversationScope(): ConversationScope {
  return Object.freeze({
    owner: sessionOwner(),
    revision: sessionRevision(),
    transition: typeof window === "undefined" ? null : transition(),
  });
}

export function conversationScopeIsLive(scope: ConversationScope): boolean {
  return DEMO_MODE || (
    scope.owner !== null &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(scope.owner) &&
    scope.owner === sessionOwner() &&
    scope.revision === sessionRevision() &&
    scope.transition === transition()
  );
}

/** Version 1 normal storage. Legacy unowned keys are never read or migrated. */
export function conversationStorageKey(scope: ConversationScope, suffix: string): string | null {
  if (typeof window === "undefined" || !conversationScopeIsLive(scope)) return null;
  return DEMO_MODE
    ? `drivemind:demo:${suffix}`
    : `drivemind:v1:normal:${scope.owner}:${suffix}`;
}

export function readConversationValue(scope: ConversationScope, suffix: string): unknown {
  const key = conversationStorageKey(scope, suffix);
  if (!key) return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    if (raw.length > 2_000_000) return undefined;
    return JSON.parse(raw) as unknown;
  } catch {
    return undefined;
  }
}

export function writeConversationValue(scope: ConversationScope, suffix: string, value: unknown): void {
  const key = conversationStorageKey(scope, suffix);
  if (!key) throw new ConversationStorageError();
  try {
    const raw = JSON.stringify(value);
    if (raw.length > 2_000_000) throw new ConversationStorageError();
    window.localStorage.setItem(key, raw);
  } catch {
    throw new ConversationStorageError();
  }
}
