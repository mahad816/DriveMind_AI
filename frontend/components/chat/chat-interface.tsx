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
  getConversationMessages,
  saveConversationMessages,
  type StoredChatMessage,
} from "@/lib/conversations/messages";
import { getConversation, DEFAULT_CONVERSATION_TITLE } from "@/lib/conversations/storage";
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

function isDefaultConversationTitle(title: string): boolean {
  return title === DEFAULT_CONVERSATION_TITLE || title === "New conversation";
}

function fromStoredMessage(stored: StoredChatMessage): ChatMessageState {
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

function toStoredMessages(messages: ChatMessageState[]): StoredChatMessage[] {
  return messages.flatMap((message) => {
    if (message.status === "loading") return [];
    if (message.status === "error") {
      return [
        {
          id: message.id,
          question: message.question,
          status: "error",
          answer: null,
          citations: [],
          retrievalCount: 0,
          error: message.error,
        },
      ];
    }
    return [
      {
        id: message.id,
        question: message.question,
        status: "done",
        answer: message.response.answer,
        citations: message.response.citations,
        retrievalCount: message.response.retrieval_count,
        error: null,
      },
    ];
  });
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
  const [messagesLoaded, setMessagesLoaded] = useState(!conversationId);
  const [isSending, setIsSending] = useState(false);
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

    const stored = getConversationMessages(conversationId);
    setMessages(stored.map(fromStoredMessage));
    titledRef.current = !isDefaultConversationTitle(record.title) || stored.length > 0;
    setMessagesLoaded(true);
    askHandledRef.current = false;
  }, [conversationId, router]);

  useEffect(() => {
    if (!conversationId || !messagesLoaded) return;
    saveConversationMessages(conversationId, toStoredMessages(messages));
  }, [conversationId, messages, messagesLoaded]);

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

      const id = options?.messageId ?? createMessageId();
      const replace = Boolean(options?.replace);

      if (conversationId && !titledRef.current && !replace) {
        renameConversation(conversationId, conversationTitleFromQuestion(normalized));
        titledRef.current = true;
      }

      if (!replace) {
        setQuestion("");
      }
      setIsSending(true);

      setMessages((prev) => {
        if (replace) {
          return prev.map((message) =>
            message.id === id
              ? { id, question: normalized, status: "loading" as const, error: null }
              : message,
          );
        }
        return [...prev, { id, question: normalized, status: "loading" as const, error: null }];
      });

      try {
        const response = await askQuestion({ question: normalized });
        setMessages((prev) =>
          prev.map((message) =>
            message.id === id
              ? { id, question: normalized, status: "done", error: null, response }
              : message,
          ),
        );
        if (conversationId) {
          bumpConversation(conversationId);
        }
      } catch (err) {
        const message = isApiError(err)
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Request failed";
        setMessages((prev) =>
          prev.map((entry) =>
            entry.id === id
              ? { id, question: normalized, status: "error", error: message, response: null }
              : entry,
          ),
        );
      } finally {
        setIsSending(false);
      }
    },
    [
      bumpConversation,
      conversationId,
      isConnected,
      isSending,
      needsPrepare,
      renameConversation,
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

    const canAutoSend =
      Boolean(conversationId) &&
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
    submitQuestion,
  ]);

  const handleNewChat = useCallback(() => {
    const created = startNewConversation();
    router.push(`/chat/${created.id}`);
  }, [router, startNewConversation]);

  useChatShortcuts({
    onNewChat: handleNewChat,
    onFocusComposer: () => composerRef.current?.focus(),
    enabled: Boolean(conversationId),
  });

  const handleSourceSelect = useCallback((citation: CitationItem) => {
    setSelectedCitation(citation);
    setSourcePanelOpen(true);
  }, []);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {connectionError ? (
        <Alert variant="destructive" className="mb-4 shrink-0">
          <AlertTitle>Connection status error</AlertTitle>
          <AlertDescription>{connectionError}</AlertDescription>
        </Alert>
      ) : null}

      <div
        className="min-h-0 flex-1 overflow-y-auto"
        aria-busy={isSending}
        aria-label="Conversation"
      >
        {messages.length === 0 ? (
          <EmptyStateHero
            needsConnect={needsConnect}
            needsPrepare={needsPrepare}
            isSending={isSending}
            onSuggestionClick={(suggestion) => send(suggestion)}
          />
        ) : (
          <MessageThread
            messages={messages}
            onSourceSelect={handleSourceSelect}
            onRetry={retryMessage}
            onRegenerate={regenerateMessage}
            onFollowUp={send}
            isSending={isSending}
            endRef={endRef}
          />
        )}
      </div>

      <ComposerDock
        ref={composerRef}
        value={question}
        onChange={setQuestion}
        onSubmit={() => send()}
        disabled={!isConnected || needsPrepare}
        isLoading={isSending}
      />

      <SourcePanel
        citation={selectedCitation}
        open={sourcePanelOpen}
        onOpenChange={setSourcePanelOpen}
      />
    </div>
  );
}
