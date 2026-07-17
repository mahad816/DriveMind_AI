"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { FollowUpChips } from "@/components/chat/follow-up-chips";
import { MessageActionBar } from "@/components/chat/message-action-bar";
import type { ChatResponse, CitationItem } from "@/lib/api/types";

type AssistantMessageProps = {
  response: ChatResponse;
  onSourceSelect: (citation: CitationItem) => void;
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
      <div className="text-body-lg leading-relaxed text-foreground">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a({ ...props }) {
              const href = props.href ?? "";
              const isExternal = typeof href === "string" && href.startsWith("http");

              return (
                <a
                  href={href}
                  target={isExternal ? "_blank" : undefined}
                  rel={isExternal ? "noreferrer" : undefined}
                  className="font-medium text-primary underline underline-offset-4 hover:text-primary/80"
                  {...props}
                />
              );
            },
            code(props) {
              const { children, className, ...rest } = props;
              const inline = Boolean((props as { inline?: boolean }).inline);

              if (inline) {
                return (
                  <code
                    className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.9em] text-foreground"
                    {...rest}
                  >
                    {children}
                  </code>
                );
              }
              return (
                <pre className="overflow-x-auto rounded-xl border border-border bg-muted/60 p-4 text-sm">
                  <code className={className} {...rest}>
                    {children}
                  </code>
                </pre>
              );
            },
            p({ children }) {
              return <p className="mb-4 last:mb-0">{children}</p>;
            },
            ul({ children }) {
              return <ul className="mb-4 list-disc space-y-1.5 pl-5 last:mb-0">{children}</ul>;
            },
            ol({ children }) {
              return <ol className="mb-4 list-decimal space-y-1.5 pl-5 last:mb-0">{children}</ol>;
            },
            h1({ children }) {
              return <h3 className="mb-3 text-lg font-semibold">{children}</h3>;
            },
            h2({ children }) {
              return <h4 className="mb-2 text-base font-semibold">{children}</h4>;
            },
            blockquote({ children }) {
              return (
                <blockquote className="mb-4 border-l-2 border-primary/30 pl-4 text-muted-foreground last:mb-0">
                  {children}
                </blockquote>
              );
            },
          }}
        >
          {response.answer}
        </ReactMarkdown>
      </div>

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
