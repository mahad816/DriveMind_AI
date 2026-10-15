"use client";

import Link from "next/link";
import { useIndexedKnowledge } from "@/lib/hooks/use-indexed-knowledge";
import { validQuestion } from "@/lib/chat/question";

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
  return <OwnedServerChat key={`${state.ownerId}:${state.sessionRevision}:${conversationId ?? "new"}`} conversationId={conversationId} />;
}

function OwnedServerChat({ conversationId }: { conversationId?: string }) {
  const { state, controller, creationDraft } = useServerConversations();
  const knowledge = useIndexedKnowledge(state.ownerId, state.sessionRevision);
  const sending = useRef(false);
  const router = useRouter(), search = useSearchParams();
  const [draft, setDraft] = useState("");
  const editable = useRef({ text: "", edit: 0 });
  const submittedDraft = useRef<{ requestId: string; edit: number; text: string } | null>(null);
  const mounted = useRef(false);
  const handoff = useRef<ReturnType<typeof creationDraft.stage>>(null);
  const reconciling = useRef(false);
  // Only this component's own new creation can authorize a draft transfer.
  // A replacement composer never derives ownership from shared pending state.
  const creationOrigin = useRef<{ requestId: string; owner: string; revision: number } | null>(null);
  const [creationRecovered, setCreationRecovered] = useState(false);
  const changeDraft = (text: string) => {
    editable.current = { text, edit: editable.current.edit + 1 };
    creationDraft.update(handoff.current, text);
    setDraft(text);
  };
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
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
  useEffect(() => {
    const transfer = creationDraft.take(state.ownerId, state.sessionRevision, routeId);
    // A late handoff never replaces text already edited at the destination.
    if (transfer !== null && editable.current.edit === 0) {
      editable.current.text = transfer.text;
      setDraft(transfer.text);
      if (transfer.submittedRequestId) submittedDraft.current = {
        requestId: transfer.submittedRequestId, edit: 0, text: transfer.text,
      };
    }
  }, [creationDraft, routeId, state.ownerId, state.sessionRevision]);
  useEffect(() => {
    const pending = submittedDraft.current, receipt = state.submission;
    // A local request reservation is not proof that a turn was submitted.
    if (pending && receipt?.turn && receipt.payload.client_request_id === pending.requestId
      && receipt.turn.client_request_id === pending.requestId) {
      submittedDraft.current = null;
      if (editable.current.edit === pending.edit && editable.current.text === pending.text) {
        editable.current = { text: "", edit: editable.current.edit + 1 };
        creationDraft.update(handoff.current, "");
        setDraft("");
      }
    }
  }, [creationDraft, state.submission]);
  useEffect(() => {
    // Never adopt or automatically submit a question from browser history.
    if (search.has("ask")) router.replace(routeId ? `/chat/${routeId}` : "/chat", { scroll: false });
  }, [search, router, routeId]);

  const canFinishCreation = (owner: string | null, revision: number, id: string) => {
    const current = controller.getSnapshot();
    return mounted.current && current.ownerId === owner && current.sessionRevision === revision
      && current.selectedId === id && routeRef.current === routeId;
  };
  const navigateCreated = (creationId: string, id: string) => {
    const origin = creationOrigin.current;
    if (!origin || origin.requestId !== creationId || origin.owner !== state.ownerId
      || origin.revision !== state.sessionRevision || !canFinishCreation(origin.owner, origin.revision, id)) return;
    handoff.current = creationDraft.stage({ owner: origin.owner, revision: origin.revision,
      creationId, conversationId: id, text: editable.current.text,
      submittedRequestId: submittedDraft.current?.edit === editable.current.edit
        ? submittedDraft.current.requestId : undefined });
    if (handoff.current) router.replace(`/chat/${id}`);
  };
  const reconcileCreation = async () => {
    const pending = controller.getSnapshot().creation;
    if (!pending || reconciling.current) return;
    const origin = creationOrigin.current;
    const ownsDraft = origin?.requestId === pending.requestId && origin.owner === state.ownerId
      && origin.revision === state.sessionRevision;
    reconciling.current = true;
    try {
      const row = await controller.retryCreate({ requestId: pending.requestId, select: ownsDraft });
      if (row && ownsDraft) navigateCreated(pending.requestId, row.id);
      else if (row && mounted.current && routeRef.current === routeId) {
        const current = controller.getSnapshot();
        if (current.ownerId === state.ownerId && current.sessionRevision === state.sessionRevision
          && current.selectedId === routeId) setCreationRecovered(true);
      }
    } finally { reconciling.current = false; }
  };
  const reconcileLatest = useRef(reconcileCreation);
  reconcileLatest.current = reconcileCreation;
  useEffect(() => creationDraft.registerReconciler(() => { void reconcileLatest.current(); }), [creationDraft]);
  const submitDraft = (text: string, edit: number) => {
    const previous = controller.getSnapshot().submission?.payload.client_request_id;
    const submitted = controller.submitQuestion(text.trim());
    const receipt = controller.getSnapshot().submission;
    // Carry the exact logical request identity; clear only after its server receipt.
    if (receipt && receipt.payload.client_request_id !== previous && receipt.payload.question === text.trim()
      && editable.current.edit === edit && editable.current.text === text)
      submittedDraft.current = { requestId: receipt.payload.client_request_id, edit, text };
    return submitted;
  };
  const create = async () => {
    const row = await controller.create();
    if (row && canFinishCreation(state.ownerId, state.sessionRevision, row.id)) router.push(`/chat/${row.id}`);
  };
  const send = async (text = draft) => {
    if (!validQuestion(text) || knowledge.status !== "ready" || sending.current || busy || !state.ownerId || state.detailLoading || state.metadataLoading) return;
    const owner = state.ownerId, revision = state.sessionRevision;
    const authority = controller.getSnapshot();
    if (authority.ownerId !== owner || authority.sessionRevision !== revision || authority.selectedId !== routeId || authority.creation) return;
    const edit = editable.current.edit;
    sending.current = true;
    try {
      if (!routeId) {
        const creating = controller.create();
        const creationId = controller.getSnapshot().creation?.requestId;
        if (creationId) creationOrigin.current = { requestId: creationId, owner, revision };
        const row = await creating;
        if (!row || !creationId || !canFinishCreation(owner, revision, row.id)) return;
        const submitted = submitDraft(text, edit);
        navigateCreated(creationId, row.id);
        await submitted;
      }
      else if (selected) {
        await submitDraft(text, edit);
      }
    } finally { sending.current = false; }
  };
  useChatShortcuts({ onNewChat: () => { void create(); }, onFocusComposer: () => composer.current?.focus(), enabled: !!state.ownerId });
  const currentEvidence = selected && evidence?.conversationId === routeId ? evidence : null;
  const messages = turns.map(turn => renderTurn(turn, state.ownerId ?? ""));
  if (request && !request.turn && waiting)
    messages.push({ id: request.payload.client_request_id, question: request.payload.question, status: "loading", error: null });

  return <div className="flex min-h-0 flex-1 flex-col">
    <ChatHeader title={selected ? state.conversation?.title ?? null : null} />
    {state.error ? <p role="alert" className="px-4 py-2">{state.error.message}</p> : null}
    {creationRecovered ? <p role="status" className="px-4 py-2 text-sm text-muted-foreground">Conversation recovered. It is available in your conversation history. Your current draft has not moved.</p> : null}
    <div className="flex flex-wrap gap-2 px-4 py-2">
      {selected ? <Button variant="ghost" disabled={state.detailLoading} onClick={() => void controller.reloadSelected()}>Refresh conversation</Button> : null}
      {state.detailLoading ? <span role="status">Refreshing conversation…</span> : null}
      {state.creation?.uncertain ? <Button onClick={() => void reconcileCreation()}>Reconcile creation</Button> : null}
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
        {knowledge.status !== "ready" ? <div className="mb-4 space-y-3 rounded-lg border border-border p-4">
          <p role="status" className="text-sm text-muted-foreground">{knowledge.status === "checking"
            ? "Checking prepared knowledge…"
            : knowledge.status === "empty"
              ? "Prepare a document to ask questions about your knowledge."
              : "Prepared knowledge is temporarily unavailable. Your saved conversations are still readable."}</p>
          {knowledge.status === "empty" ? <Link href="/files" className="text-sm font-medium underline underline-offset-4">Choose documents in Files</Link> : null}
          {knowledge.status === "unavailable" ? <Button variant="outline" onClick={() => void knowledge.refresh()}>Check again</Button> : null}
        </div> : null}
        {messages.length ? <MessageThread messages={messages} conversationId={routeId ?? undefined} isSending={busy || state.metadataLoading || knowledge.status !== "ready"}
          onSourceSelect={(citation, citations) => setEvidence({ conversationId: routeId, citations, active: citation.chunk_id })}
          onRetry={(_id, question) => { void send(question); }} onFollowUp={question => { void send(question); }} />
          : routeId && !selected ? <p className="text-muted-foreground">Conversation unavailable or loading. Select a conversation or start a new chat.</p>
          : knowledge.status !== "ready" ? null
          : <EmptyStateHero needsConnect={false} needsPrepare={false} isSending={busy || state.detailLoading || !state.ownerId} onSuggestionClick={question => { void send(question); }} />}
      </div>
    </div>
    <div className="shrink-0 px-4 pb-4 md:px-6"><div className="mx-auto w-full max-w-3xl">
      <ComposerDock ref={composer} value={draft} onChange={changeDraft} onSubmit={() => void send()}
        disabled={knowledge.status !== "ready" || !state.ownerId || (routeId !== null && !selected) || state.detailLoading || state.metadataLoading || busy}
        isLoading={waiting || !!running} submissionStatus={uncertain ? "Reconcile the original submission before sending another question." : knowledge.status !== "ready" ? "Sending is unavailable until prepared knowledge can be verified. Your draft remains editable." : undefined} />
    </div></div>
    <SourcePanel conversationId={routeId ?? undefined} open={!!currentEvidence} citation={currentEvidence?.citations.find(citation => citation.chunk_id === currentEvidence.active) ?? null}
      citations={currentEvidence?.citations} onOpenChange={open => { if (!open) setEvidence(null); }}
      onCitationSelect={citation => setEvidence(current => current ? { ...current, active: citation.chunk_id } : null)} />
  </div>;
}
