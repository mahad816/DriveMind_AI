"use client";

import { useCallback } from "react";
import { Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

type ChatComposerProps = {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  isLoading: boolean;
  placeholder?: string;
  className?: string;
};

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  isLoading,
  placeholder = "Ask a question about your Drive…",
  className,
}: ChatComposerProps) {
  const canSubmit = !disabled && !isLoading && value.trim().length > 0;

  const submit = useCallback(() => {
    if (!canSubmit) return;
    onSubmit();
  }, [canSubmit, onSubmit]);

  return (
    <div className={cn("space-y-3", className)}>
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        rows={3}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />

      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Tip: press <span className="font-mono">Enter</span> to send, <span className="font-mono">Shift+Enter</span> for newline.
        </p>

        <Button type="button" onClick={submit} disabled={!canSubmit}>
          <Send className="mr-2 size-4" />
          {isLoading ? "Sending…" : "Send"}
        </Button>
      </div>
    </div>
  );
}

