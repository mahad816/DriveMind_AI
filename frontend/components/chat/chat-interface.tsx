"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { ComposerDock } from "@/components/chat/composer-dock";
import type { ChatComposerHandle } from "@/components/chat/chat-composer";
import { EmptyStateHero } from "@/components/chat/empty-state-hero";
import { MessageThread } from "@/components/chat/message-thread";
import { SourcePanel } from "@/components/chat/source-panel";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { useConversations } from "@/lib/hooks/use-conversations";
import { useChatShortcuts } from "@/lib/hooks/use-chat-shortcuts";
import {
  CONVERSATION_MESSAGES_CHANGED_EVENT,
  appendConversationMessage,
  buildChatRequestForConversation,
  getConversationMessages,
  recoverInterruptedConversationMessages,
  type StoredChatMessage,
  updateConversationMessageById,
} from "@/lib/conversations/messages";
import { getConversation, isDefaultConversationTitle } from "@/lib/conversations/storage";
import { conversationTitleFromQuestion } from "@/lib/conversations/title";
import { isApiError } from "@/lib/api/errors";
import { askQuestion } from "@/lib/api/chat";
import type { ChatResponse, CitationItem } from "@/lib/api/types";

type ChatMessageState =
  | {
      id: string;
      question: string;
      status: "loading";
      error: null;
    }
  | {
      id: string;
      question: string;
      status: "done";
      error: null;
      response: ChatResponse;
    }
  | {
      id: string;
      question: string;
      status: "error";
      error: string;
      response: null;
    };

function createMessageId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function fromStoredMessage(stored: StoredChatMessage): ChatMessageState {
  if (stored.status === "pending") {
    return { id: stored.id, question: stored.question, status: "loading", error: null };
  }
  if (stored.status === "error") {
    return {
      id: stored.id,
      question: stored.question,
      status: "error",
      error: stored.error ?? "Request failed",
      response: null,
    };
  }

  return {
    id: stored.id,
    question: stored.question,
    status: "done",
    error: null,
    response: {
      query_id: stored.id,
      user_id: "",
      answer: stored.answer ?? "",
      citations: stored.citations,
      retrieval_count: stored.retrievalCount,
      message: stored.answer ?? "",
    },
  };
}

type ChatInterfaceProps = {
  conversationId?: string;
};

