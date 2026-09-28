"use client";

import { AnswerMarkdown } from "@/components/chat/answer-markdown";
import { FollowUpChips } from "@/components/chat/follow-up-chips";
import { MessageActionBar } from "@/components/chat/message-action-bar";
import type { ChatResponse, CitationItem } from "@/lib/api/types";

type AssistantMessageProps = {
  response: ChatResponse;
  onSourceSelect: (citation: CitationItem, citations: CitationItem[]) => void;
  onRegenerate?: () => void;
  onFollowUp?: (question: string) => void;
  followUpSuggestions?: string[];
  isLatest?: boolean;
  isLoading?: boolean;
};

export function AssistantMessage({
  response,
  onSourceSelect,
  onRegenerate,
  onFollowUp,
  followUpSuggestions = [],
  isLatest = false,
  isLoading = false,
}: AssistantMessageProps) {
  return (
    <article className="group/answer space-y-4" aria-label="Assistant answer">
      <AnswerMarkdown
        content={response.answer}
        citations={response.citations}
        onSourceSelect={onSourceSelect}
      />

      <MessageActionBar
        answer={response.answer}
        citations={response.citations}
        retrievalCount={response.retrieval_count}
        onSourceSelect={onSourceSelect}
        onRegenerate={onRegenerate}
        isLoading={isLoading}
      />

      {isLatest && onFollowUp && followUpSuggestions.length > 0 ? (
        <FollowUpChips
          suggestions={followUpSuggestions}
          onSelect={onFollowUp}
          disabled={isLoading}
        />
      ) : null}
    </article>
  );
}
