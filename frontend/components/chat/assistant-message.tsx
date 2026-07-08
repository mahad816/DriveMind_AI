"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { SourcePills } from "@/components/chat/source-pills";
import type { ChatResponse, CitationItem } from "@/lib/api/types";

type AssistantMessageProps = {
  response: ChatResponse;
  onSourceSelect: (citation: CitationItem) => void;
};

export function AssistantMessage({ response, onSourceSelect }: AssistantMessageProps) {
  return (
    <article className="space-y-4" aria-label="Assistant answer">
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
                  className="underline underline-offset-4 hover:text-foreground"
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
                    className="rounded bg-muted px-1 py-0.5 font-mono text-sm"
                    {...rest}
                  >
                    {children}
                  </code>
                );
              }
              return (
                <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-sm">
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
              return <ul className="mb-4 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>;
            },
            ol({ children }) {
              return <ol className="mb-4 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>;
            },
          }}
        >
          {response.answer}
        </ReactMarkdown>
      </div>

      <SourcePills citations={response.citations} onSelect={onSourceSelect} />
    </article>
  );
}
