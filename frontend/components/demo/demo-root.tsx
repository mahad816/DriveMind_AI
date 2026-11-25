"use client";
/**
 * Public demo (NEXT_PUBLIC_DEMO_MODE=true): the fictional HarborDesk sample library, no sign-in.
 * Uses only what the backend's demo runtime serves anonymously: GET /index/status (readiness and sample questions),
 * POST /chat, GET /files, GET /files/{id}/content and GET /sources/{chunkId}. Conversations live in this browser
 * (the kept lib/conversations demo storage), exactly as in the previous demo; nothing is written to the server.
 */
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageSquarePlus, Trash2 } from "lucide-react";
import { Wordmark } from "@/components/brand";
import { Button, buttonClass } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/controls";
import { Sheet } from "@/components/ui/dialog";
import { Composer, type ComposerHandle } from "@/components/chat/composer";
import { CompletedTurn, NoticeTurn, PendingTurn, TurnFrame } from "@/components/chat/turn";
import { EvidenceSheet, PassageCache, PassageCacheContext } from "@/components/chat/evidence";
import { FileTypeIcon } from "@/components/library/file-icon";
import { askQuestion } from "@/lib/api/chat";
import { chatErrorMessage, isApiError } from "@/lib/api/errors";
import { listDriveFiles } from "@/lib/api/files";
import { getDriveSyncStatus } from "@/lib/api/indexing";
import { getSourceChunk } from "@/lib/api/sources";
import type { CitationItem, DriveFileRead, DriveSyncStatusResponse, SourceChunkRead } from "@/lib/api/types";
import { CONVERSATIONS_CHANGED_EVENT, notifyConversationsChanged } from "@/lib/conversations/events";
import {
  appendConversationMessage, buildChatRequestForConversation, CONVERSATION_MESSAGES_CHANGED_EVENT, deleteConversationMessages,
  getConversationMessages, recoverInterruptedConversationMessages, releasePendingConversationMessage, saveConversationMessages, updateConversationMessageById,
  type StoredChatMessage,
} from "@/lib/conversations/messages";
import { captureConversationScope } from "@/lib/conversations/scope";
import { createConversation, deleteConversation, getConversation, listConversations, touchConversation } from "@/lib/conversations/storage";
import { conversationTitleFromQuestion } from "@/lib/conversations/title";
import { DEMO_SUGGESTIONS, knowledgeAvailable } from "@/lib/demo";
import { fetchFileTextPreview } from "@/lib/files/preview";
import { fileTypeName } from "@/lib/copy/files";
import { useMediaQuery } from "@/lib/state/use-media";
import { cn } from "@/lib/utils";

const STOPPED = "Stopped before the answer arrived.";

export function DemoRoot() {
  const pathname = usePathname();
  const router = useRouter();
  useEffect(() => { if (pathname === "/" || pathname === "/welcome" || pathname === "/onboarding") router.replace("/chat"); }, [pathname, router]);
  const page = pathname.startsWith("/files") || pathname.startsWith("/index") || pathname.startsWith("/prepare") ? "files"
    : pathname.startsWith("/sources/") ? "source" : pathname.startsWith("/settings") ? "settings" : "chat";
  return (
    <div className="flex h-dvh flex-col bg-paper text-ink">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-control focus:bg-sheet focus:px-3 focus:py-2">Skip to content</a>
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-rule px-4 md:px-6">
        <Link href="/chat" aria-label="DriveMind sample library, home"><Wordmark /></Link>
        <span className="rounded-full border border-rule px-2 py-0.5 text-meta text-graphite">Sample library</span>
        <nav aria-label="Demo" className="ml-auto flex items-center gap-1 text-label">
          <Link href="/chat" aria-current={page === "chat" ? "page" : undefined}
            className={cn("rounded-control px-2.5 py-1.5", page === "chat" ? "bg-well text-ink" : "text-graphite hover:bg-well hover:text-ink")}>Chat</Link>
          <Link href="/files" aria-current={page === "files" ? "page" : undefined}
            className={cn("rounded-control px-2.5 py-1.5", page === "files" ? "bg-well text-ink" : "text-graphite hover:bg-well hover:text-ink")}>Sample documents</Link>
        </nav>
      </header>
      <main id="main" className="min-h-0 flex-1">
        {page === "files" ? <DemoDocuments /> : page === "source" ? <DemoSource /> : page === "settings" ? <DemoNotHere /> : <DemoChat />}
      </main>
    </div>
  );
}

