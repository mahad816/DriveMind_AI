"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { captureConversationScope, ConversationStorageError } from "@/lib/conversations/scope";
import { CONVERSATIONS_CHANGED_EVENT } from "@/lib/conversations/events";
import {
  deleteConversation,
  getOrCreateDraftConversation,
  groupConversationsByDate,
  listConversations,
  pruneEmptyDraftConversationsOnce,
  touchConversation,
  updateConversationTitle,
} from "@/lib/conversations/storage";
import type { ConversationGroup, ConversationRecord } from "@/lib/conversations/types";

type UseConversationsResult = {
  storageError: string | null;
  conversations: ConversationRecord[];
  groups: ConversationGroup[];
  isLoading: boolean;
  refresh: () => void;
  startNewConversation: () => ConversationRecord;
  renameConversation: (id: string, title: string) => ConversationRecord | null;
  removeConversation: (id: string) => void;
  bumpConversation: (id: string) => void;
};

export function useConversations(): UseConversationsResult {
  const [scope] = useState(captureConversationScope);
  const [storageError, setStorageError] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(() => {
    setConversations(listConversations(scope));
    setIsLoading(false);
  }, [scope]);

  useEffect(() => {
    try { pruneEmptyDraftConversationsOnce(scope); } catch { /* Preserve existing records if storage is unavailable. */ }
    refresh();
  }, [refresh, scope]);

  useEffect(() => {
    const onChanged = () => refresh();
    window.addEventListener(CONVERSATIONS_CHANGED_EVENT, onChanged);
    window.addEventListener("storage", onChanged);
    return () => { window.removeEventListener(CONVERSATIONS_CHANGED_EVENT, onChanged); window.removeEventListener("storage", onChanged); };
  }, [refresh, scope]);

  const groups = useMemo(() => groupConversationsByDate(conversations), [conversations]);

  const startNewConversation = useCallback(() => {
    // Reuse an existing empty "New chat" so repeated clicks don't stack drafts.
    try { const created = getOrCreateDraftConversation(scope); refresh(); return created; }
    catch { setStorageError(new ConversationStorageError().message); throw new ConversationStorageError(); }
  }, [refresh, scope]);

  const renameConversation = useCallback(
    (id: string, title: string) => {
      try { const updated = updateConversationTitle(id, title, scope); refresh(); return updated; }
      catch { setStorageError(new ConversationStorageError().message); return null; }
    },
    [refresh, scope],
  );

  const removeConversation = useCallback(
    (id: string) => {
      try { deleteConversation(id, scope); } catch { setStorageError(new ConversationStorageError().message); }
      refresh();
    },
    [refresh, scope],
  );

  const bumpConversation = useCallback(
    (id: string) => {
      try { touchConversation(id, scope); } catch { setStorageError(new ConversationStorageError().message); }
      refresh();
    },
    [refresh, scope],
  );

  return {
    storageError,
    conversations,
    groups,
    isLoading,
    refresh,
    startNewConversation,
    renameConversation,
    removeConversation,
    bumpConversation,
  };
}
