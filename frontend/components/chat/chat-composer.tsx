"use client";

import { useCallback, useEffect, useRef } from "react";
import { ArrowUp } from "lucide-react";

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

const MIN_HEIGHT_PX = 52;
const MAX_HEIGHT_PX = 200;

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled,
  isLoading,
  placeholder = "Message DriveMind…",
  className,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canSubmit = !disabled && !isLoading && value.trim().length > 0;

  const resizeTextarea = useCallback(() => {
    const element = textareaRef.current;
    if (!element) return;

    element.style.height = "auto";
    const nextHeight = Math.min(Math.max(element.scrollHeight, MIN_HEIGHT_PX), MAX_HEIGHT_PX);
    element.style.height = `${nextHeight}px`;
  }, []);

  useEffect(() => {
    resizeTextarea();
  }, [resizeTextarea, value]);

  const submit = useCallback(() => {
    if (!canSubmit) return;
    onSubmit();
  }, [canSubmit, onSubmit]);

  return (
    <div
      className={cn(
        "flex items-end gap-2 rounded-2xl border border-border bg-surface-elevated p-2 shadow-sm",
        className,
      )}
    >
      <Textarea
        ref={textareaRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        rows={1}
        className="min-h-[52px] max-h-[200px] flex-1 resize-none border-0 bg-transparent px-3 py-3 text-base shadow-none focus-visible:ring-0"
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        aria-label="Message"
      />

      <Button
        type="button"
        size="icon"
        className="mb-1 size-9 shrink-0 rounded-full"
        onClick={submit}
        disabled={!canSubmit}
        aria-label={isLoading ? "Sending message" : "Send message"}
      >
        <ArrowUp className="size-4" />
      </Button>
    </div>
  );
}
