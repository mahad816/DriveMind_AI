"use client";

import { useState } from "react";
import { Check, Copy, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { copyTextToClipboard } from "@/lib/chat/clipboard";
import { chatCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast-provider";

type MessageActionBarProps = {
  answer?: string;
  sourceLabel?: string;
  onRegenerate?: () => void;
  isLoading?: boolean;
  className?: string;
};

export function MessageActionBar({
  answer,
  sourceLabel,
  onRegenerate,
  isLoading = false,
  className,
}: MessageActionBarProps) {
  const { pushToast } = useToast();
  const [copied, setCopied] = useState(false);

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
      {sourceLabel ? (
        <p className="text-xs text-muted-foreground">{sourceLabel}</p>
      ) : (
        <span />
      )}

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