export function ChatInterface({ conversationId }: ChatInterfaceProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: connection, error: connectionError, refetch } = useConnectionStatus({
    pollIntervalMs: 30_000,
  });
  const { needsConnect, needsPrepare } = useKnowledgeStatus({ pollIntervalMs: 30_000 });
  const { startNewConversation, renameConversation, bumpConversation } = useConversations();

  useEffect(() => {
    void refetch();
  }, [refetch]);

  const isConnected = connection?.connected ?? false;
  const titledRef = useRef(false);
  const askHandledRef = useRef(false);
  const pendingAskTitleRef = useRef<string | null>(null);
  const composerRef = useRef<ChatComposerHandle>(null);

  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessageState[]>([]);
  const [loadedConversationId, setLoadedConversationId] = useState<string | null>(null);
  const messagesLoaded = !conversationId || loadedConversationId === conversationId;
  const visibleMessages = messagesLoaded ? messages : [];
  const isSending = messagesLoaded && messages.some((message) => message.status === "loading");
  const [selectedCitation, setSelectedCitation] = useState<CitationItem | null>(null);
  const [sourcePanelOpen, setSourcePanelOpen] = useState(false);

  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!conversationId) return;

    const record = getConversation(conversationId);
    if (!record) {
      router.replace("/chat");
      return;
    }

    const stored = recoverInterruptedConversationMessages(conversationId);
    setMessages(stored.map(fromStoredMessage));
    titledRef.current = !isDefaultConversationTitle(record.title) || stored.length > 0;
    setLoadedConversationId(conversationId);
    askHandledRef.current = false;
  }, [conversationId, router]);

  useEffect(() => {
    if (!conversationId || !messagesLoaded) return;
    const onMessagesChanged = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== conversationId) return;
      setMessages(getConversationMessages(conversationId).map(fromStoredMessage));
    };
    window.addEventListener(CONVERSATION_MESSAGES_CHANGED_EVENT, onMessagesChanged);
    return () =>
      window.removeEventListener(CONVERSATION_MESSAGES_CHANGED_EVENT, onMessagesChanged);
  }, [conversationId, messagesLoaded]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isSending]);

  useEffect(() => {
    if (!conversationId || !messagesLoaded || titledRef.current) return;

    const ask = pendingAskTitleRef.current;
    if (!ask) return;

    renameConversation(conversationId, conversationTitleFromQuestion(ask));
    titledRef.current = true;
    pendingAskTitleRef.current = null;
  }, [conversationId, messagesLoaded, renameConversation]);

  const submitQuestion = useCallback(
    async (normalized: string, options?: { messageId?: string; replace?: boolean }) => {
      if (!isConnected || needsPrepare || isSending || normalized.length === 0) return;

      // Empty /chat canvas: create one history entry, then continue on that route.
      if (!conversationId) {
        const created = startNewConversation();
        renameConversation(created.id, conversationTitleFromQuestion(normalized));
        router.replace(`/chat/${created.id}?ask=${encodeURIComponent(normalized)}`);
        return;
      }
      if (!messagesLoaded) return;
      if (!getConversation(conversationId)) return;
      if (getConversationMessages(conversationId).some((message) => message.status === "pending")) {
        return;
      }

      const id = options?.messageId ?? createMessageId();
      const replace = Boolean(options?.replace);
      const request = buildChatRequestForConversation(
        conversationId,
        normalized,
        replace ? { beforeMessageId: id } : undefined,
      );
      const pending: StoredChatMessage = {
        id,
        question: normalized,
        status: "pending",
        answer: null,
        citations: [],
        retrievalCount: 0,
        error: null,
      };
      const stored = replace
        ? updateConversationMessageById(conversationId, id, () => pending)
        : appendConversationMessage(conversationId, pending);
      if (!stored) return;

      if (!titledRef.current && !replace) {
        renameConversation(conversationId, conversationTitleFromQuestion(normalized));
        titledRef.current = true;
      }

      if (!replace) {
        setQuestion("");
      }
      try {
        const response = await askQuestion(request);
        const settled = updateConversationMessageById(conversationId, id, (current) => ({
          ...current,
          status: "done",
          answer: response.answer,
          citations: response.citations,
          retrievalCount: response.retrieval_count,
          error: null,
        }));
        if (settled) {
          bumpConversation(conversationId);
        }
      } catch (err) {
        const message = isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Request failed";
        updateConversationMessageById(conversationId, id, (current) => ({
          ...current,
          status: "error",
          answer: null,
          citations: [],
          retrievalCount: 0,
          error: message,
        }));
      }
    },
    [
      bumpConversation,
      conversationId,
      isConnected,
      isSending,
      messagesLoaded,
      needsPrepare,
      renameConversation,
      router,
      startNewConversation,
    ],
  );

  const send = useCallback(
    (overrideQuestion?: string) => {
      const normalized = (overrideQuestion ?? question).trim();
      void submitQuestion(normalized);
    },
    [question, submitQuestion],
  );

  const retryMessage = useCallback(
    (messageId: string, questionText: string) => {
      void submitQuestion(questionText.trim(), { messageId, replace: true });
    },
    [submitQuestion],
  );

  const regenerateMessage = useCallback(
    (messageId: string, questionText: string) => {
      void submitQuestion(questionText.trim(), { messageId, replace: true });
    },
    [submitQuestion],
  );

  useEffect(() => {
    const ask = searchParams.get("ask");
    if (!ask || askHandledRef.current || !messagesLoaded) return;
    askHandledRef.current = true;
    pendingAskTitleRef.current = ask;

    // Deep-link from Files / sources: create one chat and auto-send there.
    if (!conversationId) {
      const created = startNewConversation();
      router.replace(`/chat/${created.id}?ask=${encodeURIComponent(ask)}`);
      return;
    }

    const canAutoSend =
      messages.length === 0 &&
      isConnected &&
      !needsPrepare &&
      !isSending;

    if (canAutoSend) {
      router.replace(`/chat/${conversationId}`, { scroll: false });
      void submitQuestion(ask.trim());
      return;
    }

    setQuestion(ask);
  }, [
    conversationId,
    isConnected,
    isSending,
    messages.length,
    messagesLoaded,
    needsPrepare,
    router,
    searchParams,
    startNewConversation,
    submitQuestion,
  ]);

  const handleNewChat = useCallback(() => {
    const created = startNewConversation();
    router.push(`/chat/${created.id}`);
  }, [router, startNewConversation]);

  useChatShortcuts({
    onNewChat: handleNewChat,
    onFocusComposer: () => composerRef.current?.focus(),
    enabled: true,
  });

  const handleSourceSelect = useCallback((citation: CitationItem) => {
    setSelectedCitation(citation);
    setSourcePanelOpen(true);
  }, []);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {connectionError ? (
        <div className="mx-auto w-full max-w-3xl shrink-0 px-4 md:px-6">
          <Alert variant="destructive" className="mb-4">
            <AlertTitle>Connection status error</AlertTitle>
            <AlertDescription>{connectionError}</AlertDescription>
          </Alert>
        </div>
      ) : null}

      <div
        className="min-h-0 flex-1 overflow-y-auto"
        aria-busy={isSending}
        aria-label="Conversation"
      >
        <div className="mx-auto w-full max-w-3xl px-4 py-4 md:px-6 md:py-6">
          {visibleMessages.length === 0 ? (
            <EmptyStateHero
              needsConnect={needsConnect}
              needsPrepare={needsPrepare}
              isSending={isSending}
              onSuggestionClick={(suggestion) => send(suggestion)}
            />
          ) : (
            <MessageThread
              messages={visibleMessages}
              onSourceSelect={handleSourceSelect}
              onRetry={retryMessage}
              onRegenerate={regenerateMessage}
              onFollowUp={send}
              isSending={isSending}
              endRef={endRef}
            />
          )}
        </div>
      </div>

      <div className="shrink-0 px-4 pb-4 md:px-6">
        <div className="mx-auto w-full max-w-3xl">
          <ComposerDock
            ref={composerRef}
            value={question}
            onChange={setQuestion}
            onSubmit={() => send()}
            disabled={!isConnected || needsPrepare}
            isLoading={isSending}
          />
        </div>
      </div>

      <SourcePanel
        citation={selectedCitation}
        open={sourcePanelOpen}
        onOpenChange={setSourcePanelOpen}
      />
    </div>
  );
}
