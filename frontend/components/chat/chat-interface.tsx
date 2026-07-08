"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { ComposerDock } from "@/components/chat/composer-dock";
import { EmptyStateHero } from "@/components/chat/empty-state-hero";
import { MessageThread } from "@/components/chat/message-thread";
import { SourcePanel } from "@/components/chat/source-panel";
import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { useKnowledgeStatus } from "@/lib/hooks/use-knowledge-status";
import { useConversations } from "@/lib/hooks/use-conversations";
import {
  getConversationMessages,
  saveConversationMessages,
  type StoredChatMessage,
} from "@/lib/conversations/messages";
import { getConversation } from "@/lib/conversations/storage";
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

function titleFromQuestion(question: string): string {
  const trimmed = question.trim();
  if (trimmed.length <= 48) return trimmed;
  return `${trimmed.slice(0, 48)}…`;
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
  const { renameConversation, bumpConversation } = useConversations();

  useEffect(() => {
    void refetch();
  }, [refetch]);

  const isConnected = connection?.connected ?? false;
  const titledRef = useRef(false);
  const prefilledRef = useRef(false);

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
    titledRef.current = record.title !== "New conversation" || stored.length > 0;
    setMessagesLoaded(true);
  }, [conversationId, router]);

  useEffect(() => {
    if (!conversationId || !messagesLoaded) return;
    saveConversationMessages(conversationId, toStoredMessages(messages));
  }, [conversationId, messages, messagesLoaded]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isSending]);

  useEffect(() => {
    const ask = searchParams.get("ask");
    if (!ask || prefilledRef.current) return;
    prefilledRef.current = true;
    setQuestion(ask);
  }, [searchParams]);

  const send = useCallback(
    async (overrideQuestion?: string) => {
      const normalized = (overrideQuestion ?? question).trim();
      if (!isConnected || needsPrepare || isSending || normalized.length === 0) return;

      const id = createMessageId();

      if (conversationId && !titledRef.current) {
        renameConversation(conversationId, titleFromQuestion(normalized));
        titledRef.current = true;
      }

      setQuestion("");
      setIsSending(true);

      setMessages((prev) => [
        ...prev,
        { id, question: normalized, status: "loading", error: null },
      ]);

      try {
        const response = await askQuestion({ question: normalized });
        setMessages((prev) =>
          prev.map((message) =>
            message.id === id
              ? { id, question: message.question, status: "done", error: null, response }
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
              ? { id, question: entry.question, status: "error", error: message, response: null }
              : entry,
          ),
        );
      } finally {
        setIsSending(false);
      }
    },
    [bumpConversation, conversationId, isConnected, isSending, needsPrepare, question, renameConversation],
  );

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
            onSuggestionClick={(suggestion) => void send(suggestion)}
          />
        ) : (
          <MessageThread
            messages={messages}
            onSourceSelect={handleSourceSelect}
            endRef={endRef}
          />
        )}
      </div>

      <ComposerDock
        value={question}
        onChange={setQuestion}
        onSubmit={() => void send()}
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
