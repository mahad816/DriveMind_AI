"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useServerConversations } from "@/components/providers/server-conversations-provider";
import { useApplicationSession } from "@/components/providers/application-session-provider";
import { useFiles, useWorkspace } from "@/components/workspace/workspace-provider";
import { FOCUS_COMPOSER_EVENT, PREFILL_COMPOSER_EVENT, takePrefill, usePageTitle } from "@/components/shell/shell-context";
import { cn } from "@/lib/utils";
import { Composer } from "@/components/chat/composer";
import type { ComposerHandle } from "@/components/chat/composer";
import { CompletedTurn, NoticeTurn, PendingTurn, TurnFrame } from "@/components/chat/turn";
import { CitedFilesContext, EvidenceSheet, PassageCache, PassageCacheContext } from "@/components/chat/evidence";
import { NewChatCanvas } from "@/components/chat/new-chat-canvas";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Menu } from "@/components/ui/menu";
import { Skeleton, TextInput } from "@/components/ui/controls";
import { useToast } from "@/components/ui/toast";
import { validQuestion } from "@/lib/chat/question";
import { readDraft, writeDraft } from "@/lib/state/browser-memory";
import { useMediaQuery, useVisible } from "@/lib/state/use-media";
import type { CitationItem } from "@/lib/api/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const scrollMemory = new Map<string, number>();

