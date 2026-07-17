"use client";

import { useState } from "react";
import { Check, Copy, FileText, RefreshCw } from "lucide-react";

import { uniqueCitationsByFilename } from "@/components/chat/source-pills";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast-provider";
import type { CitationItem } from "@/lib/api/types";
import { copyTextToClipboard } from "@/lib/chat/clipboard";
import { formatSourceCount } from "@/lib/chat/source-label";
import { chatCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";

type MessageActionBarProps = {
  answer?: string;
  citations?: CitationItem[];
  retrievalCount?: number;
  onSourceSelect?: (citation: CitationItem) => void;
  onRegenerate?: () => void;
  isLoading?: boolean;
  className?: string;
};

export function MessageActionBar({
  answer,
  citations = [],
  retrievalCount = 0,
  onSourceSelect,
  onRegenerate,
  isLoading = false,
  className,
}: MessageActionBarProps) {
  const { pushToast } = useToast();
  const [copied, setCopied] = useState(false);

  const uniqueSources = uniqueCitationsByFilename(citations);
  const sourceLabel = formatSourceCount(retrievalCount, citations);
  const canOpenSources = uniqueSources.length > 0 && Boolean(onSourceSelect);

  const handleCopy = async () => {
    if (!answer) return;
    const ok = await copyTextToClipboard(answer);
    if (ok) {
      setCopied(true);
      pushToast({ title: chatCopy.copiedToast, variant: "success", durationMs: 2_000 });
      window.setTimeout(() => setCopied(false), 2_000);
      return;
    }
    pushToast({ title: chatCopy.copyFailedToast, variant: "error" });
  };

  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-3",
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        {canOpenSources ? (
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <button
              type="button"
              onClick={() => onSourceSelect?.(uniqueSources[0])}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-primary transition-colors hover:text-primary/80 hover:underline underline-offset-2"
              title="View source documents"
            >
              <FileText className="size-3.5 shrink-0" aria-hidden="true" />
              {sourceLabel}
            </button>

            {uniqueSources.map((citation) => (
              <button
                key={citation.chunk_id}
                type="button"
                onClick={() => onSourceSelect?.(citation)}
                className="max-w-[14rem] truncate rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                title={`Open ${citation.filename}`}
              >
                {citation.filename}
              </button>
            ))}
          </div>
        ) : sourceLabel ? (
          <p className="text-xs text-muted-foreground">{sourceLabel}</p>
        ) : (
          <span />
        )}
      </div>

      <div className="flex items-center gap-0.5 opacity-80 transition-opacity group-hover/answer:opacity-100">
        {answer ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => void handleCopy()}
            disabled={isLoading}
            title={copied ? chatCopy.copied : chatCopy.copyAnswer}
          >
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            {copied ? chatCopy.copied : chatCopy.copyAnswer}
          </Button>
        ) : null}

        {onRegenerate ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={onRegenerate}
            disabled={isLoading}
            title={chatCopy.regenerate}
          >
            <RefreshCw className="size-3.5" />
            {chatCopy.regenerate}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
