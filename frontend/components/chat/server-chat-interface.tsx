"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useServerConversations } from "@/components/providers/server-conversations-provider";
import { EmptyStateHero } from "@/components/chat/empty-state-hero";
import { ComposerDock } from "@/components/chat/composer-dock";
import { MessageThread } from "@/components/chat/message-thread";
import type { ChatTurn } from "@/components/chat/message-thread";
import { SourcePanel } from "@/components/chat/source-panel";
import { ChatHeader } from "@/components/layout/chat-header";
import { Button } from "@/components/ui/button";
import type { CitationItem } from "@/lib/api/types";
import type { StoredTurn } from "@/lib/api/conversations";
import { useChatShortcuts } from "@/lib/hooks/use-chat-shortcuts";
import type { ChatComposerHandle } from "@/components/chat/chat-composer";

function renderTurn(turn: StoredTurn, owner: string): ChatTurn {
  if (turn.status === "COMPLETED")
    return { id: turn.id, question: turn.question, status: "done", error: null, response: {
      query_id: turn.query_id, user_id: owner, answer: turn.answer, message: turn.answer,
      citations: turn.citations, retrieval_count: turn.retrieval_count,
    } };
  if (turn.status === "RUNNING")
    return { id: turn.id, question: turn.question, status: "loading", error: null };
  return { id: turn.id, question: turn.question, status: "error", response: null,
    error: turn.status === "INTERRUPTED" ? "This attempt was interrupted. A retry creates a new attempt."
      : "This attempt failed. A retry creates a new attempt." };
}

export function ServerChatInterface({ conversationId }: { conversationId?: string }) {
  const { state } = useServerConversations();
  // Remount local drafts/source previews on every verified account or session revision.
  return <OwnedServerChat key={`${state.ownerId}:${state.sessionRevision}`} conversationId={conversationId} />;
}

