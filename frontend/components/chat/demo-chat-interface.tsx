"use client";

import { DEMO_MODE, DEMO_QUESTION_LIMIT, questionCharacters, knowledgeAvailable } from "@/lib/demo";

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
import { ChatHeader } from "@/components/layout/chat-header";
import { useChatShortcuts } from "@/lib/hooks/use-chat-shortcuts";
import {
  CONVERSATION_MESSAGES_CHANGED_EVENT,
  appendConversationMessage,
  buildChatRequestForConversation,
  getConversationMessages,
  recoverInterruptedConversationMessages,
  releasePendingConversationMessage,
  type StoredChatMessage,
  updateConversationMessageById,
} from "@/lib/conversations/messages";
import { getConversation, isDefaultConversationTitle } from "@/lib/conversations/storage";
import { conversationTitleFromQuestion } from "@/lib/conversations/title";
import { chatErrorMessage } from "@/lib/api/errors";
import { captureConversationScope, conversationScopeIsLive, ConversationStorageError } from "@/lib/conversations/scope";
import { SESSION_REQUESTS_INVALIDATED_EVENT } from "@/lib/api/session-events";
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

export function DemoChatInterface(props: ChatInterfaceProps) {
  return DEMO_MODE ? <BrowserDemoChat {...props} /> : null;
}