export function ChatWorkspace() {
  const params = useParams<{ id?: string }>();
  const raw = params.id ?? null;
  const routeId = raw && UUID.test(raw) ? raw.toLowerCase() : null;
  const invalidRoute = raw !== null && routeId === null;
  const { state, controller } = useServerConversations();
  const session = useApplicationSession();
  const { owner } = useWorkspace();
  const files = useFiles();
  const router = useRouter();
  const wide = useMediaQuery("(min-width: 1280px)");
  const visible = useVisible();
  const [cache] = useState(() => new PassageCache());

  const composer = useRef<ComposerHandle>(null);
  const scroller = useRef<HTMLDivElement>(null);

  // ----- selection follows the URL (never the other way round, so a created conversation is not reselected) -----
  const [loadedFor, setLoadedFor] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (!state.ownerId) return;
    const current = controller.getSnapshot();
    if (current.selectedId !== routeId || (routeId && !current.conversation)) {
      setLoadedFor(undefined);
      void controller.select(routeId).then(() => setLoadedFor(routeId));
    } else setLoadedFor(routeId);
  }, [controller, routeId, state.ownerId]);
  const selected = !!routeId && state.selectedId === routeId && !!state.conversation;
  const notFound = invalidRoute || (!!routeId && loadedFor === routeId && !selected && !state.detailLoading);
  usePageTitle(selected ? state.conversation!.title : routeId ? "Conversation" : "New chat");

  // ----- draft: per conversation, kept in this tab, restored on return -----
  const [draft, setDraft] = useState("");
  useEffect(() => { setDraft(readDraft(owner, routeId)); }, [owner, routeId]);
  useEffect(() => { const t = setTimeout(() => writeDraft(owner, routeId, draft), 300); return () => clearTimeout(t); }, [owner, routeId, draft]);
  useEffect(() => {
    const focus = () => composer.current?.focus();
    const prefill = (event: Event) => { if (!routeId) { setDraft((event as CustomEvent<string>).detail); takePrefill(); requestAnimationFrame(focus); } };
    if (!routeId) { const pending = takePrefill(); if (pending) { setDraft(pending); requestAnimationFrame(focus); } }
    window.addEventListener(FOCUS_COMPOSER_EVENT, focus);
    window.addEventListener(PREFILL_COMPOSER_EVENT, prefill);
    return () => { window.removeEventListener(FOCUS_COMPOSER_EVENT, focus); window.removeEventListener(PREFILL_COMPOSER_EVENT, prefill); };
  }, [routeId]);

  // ----- what is happening now -----
  const turns = selected ? state.turns : [];
  const submission = selected && state.submission?.conversationId === routeId ? state.submission : null;
  const streaming = state.streaming && state.streaming.conversationId === routeId ? state.streaming : null;
  const running = turns.find(turn => turn.status === "RUNNING");
  const waiting = submission?.phase === "submitting";
  const unknown = submission?.phase === "unknown";
  const [outgoing, setOutgoing] = useState<string | null>(null);
  const [stopped, setStopped] = useState<string | null>(null);
  useEffect(() => { if (routeId) setOutgoing(null); }, [routeId]);
  const sending = useRef(false);
  const [sendingState, setSendingState] = useState(false);
  const ready = files.data ? files.data.filter(f => f.status === "indexed").length : null;
  const busy = waiting || !!running || unknown || !!outgoing;

  const blocked = session.offline ? "You're offline. Your question is kept until you reconnect."
    : !session.canMutate ? "Sending resumes when DriveMind is reachable again. Your question is kept."
    : ready === 0 ? "Prepare a document before asking."
    : unknown ? "Resolve the question above before asking another."
    : running && !streaming ? "Wait for the current answer to finish."
    : routeId && !selected ? (notFound ? "This conversation isn't available." : "Loading the conversation…")
    : null;

  const send = useCallback(async (text: string) => {
    const question = text.trim();
    if (!validQuestion(question) || sending.current || !session.canMutate) return;
    sending.current = true; setSendingState(true);
    try {
      if (!routeId) {
        // Create only now, on the first send (never on "New chat"). The same creation id is reused on retry.
        setOutgoing(question); setDraft(""); writeDraft(owner, null, "");
        const pending = controller.getSnapshot().creation;
        const row = pending ? await controller.retryCreate({ requestId: pending.requestId }) : await controller.create();
        if (!row) { setOutgoing(null); setDraft(question); return; }
        const submitted = controller.submitQuestion(question);
        // The outgoing question stays on screen until the URL names the new conversation (cleared by the effect below).
        router.replace(`/chat/${row.id}`, { scroll: false });
        await submitted;
      } else if (selected) {
        const previous = controller.getSnapshot().submission?.payload.client_request_id;
        const submitted = controller.submitQuestion(question);
        const accepted = controller.getSnapshot().submission;
        // Clear the box only when the controller really took this question.
        if (accepted && accepted.payload.client_request_id !== previous && accepted.payload.question === question) { setDraft(""); writeDraft(owner, routeId, ""); }
        await submitted;
      }
    } finally { sending.current = false; setSendingState(false); }
  }, [controller, owner, routeId, router, selected, session.canMutate]);

  const stop = () => { if (submission) setStopped(submission.payload.client_request_id); controller.cancelSubmission(); };
  const reconcile = () => { setStopped(null); void controller.reconcileSubmission(); };

  // Non-streamed RUNNING turns (from history or a 202 replay) are checked automatically while visible; reads only.
  const polled = useRef(new Set<string>());
  useEffect(() => {
    if (!running || streaming || waiting || !visible || state.polling || polled.current.has(running.id)) return;
    polled.current.add(running.id);
    void controller.pollTurn(running.id);
  }, [controller, running, streaming, waiting, visible, state.polling]);

  // ----- scrolling: restore per conversation, follow new questions -----
  const lastCount = useRef(0);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || (routeId && !selected)) return;
    const key = routeId ?? "new";
    const saved = scrollMemory.get(key);
    el.scrollTop = saved ?? el.scrollHeight;
    lastCount.current = turns.length;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeId, selected]);
  const pendingKey = submission?.payload.client_request_id ?? outgoing ?? "";
  useEffect(() => {
    const el = scroller.current;
    if (!el || !pendingKey) return;
    requestAnimationFrame(() => el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }));
  }, [pendingKey]);
  // "Jump to latest" appears only once the reader has scrolled well away from the end.
  const [awayFromEnd, setAwayFromEnd] = useState(false);
  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    scrollMemory.set(routeId ?? "new", el.scrollTop);
    const away = el.scrollHeight - el.scrollTop - el.clientHeight > 120;
    setAwayFromEnd(prev => (prev === away ? prev : away));
  };
  const jumpToLatest = () => scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });

  // ----- announcements: phases are announced by their own status rows; completion once -----
  const [announce, setAnnounce] = useState("");
  const completedCount = turns.filter(t => t.status === "COMPLETED").length;
  const lastCompleted = useRef(completedCount);
  useEffect(() => {
    if (completedCount > lastCompleted.current && selected) setAnnounce("Answer ready");
    lastCompleted.current = completedCount;
  }, [completedCount, selected]);

  const [sheet, setSheet] = useState<{ turnId: string; citations: readonly CitationItem[]; focus: number | null } | null>(null);
  const openSources = useCallback((turnId: string, citations: readonly CitationItem[], focus: number | null) => setSheet({ turnId, citations, focus }), []);

  const error = state.error && (state.error.conversationId === routeId || !state.error.conversationId) ? state.error : null;
  const lastTurn = turns.at(-1);
  const askAgain = (question: string) => { void send(question); };

  const timeline = useMemo(() => turns.map(turn => {
    if (turn.status === "COMPLETED")
      return <CompletedTurn key={turn.id} id={turn.id} question={turn.question} answer={turn.answer} citations={turn.citations}
        conversationId={routeId} onOpenSources={openSources} wide={wide} current={turn.id === lastTurn?.id}
        onAskAgain={turn.id === lastTurn?.id && !busy && session.canMutate ? () => askAgain(turn.question) : undefined} />;
    if (turn.status === "RUNNING") {
      const live = streaming && submission?.turn?.id === turn.id;
      if (live) return <PendingTurn key={turn.id} question={turn.question} phase={streaming.phase} provisional={streaming.text || undefined} />;
      if (state.executionExpired[turn.id])
        return <NoticeTurn key={turn.id} question={turn.question} tone="caution" title="This answer is taking much longer than expected."
          body="It has probably stopped. Marking it as stopped lets you ask again; nothing else changes."
          actions={<Button size="sm" onClick={() => void controller.interruptExpiredTurn(turn.id)} disabled={!session.canMutate}>Mark as stopped</Button>} />;
      if (unknown && submission?.turn?.id === turn.id)
        return <NoticeTurn key={turn.id} question={turn.question} tone="neutral" title="Stopped waiting."
          body="DriveMind received this question and may still finish the answer. Check to see whether it arrived."
          actions={<Button size="sm" onClick={reconcile}>Check for the answer</Button>} />;
      return <PendingTurn key={turn.id} question={turn.question} phase="timer"
        action={<Button intent="quiet" size="sm" className="h-7 text-meta"
          onClick={state.polling ? () => controller.stopPolling() : () => void controller.pollTurn(turn.id)}>{state.polling ? "Stop checking" : "Check again"}</Button>} />;
    }
    const latest = turn.id === lastTurn?.id && !busy;
    return turn.status === "FAILED"
      ? <NoticeTurn key={turn.id} question={turn.question} tone="fault" title="DriveMind couldn't answer this time."
          body="No documents were changed. Asking again sends the question as a new attempt."
          actions={latest ? <Button size="sm" onClick={() => askAgain(turn.question)} disabled={!session.canMutate}>Ask again</Button> : undefined} />
      : <NoticeTurn key={turn.id} question={turn.question} tone="neutral" title="This answer was stopped before it finished."
          actions={latest ? <Button size="sm" onClick={() => askAgain(turn.question)} disabled={!session.canMutate}>Ask again</Button> : undefined} />;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [turns, streaming, submission, state.executionExpired, state.polling, unknown, wide, routeId, busy, session.canMutate, openSources]);

  let tail: React.ReactNode = null;
  if (outgoing) tail = <PendingTurn question={outgoing} phase="searching" />;
  else if (submission && !submission.turn) {
    const q = submission.payload.question;
    if (waiting) tail = <PendingTurn question={q} phase={streaming?.phase ?? "timer"} provisional={streaming?.text || undefined} />;
    else if (unknown && error?.category === "rate_limited")
      tail = <NoticeTurn question={q} tone="caution" title="You've reached the question limit for now."
        body="Your question is kept while this page stays open. Try again a little later; it will be sent once, exactly as written."
        actions={<Button size="sm" onClick={reconcile} disabled={!session.canMutate}>Try again</Button>} />;
    else if (unknown && error?.category === "request_conflict")
      tail = <NoticeTurn question={q} tone="caution" title="This conversation changed in another tab, so the question wasn't sent."
        body="Reload the page to see the latest messages, then ask again." actions={<Button size="sm" onClick={() => window.location.reload()}>Reload</Button>} />;
    else if (unknown && stopped === submission.payload.client_request_id)
      tail = <NoticeTurn question={q} tone="neutral" title="Stopped waiting."
        body="The answer may still finish. Checking asks DriveMind about this exact question; it is never answered twice."
        actions={<Button size="sm" onClick={reconcile} disabled={!session.canMutate}>Check for the answer</Button>} />;
    else if (unknown)
      tail = <NoticeTurn question={q} tone="caution" title="DriveMind can't confirm this question was received."
        body="It won't be sent again automatically. Checking sends this exact question once more; if it already arrived, it isn't answered twice."
        actions={<Button size="sm" onClick={reconcile} disabled={!session.canMutate}>Check again</Button>} />;
  }

  const isNew = !routeId && !outgoing;
  const showComposer = !notFound && !(isNew && ready === 0);
  const footer = ready === null ? (files.error ? "Couldn't check your documents. You can still ask." : "Answers cite the passages they use.")
    : `${ready.toLocaleString()} ${ready === 1 ? "document is" : "documents are"} ready. Answers cite their sources.`;

  return (
    <PassageCacheContext.Provider value={cache}>
    <CitedFilesContext.Provider value={files.data ?? null}>
      <div className="flex min-h-0 flex-1 flex-col">
        {selected ? <ConversationHeader /> : routeId && !notFound ? <div className="h-14 shrink-0" /> : null}
        <div className="relative flex min-h-0 flex-1 flex-col">
        <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto overscroll-contain" aria-label="Conversation">
          <div className={cn("mx-auto flex min-h-full w-full flex-col px-5 pb-6 md:px-8", isNew ? "max-w-[var(--column-wide)]" : "max-w-[var(--column)] "+"xl:max-w-[calc(var(--column)+var(--margin-col)+2.5rem)]")}>
            {notFound ? <NotFound /> : null}
            {routeId && !selected && !notFound ? <ConversationSkeleton /> : null}
            {selected && state.nextTurnCursor !== null ? <LoadEarlier scroller={scroller} /> : null}
            {isNew ? <NewChatCanvas ready={ready} onInsert={text => composer.current?.insert(text)} /> : null}
            <div className="space-y-12 pt-6">{timeline}{tail}</div>
          </div>
        </div>
        {awayFromEnd && !isNew ? (
          // Same column geometry as the question bar below, so the button sits centred over it.
          <div className="pointer-events-none absolute inset-x-0 bottom-3 z-10">
            <div className="mx-auto w-full max-w-[var(--column)] px-5 md:px-8 xl:grid xl:max-w-[calc(var(--column)+var(--margin-col)+2.5rem)] xl:grid-cols-[minmax(0,1fr)_var(--margin-col)] xl:gap-x-10">
              <div className="flex justify-center">
                <button type="button" onClick={jumpToLatest} aria-label="Jump to the latest message"
                  className="press enter-fade pointer-events-auto grid size-9 place-items-center rounded-full border border-rule bg-sheet text-graphite shadow-[var(--shadow-float)] hover:bg-well hover:text-ink touch-44">
                  <ArrowDown className="size-4" aria-hidden="true" />
                </button>
              </div>
            </div>
          </div>
        ) : null}
        </div>
        {showComposer ? (
          <div className="shrink-0 bg-gradient-to-t from-paper from-70% to-transparent pt-2 safe-bottom">
            <div className={cn("mx-auto w-full px-5 pb-4 md:px-8", isNew ? "max-w-[var(--column-wide)]" : "max-w-[var(--column)] "+"xl:max-w-[calc(var(--column)+var(--margin-col)+2.5rem)]")}>
              <TurnFrame solo={isNew}>
                {state.creation?.uncertain && !outgoing ? (
                  <p role="alert" className="mb-2 text-label text-fault">Couldn&apos;t start the conversation. Your question is still in the box; sending again is safe.</p>
                ) : error?.category === "invalid_request" ? (
                  <p role="alert" className="mb-2 text-label text-fault">Questions can be up to 4,000 characters.</p>
                ) : null}
                <Composer ref={composer} value={draft} onChange={setDraft} onSend={() => void send(draft)} onStop={waiting ? stop : undefined}
                  waiting={waiting} sending={sendingState || !!outgoing || (state.detailLoading && !!routeId)} blocked={blocked} footer={footer} />
              </TurnFrame>
            </div>
          </div>
        ) : null}
        <p className="sr-only" role="status" aria-live="polite">{announce}</p>
        {sheet ? <EvidenceSheet open onOpenChange={open => { if (!open) setSheet(null); }} citations={sheet.citations}
          turnId={sheet.turnId} focus={sheet.focus} conversationId={routeId} /> : null}
      </div>
    </CitedFilesContext.Provider>
    </PassageCacheContext.Provider>
  );
}

function LoadEarlier({ scroller }: { scroller: React.RefObject<HTMLDivElement | null> }) {
  const { state, controller } = useServerConversations();
    return (
      <div className="pt-4">
        <Button intent="quiet" size="sm" loading={state.detailLoading} onClick={async () => {
          const el = scroller.current, before = el?.scrollHeight ?? 0;
          await controller.loadOlderTurns();
          requestAnimationFrame(() => { if (el) el.scrollTop += el.scrollHeight - before; });
        }}>Show earlier messages</Button>
      </div>
    );
  }
function ConversationHeader() {
    const { state, controller } = useServerConversations();
    const session = useApplicationSession();
    const toast = useToast();
    const router = useRouter();
    const [renaming, setRenaming] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [title, setTitle] = useState(state.conversation!.title);
    const [busyAction, setBusyAction] = useState(false);
    const [actionError, setActionError] = useState<string | null>(null);
    const id = state.conversation!.id;
    return (
      <header className="flex h-14 shrink-0 items-center">
        <div className="mx-auto flex w-full max-w-[var(--column)] items-center gap-2 px-5 md:px-8 xl:max-w-[calc(var(--column)+var(--margin-col)+2.5rem)]">
          <h1 className="min-w-0 flex-1 truncate font-serif text-title font-medium" title={state.conversation!.title}>{state.conversation!.title}</h1>
          <Menu label="Conversation options" trigger={<button type="button" className="press grid size-9 place-items-center rounded-control text-graphite hover:bg-well hover:text-ink"><MoreHorizontal className="size-4" aria-hidden="true" /></button>}
            items={[
              { label: "Rename", icon: <Pencil />, disabled: !session.canMutate, onSelect: () => { setTitle(state.conversation!.title); setActionError(null); setRenaming(true); } },
              { label: "Delete", icon: <Trash2 />, danger: true, disabled: !session.canMutate, onSelect: () => { setActionError(null); setDeleting(true); } },
            ]} />
        </div>
        <Dialog open={renaming} onOpenChange={setRenaming} title="Rename conversation">
          <form className="mt-3" onSubmit={async event => {
            event.preventDefault();
            if (!title.trim()) return;
            setBusyAction(true);
            const ok = await controller.rename(id, title.trim().slice(0, 256));
            setBusyAction(false);
            if (ok) { setRenaming(false); toast("Conversation renamed"); }
            else setActionError(controller.getSnapshot().error?.category === "metadata_version_conflict" ? "It was renamed elsewhere. The latest title is shown; edit it again if you like." : "It couldn't be renamed. Try again.");
          }}>
            <TextInput value={title} onChange={e => setTitle(e.target.value)} maxLength={256} aria-label="Title" autoFocus />
            {actionError ? <p role="alert" className="mt-2 text-label text-fault">{actionError}</p> : null}
            <div className="mt-4 flex justify-end gap-2">
              <Button intent="quiet" onClick={() => setRenaming(false)}>Cancel</Button>
              <Button type="submit" intent="primary" loading={busyAction} disabled={!title.trim()}>Save</Button>
            </div>
          </form>
        </Dialog>
        <ConfirmDialog open={deleting} onOpenChange={setDeleting} destructive busy={busyAction} error={actionError}
          title={`Delete “${state.conversation!.title}”?`} confirmLabel="Delete conversation"
          description="This removes its questions and answers from DriveMind. Your Google Drive is not affected."
          onConfirm={async () => {
            setBusyAction(true);
            const ok = await controller.delete(id);
            setBusyAction(false);
            if (ok) { setDeleting(false); toast("Conversation deleted"); router.replace("/chat"); }
            else setActionError("It couldn't be deleted. Nothing was removed; try again.");
          }} />
      </header>
    );
  }

function NotFound() {
  return (
    <div className="pt-[18dvh]">
      <h1 className="font-serif text-display font-medium">This conversation was deleted or doesn&apos;t exist.</h1>
      <p className="mt-3 text-body text-graphite">It may have been removed in another tab. Your other conversations are in the sidebar.</p>
      <Link href="/chat" className="mt-6 inline-flex h-9 items-center rounded-control bg-archive px-3.5 text-label font-medium text-archive-ink hover:bg-archive-hover">Start a new chat</Link>
    </div>
  );
}
function ConversationSkeleton() {
  return (
    <div aria-hidden="true" className="space-y-12 pt-6">
      {[0, 1].map(i => (
        <TurnFrame key={i}>
          <Skeleton className="h-4 w-2/3" />
          <div className="mt-6 space-y-3"><Skeleton className="h-4" /><Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-4/5" /></div>
        </TurnFrame>
      ))}
    </div>
  );
}
