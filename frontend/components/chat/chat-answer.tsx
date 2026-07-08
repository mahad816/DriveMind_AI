"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CitationCard } from "@/components/chat/citation-card";
import type { ChatResponse } from "@/lib/api/types";

export function ChatAnswer({ response }: { response: ChatResponse }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Answer</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="text-sm leading-6 text-foreground">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a({ ...props }) {
                  const href = props.href ?? "";
                  const isExternal =
                    typeof href === "string" && href.startsWith("http");

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
                        className="rounded bg-muted px-1 py-0.5 font-mono text-xs"
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
              }}
            >
              {response.answer}
            </ReactMarkdown>
          </div>

          {response.citations.length > 0 ? (
            <div className="space-y-3">
              <p className="text-xs font-medium text-muted-foreground">Sources</p>
              <div className="grid gap-3 md:grid-cols-2">
                {response.citations.map((citation, idx) => (
                  <CitationCard key={citation.chunk_id} citation={citation} index={idx + 1} />
                ))}
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