function useDemoStatus() {
  const [status, setStatus] = useState<DriveSyncStatusResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(async () => {
    setFailed(false);
    try { setStatus(await getDriveSyncStatus()); } catch { setFailed(true); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return { status, failed, loading: !status && !failed, ready: knowledgeAvailable(status), reload: load };
}

function useConversationList() {
  // Browser storage is read only after mount, so the server render and the first client render match.
  const [list, setList] = useState<ReturnType<typeof listConversations> | null>(null);
  useEffect(() => {
    const refresh = () => setList(listConversations());
    refresh();
    window.addEventListener(CONVERSATIONS_CHANGED_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => { window.removeEventListener(CONVERSATIONS_CHANGED_EVENT, refresh); window.removeEventListener("storage", refresh); };
  }, []);
  return list;
}

function DemoChat() {
  const params = useParams<{ id?: string }>();
  const routeId = typeof params.id === "string" ? params.id : null;
  const router = useRouter();
  const { status, failed, loading, ready, reload } = useDemoStatus();
  const loaded = useConversationList();
  const conversations = loaded ?? [];
  const conversation = routeId ? conversations.find(c => c.id === routeId) ?? null : null;
  const [messages, setMessages] = useState<StoredChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [inFlight, setInFlight] = useState<{ conversationId: string; messageId: string; controller: AbortController } | null>(null);
  const [sheet, setSheet] = useState<{ id: string; citations: CitationItem[]; focus: number | null } | null>(null);
  const [cache] = useState(() => new PassageCache());
  const composer = useRef<ComposerHandle>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const wide = useMediaQuery("(min-width: 1280px)");

  // A request belongs to the conversation it was sent from; switching conversations never shows it elsewhere.
  useEffect(() => {
    if (!routeId) { setMessages([]); return; }
    const load = () => setMessages(getConversationMessages(routeId));
    setMessages(recoverInterruptedConversationMessages(routeId));
    const onChange = (event: Event) => { const id = (event as CustomEvent<string>).detail; if (!id || id === routeId) load(); };
    window.addEventListener(CONVERSATION_MESSAGES_CHANGED_EVENT, onChange);
    window.addEventListener("storage", load);
    return () => { window.removeEventListener(CONVERSATION_MESSAGES_CHANGED_EVENT, onChange); window.removeEventListener("storage", load); };
  }, [routeId]);
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [messages.length, routeId]);

  const send = async (text: string, retryOf?: StoredChatMessage) => {
    const question = text.trim();
    if (!question || inFlight || !ready) return;
    const scope = captureConversationScope();
    let conversationId = routeId && getConversation(routeId, scope) ? routeId : null;
    try {
      if (!conversationId) {
        conversationId = createConversation(conversationTitleFromQuestion(question), scope).id;
        notifyConversationsChanged();
        router.replace(`/chat/${conversationId}`, { scroll: false });
      }
      // "Ask again" replaces only the failed turn; every other turn of the conversation is kept.
      if (retryOf) saveConversationMessages(conversationId, getConversationMessages(conversationId, scope).filter(m => m.id !== retryOf.id), scope);
      const messageId = crypto.randomUUID();
      const request = buildChatRequestForConversation(conversationId, question, undefined, scope);
      appendConversationMessage(conversationId, { id: messageId, question, status: "pending", answer: null, citations: [], retrievalCount: 0, error: null }, scope);
      touchConversation(conversationId, scope); notifyConversationsChanged();
      setDraft("");
      const controller = new AbortController();
      setInFlight({ conversationId, messageId, controller });
      try {
        const response = await askQuestion(request, controller.signal);
        updateConversationMessageById(conversationId, messageId, m => ({ ...m, status: "done", answer: response.answer, citations: response.citations, retrievalCount: response.retrieval_count, error: null }), scope);
      } catch (error) {
        const stopped = controller.signal.aborted;
        updateConversationMessageById(conversationId, messageId, m => ({ ...m, status: "error", error: stopped ? STOPPED : chatErrorMessage(error) }), scope);
      } finally {
        releasePendingConversationMessage(conversationId, messageId, scope);
        setInFlight(null);
      }
    } catch {
      setInFlight(null);
    }
  };
  const remove = (id: string) => {
    deleteConversationMessages(id); deleteConversation(id); notifyConversationsChanged();
    if (id === routeId) router.replace("/chat");
  };

  const waiting = !!inFlight && inFlight.conversationId === routeId;
  const busyElsewhere = !!inFlight && inFlight.conversationId !== routeId;
  const blocked = loading ? null : !ready ? "The sample library isn't available right now." : busyElsewhere ? "Another sample question is still being answered." : null;
  const suggestions = status?.demo_questions?.length ? status.demo_questions : DEMO_SUGGESTIONS;
  const isNew = !routeId || messages.length === 0;
  const notFound = !!routeId && loaded !== null && !conversation && !inFlight;

  return (
    <PassageCacheContext.Provider value={cache}>
      <div className="flex h-full">
        <aside aria-label="Sample conversations" className="hidden w-64 shrink-0 flex-col border-r border-rule md:flex">
          <div className="p-3"><Link href="/chat" className={buttonClass("secondary", "md", "w-full justify-start")}><MessageSquarePlus className="size-4" aria-hidden="true" />New chat</Link></div>
          <p className="px-5 pb-1 text-meta font-medium text-faint">Kept in this browser only</p>
          <ul className="min-h-0 flex-1 space-y-px overflow-y-auto px-3 pb-4">
            {conversations.map(c => (
              <li key={c.id} className="group relative">
                <Link href={`/chat/${c.id}`} aria-current={c.id === routeId ? "page" : undefined}
                  className={cn("flex h-9 items-center rounded-control pl-2.5 pr-9 text-label", c.id === routeId ? "bg-well font-medium" : "text-graphite hover:bg-well/70 hover:text-ink")}>
                  <span className="truncate">{c.title}</span>
                </Link>
                <button type="button" aria-label={`Delete ${c.title}`} onClick={() => remove(c.id)} disabled={inFlight?.conversationId === c.id}
                  className="press absolute right-1 top-1/2 grid size-7 -translate-y-1/2 place-items-center rounded-control text-graphite opacity-0 hover:bg-sheet hover:text-ink focus-visible:opacity-100 group-hover:opacity-100 disabled:hidden [@media(pointer:coarse)]:opacity-100">
                  <Trash2 className="size-3.5" aria-hidden="true" />
                </button>
              </li>
            ))}
            {loaded && conversations.length === 0 ? <li className="px-2.5 pt-2 text-label text-faint">No conversations yet.</li> : null}
          </ul>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto" aria-label="Conversation">
            <div className="mx-auto flex min-h-full w-full max-w-[var(--column)] flex-col px-5 pb-6 md:px-8 xl:max-w-[calc(var(--column)+var(--margin-col)+2.5rem)]">
              {notFound ? (
                <div className="pt-16"><h1 className="font-serif text-title font-medium">This conversation isn&apos;t in this browser.</h1>
                  <p className="mt-2 text-body text-graphite">Sample conversations are kept only in the browser that started them.</p>
                  <Link href="/chat" className={buttonClass("primary", "md", "mt-5")}>Start a new chat</Link></div>
              ) : isNew ? (
                <TurnFrame>
                  <div className="pt-[14dvh]">
                    <h1 className="font-serif text-display font-medium">Ask the sample library.</h1>
                    <p className="mt-3 text-body text-graphite">
                      This demo answers from seven fictional documents about HarborDesk, a made-up bicycle-shop support inbox, and cites the passages it used. Nothing here is real customer data.
                    </p>
                    {loading ? <div className="mt-6 flex gap-2" aria-hidden="true"><Skeleton className="h-8 w-48" /><Skeleton className="h-8 w-40" /></div>
                      : failed || !ready ? (
                        <div role="status" className="mt-6 rounded-panel border border-caution/30 bg-caution-wash px-4 py-3 text-label">
                          The sample library is temporarily unavailable. Please try again shortly.
                          <Button size="sm" intent="quiet" className="ml-2" onClick={() => void reload()}>Try again</Button>
                        </div>
                      ) : (
                        <div className="mt-6">
                          <p className="text-meta text-faint">Try one of these</p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {suggestions.map(q => (
                              <button key={q} type="button" onClick={() => void send(q)} disabled={!!inFlight}
                                className="press rounded-full border border-rule bg-sheet px-3 py-1.5 text-left text-label hover:border-edge/60 disabled:opacity-45">{q}</button>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>
                </TurnFrame>
              ) : null}
              <div className="space-y-12 pt-6">
                {messages.map(m => m.status === "done"
                  ? <CompletedTurn key={m.id} id={m.id} question={m.question} answer={m.answer ?? ""} citations={m.citations} conversationId={null} wide={wide}
                      onOpenSources={(id, citations, focus) => setSheet({ id, citations: [...citations], focus })} />
                  : m.status === "pending"
                    ? <PendingTurn key={m.id} question={m.question} phase="timer" />
                    : <NoticeTurn key={m.id} question={m.question} tone={m.error === STOPPED ? "neutral" : "caution"}
                        title={m.error === STOPPED ? "Stopped." : "This sample question wasn't answered."}
                        body={m.error === STOPPED ? "You stopped waiting, so no answer is shown. Asking again sends the question again." : m.error ?? "Please try again shortly."}
                        actions={<Button size="sm" disabled={!!inFlight || !ready} onClick={() => void send(m.question, m)}>Ask again</Button>} />)}
              </div>
            </div>
          </div>
          {!notFound ? (
            <div className="shrink-0 bg-gradient-to-t from-paper from-70% to-transparent pt-2 safe-bottom">
              <div className="mx-auto w-full max-w-[var(--column)] px-5 pb-4 md:px-8 xl:max-w-[calc(var(--column)+var(--margin-col)+2.5rem)]">
                <TurnFrame>
                  <Composer ref={composer} value={draft} onChange={setDraft} onSend={() => void send(draft)}
                    onStop={waiting ? () => inFlight?.controller.abort() : undefined} waiting={waiting} sending={false} blocked={blocked}
                    placeholder="Ask about the sample documents…"
                    footer={<span>Sample answers cite fictional documents. Conversations stay in this browser.</span>} />
                </TurnFrame>
              </div>
            </div>
          ) : null}
        </div>
      </div>
      {sheet ? <EvidenceSheet open onOpenChange={open => { if (!open) setSheet(null); }} citations={sheet.citations} turnId={sheet.id} focus={sheet.focus} conversationId={null} /> : null}
    </PassageCacheContext.Provider>
  );
}

function DemoDocuments() {
  const [files, setFiles] = useState<DriveFileRead[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<DriveFileRead | null>(null);
  const [text, setText] = useState<{ id: string; value: string | null } | null>(null);
  const load = useCallback(async () => {
    setFailed(false);
    try { setFiles((await listDriveFiles()).files); } catch { setFailed(true); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!open) return;
    let live = true; setText(null);
    void fetchFileTextPreview(open.id, open.mime_type).then(value => { if (live) setText({ id: open.id, value }); });
    return () => { live = false; };
  }, [open]);
  const sorted = useMemo(() => [...(files ?? [])].sort((a, b) => a.name.localeCompare(b.name)), [files]);
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-5 pb-16 pt-8 md:px-8 md:pt-10">
        <h1 className="font-serif text-display font-medium">Sample documents</h1>
        <p className="mt-2 text-body text-graphite">Browse seven fictional HarborDesk sample documents and inspect their text. These are the only documents the demo answers from.</p>
        {failed ? (
          <div role="alert" className="mt-8"><p className="text-body">The sample documents couldn&apos;t load.</p><Button className="mt-3" onClick={() => void load()}>Try again</Button></div>
        ) : !files ? (
          <div className="mt-8 space-y-3" aria-hidden="true">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-10" />)}</div>
        ) : (
          <ul className="mt-8 divide-y divide-rule border-y border-rule">
            {sorted.map(f => (
              <li key={f.id}>
                <button type="button" onClick={() => setOpen(f)} className="flex w-full items-center gap-3 px-1 py-3 text-left hover:bg-sheet">
                  <FileTypeIcon mime={f.mime_type} />
                  <span className="min-w-0 flex-1"><span className="block truncate text-body">{f.name}</span><span className="block text-meta text-faint">{fileTypeName(f.mime_type)}</span></span>
                  <span className="text-label text-archive-text">Read</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Sheet open={!!open} onOpenChange={next => { if (!next) setOpen(null); }} side="right" title={open?.name ?? ""} description={open ? `${fileTypeName(open.mime_type)}, fictional sample` : undefined}>
        {!text ? <div className="space-y-2" aria-hidden="true"><Skeleton className="h-3.5" /><Skeleton className="h-3.5 w-5/6" /><Skeleton className="h-3.5 w-2/3" /></div>
          : text.value ? <p className="whitespace-pre-wrap font-serif text-passage">{text.value}</p>
          : <p className="text-label text-graphite">This document&apos;s text couldn&apos;t load. Please try again shortly.</p>}
      </Sheet>
    </div>
  );
}

function DemoSource() {
  const { chunkId } = useParams<{ chunkId: string }>();
  const [result, setResult] = useState<{ status: "loading" | "ready" | "gone" | "error"; data?: SourceChunkRead }>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true; setResult({ status: "loading" });
    getSourceChunk(chunkId).then(data => { if (live) setResult({ status: "ready", data }); },
      error => { if (live) setResult({ status: isApiError(error) && (error.status === 404 || error.status === 403) ? "gone" : "error" }); });
    return () => { live = false; };
  }, [chunkId, attempt]);
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[var(--column)] px-5 pb-20 pt-6 md:px-8 md:pt-10">
        <Link href="/chat" className="text-label text-graphite hover:text-ink">Back to chat</Link>
        {result.status === "loading" ? <div className="mt-8 space-y-4" aria-hidden="true"><Skeleton className="h-7 w-2/3" /><Skeleton className="h-4" /><Skeleton className="h-4 w-4/5" /></div>
          : result.status === "gone" ? <h1 className="mt-8 font-serif text-display font-medium">This passage is no longer available.</h1>
          : result.status === "error" ? <div className="mt-8" role="alert"><h1 className="font-serif text-display font-medium">The passage couldn&apos;t load.</h1><Button className="mt-5" onClick={() => setAttempt(a => a + 1)}>Try again</Button></div>
          : result.data ? (
            <article className="mt-8">
              <h1 className="font-serif text-display font-medium [overflow-wrap:anywhere]">{result.data.filename}</h1>
              <p className="mt-2 text-label text-graphite">{fileTypeName(result.data.mime_type)}, passage {result.data.chunk_index + 1}, fictional sample</p>
              <blockquote className="mt-8 whitespace-pre-wrap border-l-2 border-highlight-edge pl-5 font-serif text-prose">{result.data.text}</blockquote>
              <p className="mt-4 text-meta text-faint">This is one passage from the sample document, not the whole document.</p>
            </article>
          ) : null}
      </div>
    </div>
  );
}

function DemoNotHere() {
  return (
    <div className="mx-auto max-w-md px-6 pt-20">
      <h1 className="font-serif text-title font-medium">Settings aren&apos;t part of the demo.</h1>
      <p className="mt-2 text-body text-graphite">The sample library needs no account. The full app connects your own Google Drive with read-only access.</p>
      <Link href="/chat" className={buttonClass("primary", "md", "mt-5")}>Back to the sample chat</Link>
    </div>
  );
}
