"use client";

import type { RefObject } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { AssistantMessage } from "@/components/chat/assistant-message";
import { ThinkingIndicator } from "@/components/chat/thinking-indicator";
import { UserMessage } from "@/components/chat/user-message";
import { buildFollowUpSuggestions } from "@/lib/chat/follow-ups";
import { chatCopy } from "@/lib/user-language";
import type { ChatResponse, CitationItem } from "@/lib/api/types";

export type ChatTurn =
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

type MessageThreadProps = {
  messages: ChatTurn[];
  onSourceSelect: (citation: CitationItem) => void;
  onRetry: (messageId: string, question: string) => void;
  onRegenerate: (messageId: string, question: string) => void;
  onFollowUp: (question: string) => void;
  isSending: boolean;
  endRef: RefObject<HTMLDivElement | null>;
};

export function MessageThread({
  messages,
  onSourceSelect,
  onRetry,
  onRegenerate,
  onFollowUp,
  isSending,
  endRef,
}: MessageThreadProps) {
  const lastMessageId = messages.at(-1)?.id;

  return (
    <div className="space-y-10 pb-4">
      {messages.map((message) => {
        const isLatest = message.id === lastMessageId;

        return (
          <section key={message.id} className="space-y-4" aria-label="Conversation turn">
            <UserMessage content={message.question} />

            {message.status === "loading" ? <ThinkingIndicator /> : null}

            {message.status === "error" ? (
              <div className="space-y-3">
                <Alert variant="destructive">
                  <AlertTitle>{chatCopy.errorTitle}</AlertTitle>
                  <AlertDescription>{message.error}</AlertDescription>
                </Alert>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={isSending}
                    onClick={() => onRetry(message.id, message.question)}
                  >
                    {chatCopy.retry}
                  </Button>
                </div>
              </div>
            ) : null}

            {message.status === "done" ? (
              <div aria-live="polite" aria-atomic="true">
                <AssistantMessage
                  response={message.response}
                  onSourceSelect={onSourceSelect}
                  onRegenerate={
                    isLatest ? () => onRegenerate(message.id, message.question) : undefined
                  }
                  onFollowUp={isLatest ? onFollowUp : undefined}
                  followUpSuggestions={
                    isLatest
                      ? buildFollowUpSuggestions(
                          message.question,
                          message.response.answer,
                          message.response.citations,
                        )
                      : []
                  }
                  isLatest={isLatest}
                  isLoading={isSending}
                />
              </div>
            ) : null}
          </section>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
