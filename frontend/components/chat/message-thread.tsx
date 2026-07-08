"use client";

import type { RefObject } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { AssistantMessage } from "@/components/chat/assistant-message";
import { ThinkingIndicator } from "@/components/chat/thinking-indicator";
import { UserMessage } from "@/components/chat/user-message";
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
  endRef: RefObject<HTMLDivElement | null>;
};

export function MessageThread({ messages, onSourceSelect, endRef }: MessageThreadProps) {
  return (
    <div className="space-y-8 pb-4">
      {messages.map((message) => (
        <section key={message.id} className="space-y-4" aria-label="Conversation turn">
          <UserMessage content={message.question} />

          {message.status === "loading" ? <ThinkingIndicator /> : null}

          {message.status === "error" ? (
            <Alert variant="destructive">
              <AlertTitle>Couldn&apos;t get an answer</AlertTitle>
              <AlertDescription>{message.error}</AlertDescription>
            </Alert>
          ) : null}

          {message.status === "done" ? (
            <div aria-live="polite" aria-atomic="true">
              <AssistantMessage response={message.response} onSourceSelect={onSourceSelect} />
            </div>
          ) : null}
        </section>
      ))}
      <div ref={endRef} />
    </div>
  );
}