function BrowserDemoChat({ conversationId }: ChatInterfaceProps) {
  const router = useRouter();
  const [scope] = useState(captureConversationScope);
  const [storageError, setStorageError] = useState<string | null>(null);
  const searchParams = useSearchParams();
  const { data: connection, isLoading: connectionLoading, error: connectionError, refetch } = useConnectionStatus({
    pollIntervalMs: 30_000,
  });
  const { needsConnect, needsPrepare } = useKnowledgeStatus({ pollIntervalMs: 30_000 });
  const { conversations, startNewConversation, renameConversation, bumpConversation } = useConversations();

  const canAsk = !connectionError && knowledgeAvailable(connection);
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
  const [evidence, setEvidence] = useState<{
    citations: CitationItem[];
    activeChunkId: string;
  } | null>(null);
  const [sourcePanelOpen, setSourcePanelOpen] = useState(false);
  const selectedCitation =
    evidence?.citations.find((citation) => citation.chunk_id === evidence.activeChunkId) ?? null;

  const conversationScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!conversationId) return;

    const record = getConversation(conversationId, scope);
    if (!record) {
      router.replace("/chat");
      return;
    }

    let stored: StoredChatMessage[];
    try { stored = recoverInterruptedConversationMessages(conversationId, scope); }
    catch { stored = getConversationMessages(conversationId, scope); setStorageError(new ConversationStorageError().message); }
    setMessages(stored.map(fromStoredMessage));
    titledRef.current = !isDefaultConversationTitle(record.title) || stored.length > 0;
    setLoadedConversationId(conversationId);
    askHandledRef.current = false;
  }, [conversationId, router, scope]);

  useEffect(() => {
    if (!conversationId || !messagesLoaded) return;
    const onMessagesChanged = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== conversationId) return;
      setMessages(getConversationMessages(conversationId, scope).map(fromStoredMessage));
    };
    const storageChanged = () => { if (conversationScopeIsLive(scope)) setMessages(getConversationMessages(conversationId, scope).map(fromStoredMessage)); };
    window.addEventListener("storage", storageChanged);
    window.addEventListener(CONVERSATION_MESSAGES_CHANGED_EVENT, onMessagesChanged);
    return () => { window.removeEventListener("storage", storageChanged); window.removeEventListener(CONVERSATION_MESSAGES_CHANGED_EVENT, onMessagesChanged); };
  }, [conversationId, messagesLoaded, scope]);

  useEffect(() => {
    const scrollRegion = conversationScrollRef.current;
    scrollRegion?.scrollTo?.({ top: scrollRegion.scrollHeight, behavior: "smooth" });
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
      if (!conversationScopeIsLive(scope)) return;
      if (!canAsk || needsPrepare || isSending || normalized.length === 0) return;
      if (DEMO_MODE && questionCharacters(normalized) > DEMO_QUESTION_LIMIT) return;

      // Empty /chat canvas: create one history entry, then continue on that route.
      if (!conversationId) {
        try {
          const created = startNewConversation();
          renameConversation(created.id, conversationTitleFromQuestion(normalized));
          router.replace(`/chat/${created.id}?ask=${encodeURIComponent(normalized)}`);
        } catch { setStorageError(new ConversationStorageError().message); }
        return;
      }
      if (!messagesLoaded) return;
      if (!getConversation(conversationId, scope)) return;
      if (getConversationMessages(conversationId, scope).some(message =>
        message.status === "pending" && !(options?.replace && options.messageId === message.id &&
          messages.some(turn => turn.id === message.id && turn.status === "error")))) {
        return;
      }

      const id = options?.messageId ?? createMessageId();
      const replace = Boolean(options?.replace);
      const request = buildChatRequestForConversation(
        conversationId,
        normalized,
        replace ? { beforeMessageId: id } : undefined,
        scope,
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
      let stored: boolean;
      try {
        stored = replace
          ? updateConversationMessageById(conversationId, id, () => pending, scope)
          : appendConversationMessage(conversationId, pending, scope);
      } catch { setStorageError(new ConversationStorageError().message); return; }
      if (!stored) return;
      setStorageError(null);

      if (!titledRef.current && !replace) {
        renameConversation(conversationId, conversationTitleFromQuestion(normalized));
        titledRef.current = true;
      }

      if (!replace) {
        setQuestion("");
      }
      const controller = new AbortController();
      const abort = () => controller.abort();
      window.addEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, abort);
      try {
        const response = await askQuestion(request, controller.signal);
        if (!conversationScopeIsLive(scope)) return;
        const settled = updateConversationMessageById(conversationId, id, (current) => ({
          ...current,
          status: "done",
          answer: response.answer,
          citations: response.citations,
          retrievalCount: response.retrieval_count,
          error: null,
        }), scope);
        if (settled) {
          bumpConversation(conversationId);
        }
      } catch (err) {
        if (!conversationScopeIsLive(scope)) return;
        const message = chatErrorMessage(err);
        try { updateConversationMessageById(conversationId, id, (current) => ({
          ...current,
          status: "error",
          answer: null,
          citations: [],
          retrievalCount: 0,
          error: message,
        }), scope); } catch {
          const failure = new ConversationStorageError().message;
          setStorageError(failure);
          // A failed browser write must not leave the mounted composer loading forever.
          setMessages(previous => previous.map(turn => turn.id === id
            ? { id, question: normalized, status: "error", error: failure, response: null }
            : turn));
        }
      } finally {
        window.removeEventListener(SESSION_REQUESTS_INVALIDATED_EVENT, abort);
        releasePendingConversationMessage(conversationId, id, scope);
      }
    },
    [
      scope,
      bumpConversation,
      conversationId,
      canAsk,
      isSending,
      messagesLoaded,
      messages,
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
    // A newly mounted conversation may hydrate before backend readiness arrives.
    // Keep the deferred ask until the empty conversation can actually send it.
    if (conversationId && messages.length === 0 && (!canAsk || needsPrepare || isSending)) return;
    askHandledRef.current = true;
    pendingAskTitleRef.current = ask;

    // Deep-link from Files / sources: create one chat and auto-send there.
    if (!conversationId) {
      try {
        const created = startNewConversation();
        router.replace(`/chat/${created.id}?ask=${encodeURIComponent(ask)}`);
      } catch { setStorageError(new ConversationStorageError().message); }
      return;
    }

    const canAutoSend =
      messages.length === 0 &&
      canAsk &&
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
    canAsk,
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
    try { const created = startNewConversation(); router.push(`/chat/${created.id}`); }
    catch { setStorageError(new ConversationStorageError().message); }
  }, [router, startNewConversation]);

  useChatShortcuts({
    onNewChat: handleNewChat,
    onFocusComposer: () => composerRef.current?.focus(),
    enabled: true,
  });

  const handleSourceSelect = useCallback((citation: CitationItem, citations: CitationItem[]) => {
    setEvidence({ citations, activeChunkId: citation.chunk_id });
    setSourcePanelOpen(true);
  }, []);

  useEffect(() => {
    setEvidence(null);
    setSourcePanelOpen(false);
  }, [conversationId]);

  const handleSourcePanelOpenChange = useCallback((open: boolean) => {
    setSourcePanelOpen(open);
    if (!open) setEvidence(null);
  }, []);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {storageError ? <p role="alert" className="p-4">{storageError}</p> : null}
      <ChatHeader
        title={
          conversationId
            ? conversations?.find((item) => item.id === conversationId)?.title ?? null
            : null
        }
      />
      {connectionError ? (
        <div className="mx-auto w-full max-w-3xl shrink-0 px-4 md:px-6">
          <Alert variant="destructive" className="mb-4">
            <AlertTitle>Connection status error</AlertTitle>
            <AlertDescription>{DEMO_MODE ? "The sample knowledge base is temporarily unavailable. Please try again shortly." : connectionError}</AlertDescription>
            <button type="button" className="mt-2 text-sm underline" onClick={() => void refetch()}>Retry status check</button>
          </Alert>
        </div>
      ) : null}

      <div
        ref={conversationScrollRef}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
        aria-busy={isSending}
        aria-label="Conversation"
      >
        <div className="mx-auto w-full max-w-3xl px-4 py-4 md:px-6 md:py-6">
          {visibleMessages.length === 0 ? (
            <EmptyStateHero
              demoReady={canAsk}
              isChecking={connectionLoading || !connection && !connectionError}
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
            disabled={!canAsk || needsPrepare}
            isLoading={isSending}
            submissionStatus={!canAsk || needsPrepare
              ? connectionError ? "Sending is unavailable. Retry the status check."
                : connectionLoading || !connection ? "Checking knowledge readiness. You can type a draft while waiting."
                : "Knowledge is not ready. Sending is unavailable."
              : undefined}
          />
        </div>
      </div>

      <SourcePanel
        citation={selectedCitation}
        citations={evidence?.citations}
        onCitationSelect={(citation) =>
          setEvidence((current) =>
            current ? { ...current, activeChunkId: citation.chunk_id } : null,
          )
        }
        open={sourcePanelOpen}
        onOpenChange={handleSourcePanelOpenChange}
      />
    </div>
  );
}