function OwnedServerChat({ conversationId }: { conversationId?: string }) {
  const { state, controller } = useServerConversations();
  const router = useRouter(), search = useSearchParams();
  const [draft, setDraft] = useState("");
  const [evidence, setEvidence] = useState<{ conversationId: string | null; citations: CitationItem[]; active: string } | null>(null);
  const composer = useRef<ChatComposerHandle>(null);
  const routeId = conversationId?.toLowerCase() ?? null;
  const routeRef = useRef(routeId);
  routeRef.current = routeId;
  const selected = state.selectedId === routeId && !!state.conversation;
  const turns = selected ? state.turns : [];
  const request = selected ? state.submission : null;
  const running = turns.find(turn => turn.status === "RUNNING");
  const waiting = request?.phase === "submitting";
  const uncertain = request?.phase === "unknown";
  const busy = !!running || waiting || uncertain || !!state.creation;

  useEffect(() => {
    if (!state.ownerId) return;
    const current = controller.getSnapshot();
    if (current.selectedId !== routeId || (routeId && !current.conversation))
      void controller.select(routeId);
  }, [controller, routeId, state.ownerId]);
  useEffect(() => { setDraft(""); setEvidence(null); }, [routeId]);
  useEffect(() => {
    // Never adopt or automatically submit a question from browser history.
    if (search.has("ask")) router.replace(routeId ? `/chat/${routeId}` : "/chat", { scroll: false });
  }, [search, router, routeId]);

  const create = async () => {
    const row = await controller.create();
    if (row && controller.getSnapshot().selectedId === row.id && routeRef.current === routeId) router.push(`/chat/${row.id}`);
  };
  const send = async (text = draft) => {
    if (!text.trim() || busy || !state.ownerId || state.detailLoading || state.metadataLoading) return;
    const owner = state.ownerId, revision = state.sessionRevision;
    const authority = controller.getSnapshot();
    if (authority.ownerId !== owner || authority.sessionRevision !== revision || authority.selectedId !== routeId) return;
    if (!routeId) {
      const row = await controller.create();
      const current = controller.getSnapshot();
      if (!row || current.ownerId !== owner || current.sessionRevision !== revision || current.selectedId !== row.id || routeRef.current !== routeId) return;
      setDraft("");
      router.replace(`/chat/${row.id}`);
      await controller.submitQuestion(text.trim());
    }
    else if (selected) {
      setDraft("");
      await controller.submitQuestion(text.trim());
    }
  };
  useChatShortcuts({ onNewChat: () => { void create(); }, onFocusComposer: () => composer.current?.focus(), enabled: !!state.ownerId });
  const currentEvidence = selected && evidence?.conversationId === routeId ? evidence : null;
  const messages = turns.map(turn => renderTurn(turn, state.ownerId ?? ""));
  if (request && !request.turn && waiting)
    messages.push({ id: request.payload.client_request_id, question: request.payload.question, status: "loading", error: null });

  return <div className="flex min-h-0 flex-1 flex-col">
    <ChatHeader title={selected ? state.conversation?.title ?? null : null} />
    {state.error ? <p role="alert" className="px-4 py-2">{state.error.message}</p> : null}
    <div className="flex flex-wrap gap-2 px-4 py-2">
      {selected ? <Button variant="ghost" disabled={state.detailLoading} onClick={() => void controller.reloadSelected()}>Refresh conversation</Button> : null}
      {state.detailLoading ? <span role="status">Refreshing conversation…</span> : null}
      {state.creation?.uncertain ? <Button onClick={() => void controller.retryCreate().then(row => { if (row && controller.getSnapshot().selectedId === row.id && routeRef.current === routeId) router.replace(`/chat/${row.id}`); })}>Reconcile creation</Button> : null}
      {waiting ? <Button variant="outline" onClick={() => controller.cancelSubmission()}>Stop waiting</Button> : null}
      {uncertain ? <><p role="status">The response is unknown. Stopping the wait does not stop server generation.</p>
        <Button onClick={() => void controller.reconcileSubmission()}>Reconcile submission</Button></> : null}
      {running ? <>
        <span role="status">Server turn RUNNING</span>
        <Button disabled={state.polling} onClick={() => void controller.pollTurn(running.id)}>Check progress</Button>
        {state.polling ? <Button onClick={() => controller.stopPolling()}>Stop checking</Button> : null}
        {state.executionExpired[running.id] ? <Button onClick={() => void controller.interruptExpiredTurn(running.id)}>Interrupt expired attempt</Button> : null}
      </> : null}
      {state.metadataLoading ? <span role="status">Refreshing conversation metadata…</span> : null}
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" aria-label="Conversation" aria-busy={waiting || !!running}>
      <div className="mx-auto w-full max-w-3xl px-4 py-4 md:px-6 md:py-6">
        {selected && state.nextTurnCursor !== null ? <Button disabled={state.detailLoading} onClick={() => void controller.loadOlderTurns()}>Load older turns</Button> : null}
        {messages.length ? <MessageThread messages={messages} isSending={busy || state.metadataLoading}
          onSourceSelect={(citation, citations) => setEvidence({ conversationId: routeId, citations, active: citation.chunk_id })}
          onRetry={(_id, question) => { void send(question); }} onFollowUp={question => { void send(question); }} />
          : routeId && !selected ? <p className="text-muted-foreground">Conversation unavailable or loading. Select a conversation or start a new chat.</p>
          : <EmptyStateHero needsConnect={false} needsPrepare={false} isSending={busy || state.detailLoading || !state.ownerId} onSuggestionClick={question => { void send(question); }} />}
      </div>
    </div>
    <div className="shrink-0 px-4 pb-4 md:px-6"><div className="mx-auto w-full max-w-3xl">
      <ComposerDock ref={composer} value={draft} onChange={setDraft} onSubmit={() => void send()}
        disabled={!state.ownerId || (routeId !== null && !selected) || state.detailLoading || state.metadataLoading || busy}
        isLoading={waiting || !!running} submissionStatus={uncertain ? "Reconcile the original submission before sending another question." : undefined} />
    </div></div>
    <SourcePanel open={!!currentEvidence} citation={currentEvidence?.citations.find(citation => citation.chunk_id === currentEvidence.active) ?? null}
      citations={currentEvidence?.citations} onOpenChange={open => { if (!open) setEvidence(null); }}
      onCitationSelect={citation => setEvidence(current => current ? { ...current, active: citation.chunk_id } : null)} />
  </div>;
}
