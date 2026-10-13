"use client";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { askQuestion } from "@/lib/api/chat";
import { chatErrorMessage } from "@/lib/api/errors";
import { sessionRevision, sessionOwner, notifySessionInvalid } from "@/lib/api/session-events";
import { MessageThread, type ChatTurn } from "@/components/chat/message-thread";
import { ComposerDock } from "@/components/chat/composer-dock";
import { SourcePanel } from "@/components/chat/source-panel";
import type { CitationItem } from "@/lib/api/types";
/** Temporary normal-mode chat: no legacy conversation storage or supplied history. */
export function SessionChat() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const [citation, setCitation] = useState<CitationItem | null>(null);
  const live = useRef(true);
  const busy = useRef(false);
  const params = useSearchParams();
  useEffect(() => { setQuestion(params.get("ask") ?? ""); }, [params]);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  async function send(value = question) {
    if (busy.current || !value.trim())
      return;
    busy.current = true;
    const revision = sessionRevision();
    const owner = sessionOwner();
    const id = crypto.randomUUID();
    setSending(true);
    setQuestion("");
    setMessages(m => [...m, { id, question: value, status: "loading", error: null }]);
    try {
      const response = await askQuestion({ question: value });
      if (revision === sessionRevision() && response.user_id !== owner) {
        notifySessionInvalid();
        return;
      }
      if (live.current && revision === sessionRevision())
        setMessages(m => m.map(t => t.id === id ? { id, question: value, status: "done", error: null, response } : t));
    }
    catch (err) {
      if (live.current && revision === sessionRevision())
        setMessages(m => m.map(t => t.id === id ? { id, question: value, status: "error", error: chatErrorMessage(err), response: null } : t));
    }
    finally {
      if (live.current && revision === sessionRevision()) {
        busy.current = false;
        setSending(false);
      }
    }
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col p-6">
      <p className="text-sm text-muted-foreground">
        This chat is kept in memory only. Saved conversations and history follow-ups
        will return with account-scoped storage.
      </p>
      <div className="flex-1 overflow-y-auto">
        <MessageThread
          messages={messages}
          onSourceSelect={setCitation}
          onRetry={(_id, text) => void send(text)}
          onRegenerate={(_id, text) => void send(text)}
          onFollowUp={text => void send(text)}
          isSending={sending}
        />
      </div>
      <ComposerDock
        value={question}
        onChange={setQuestion}
        onSubmit={() => void send()}
        disabled={false}
        isLoading={sending}
      />
      <SourcePanel
        citation={citation}
        open={!!citation}
        onOpenChange={open => { if (!open) setCitation(null); }}
      />
    </div>
  );
}
