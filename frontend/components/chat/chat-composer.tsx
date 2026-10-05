"use client";

import { forwardRef, useCallback, useEffect, useId, useImperativeHandle, useRef } from "react";
import { ArrowUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { DEMO_MODE, DEMO_QUESTION_LIMIT, questionCharacters } from "@/lib/demo";

export type ChatComposerHandle = {
  focus: () => void;
};

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

export const ChatComposer = forwardRef<ChatComposerHandle, ChatComposerProps>(
  function ChatComposer(
    {
      value,
      onChange,
      onSubmit,
      disabled,
      isLoading,
      placeholder = "Message DriveMind…",
      className,
    },
    ref,
  ) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const isComposingRef = useRef(false);
    const helperId = useId();
    const count = DEMO_MODE ? questionCharacters(value) : 0;
    const overLimit = DEMO_MODE && count > DEMO_QUESTION_LIMIT;
    const nearLimit = DEMO_MODE && count >= DEMO_QUESTION_LIMIT * 0.8;
    const canSubmit = !disabled && !isLoading && !overLimit && value.trim().length > 0;

    useImperativeHandle(ref, () => ({
      focus: () => {
        textareaRef.current?.focus();
      },
    }));

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
      <div>
        <div
          className={cn(
            "flex items-end gap-2 rounded-2xl border border-border/80 bg-surface-elevated p-2 shadow-sm ring-1 ring-black/[0.02] transition-shadow focus-within:border-primary/30 focus-within:shadow-md focus-within:ring-primary/10 dark:ring-white/[0.02]",
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
                if (isComposingRef.current || event.nativeEvent.isComposing) return;
                event.preventDefault();
                submit();
              }
            }}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            aria-label="Message"
            aria-describedby={DEMO_MODE ? helperId : undefined}
            aria-invalid={overLimit || undefined}
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
        {DEMO_MODE ? (
          <div id={helperId} className="grid min-h-10 grid-cols-1 px-2 pt-2 text-xs leading-4 text-muted-foreground sm:min-h-6 sm:grid-cols-[1fr_auto] sm:gap-3">
            <span>Public demo · Questions up to 4,000 characters</span>
            <span aria-live="polite" className={cn("min-h-4 tabular-nums sm:text-right", count >= DEMO_QUESTION_LIMIT && "text-destructive")}>
              {nearLimit ? `${count.toLocaleString("en-US")} / 4,000${overLimit ? " · Shorten to send" : count === DEMO_QUESTION_LIMIT ? " · Limit reached" : ""}` : ""}
            </span>
          </div>
        ) : null}
      </div>
    );
  },
);
