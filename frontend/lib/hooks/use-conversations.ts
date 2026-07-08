"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { CONVERSATIONS_CHANGED_EVENT } from "@/lib/conversations/events";
import {
  createConversation,
  deleteConversation,
  groupConversationsByDate,
  listConversations,
  touchConversation,
  updateConversationTitle,
} from "@/lib/conversations/storage";
import type { ConversationGroup, ConversationRecord } from "@/lib/conversations/types";

type UseConversationsResult = {
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
  const [conversations, setConversations] = useState<ConversationRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(() => {
    setConversations(listConversations());
    setIsLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const onChanged = () => refresh();
    window.addEventListener(CONVERSATIONS_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(CONVERSATIONS_CHANGED_EVENT, onChanged);
  }, [refresh]);

  const groups = useMemo(() => groupConversationsByDate(conversations), [conversations]);

  const startNewConversation = useCallback(() => {
    const created = createConversation();
    refresh();
    return created;
  }, [refresh]);

  const renameConversation = useCallback(
    (id: string, title: string) => {
      const updated = updateConversationTitle(id, title);
      refresh();
      return updated;
    },
    [refresh],
  );

  const removeConversation = useCallback(
    (id: string) => {
      deleteConversation(id);
      refresh();
    },
    [refresh],
  );

  const bumpConversation = useCallback(
    (id: string) => {
      touchConversation(id);
      refresh();
    },
    [refresh],
  );

  return {
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
