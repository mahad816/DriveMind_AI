"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { useConnectionStatus } from "@/lib/hooks/use-connection-status";
import { isApiError } from "@/lib/api/errors";
import { askQuestion } from "@/lib/api/chat";
import type { ChatResponse } from "@/lib/api/types";

import { ChatComposer } from "@/components/chat/chat-composer";
import { ChatAnswer } from "@/components/chat/chat-answer";

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

const exampleQuestions = [
  "What does tensile strength mean?",
  "Summarize everything about PTCL in my Drive.",
  "Find my latest resume in Drive.",
] as const;

function createMessageId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function ChatInterface() {
  const { data: connection, error: connectionError, refetch } = useConnectionStatus({
    pollIntervalMs: 30_000,
  });

  useEffect(() => {
    // A quick one-time refresh makes the UI respond faster after OAuth redirects.
    void refetch();
  }, [refetch]);

  const isConnected = connection?.connected ?? false;

  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessageState[]>([]);
  const [isSending, setIsSending] = useState(false);

  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  const canSend = useMemo(() => {
    if (!isConnected) return false;
    if (isSending) return false;
    return question.trim().length > 0;
  }, [isConnected, isSending, question]);

  const send = useCallback(async () => {
    if (!canSend) return;

    const normalized = question.trim();
    const id = createMessageId();

    setQuestion("");
    setIsSending(true);

    setMessages((prev) => [
      ...prev,
      { id, question: normalized, status: "loading", error: null },
    ]);

    try {
      const response = await askQuestion({ question: normalized });
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id
            ? { id, question: m.question, status: "done", error: null, response }
            : m,
        ),
      );
    } catch (err) {
      const message = isApiError(err) ? err.detail : err instanceof Error ? err.message : "Request failed";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id
            ? { id, question: m.question, status: "error", error: message, response: null }
            : m,
        ),
      );
    } finally {
      setIsSending(false);
    }
  }, [canSend, question]);

  const exampleChips = (
    <div className="flex flex-wrap gap-2">
      {exampleQuestions.map((q) => (
        <Button
          key={q}
          type="button"
          size="sm"
          variant="outline"
          disabled={!isConnected || isSending}
          onClick={() => setQuestion(q)}
        >
          {q}
        </Button>
      ))}
    </div>
  );

  return (
    <div className="space-y-4">
      {connectionError ? (
        <Alert variant="destructive">
          <AlertTitle>Connection status error</AlertTitle>
          <AlertDescription>{connectionError}</AlertDescription>
        </Alert>
      ) : null}

      {!isConnected ? (
        <Alert className="border-amber-500/30 bg-amber-50 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100">
          <AlertTitle>Google Drive not connected</AlertTitle>
          <AlertDescription>
            Connect Drive in <a className="underline" href="/settings">Settings</a> and sync metadata in Index.
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Chat</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {messages.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Ask a question and get a grounded answer with clickable sources.
              </p>
              {exampleChips}
            </div>
          ) : null}

          <div className="space-y-6">
            {messages.map((m) => {
              if (m.status === "loading") {
                return (
                  <div key={m.id} className="space-y-3">
                    <div className="rounded-lg bg-muted px-3 py-2 text-sm">
                      <span className="font-medium">You:</span> {m.question}
                    </div>
                    <div className="space-y-2">
                      <Skeleton className="h-5 w-2/3" />
                      <Skeleton className="h-5 w-full" />
                      <Skeleton className="h-5 w-5/6" />
                    </div>
                  </div>
                );
              }

              if (m.status === "error") {
                return (
                  <div key={m.id} className="space-y-3">
                    <div className="rounded-lg bg-muted px-3 py-2 text-sm">
                      <span className="font-medium">You:</span> {m.question}
                    </div>
                    <Alert variant="destructive">
                      <AlertTitle>Answer failed</AlertTitle>
                      <AlertDescription>{m.error}</AlertDescription>
                    </Alert>
                  </div>
                );
              }

              return (
                <div key={m.id} className="space-y-3">
                  <div className="rounded-lg bg-muted px-3 py-2 text-sm">
                    <span className="font-medium">You:</span> {m.question}
                  </div>
                  <div>
                    <ChatAnswer response={m.response} />
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="text-xs font-normal">
                        retrieval_count: {m.response.retrieval_count}
                      </Badge>
                      {m.response.message ? (
                        <Badge variant="outline" className="text-xs font-normal">
                          {m.response.message}
                        </Badge>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
            <div ref={endRef} />
          </div>

          <ChatComposer
            value={question}
            onChange={setQuestion}
            onSubmit={() => void send()}
            disabled={!isConnected}
            isLoading={isSending}
          />
        </CardContent>
      </Card>
    </div>
  );
}

