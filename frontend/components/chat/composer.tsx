"use client";
import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";
import { ArrowUp, Square } from "lucide-react";
import { QUESTION_LIMIT } from "@/lib/chat/question";
import { questionCharacters } from "@/lib/demo";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export type ComposerHandle = { focus: () => void; insert: (text: string) => void };
type Props = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  /** Why sending is unavailable right now; typing always stays possible. */
  blocked?: string | null;
  waiting: boolean;
  sending: boolean;
  footer?: ReactNode;
  placeholder?: string;
};

export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  { value, onChange, onSend, onStop, blocked, waiting, sending, footer, placeholder = "Ask about your prepared documents…" }, ref,
) {
  const area = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({
    focus: () => area.current?.focus(),
    insert: text => { onChange(text + value.replace(/^In “[^”]*”, /, "")); requestAnimationFrame(() => { const el = area.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }); },
  }), [onChange, value]);
  // Auto-grow up to 40% of the viewport; layout effect avoids a visible jump.
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, Math.round(window.innerHeight * 0.4))}px`;
  }, [value]);
  const length = questionCharacters(value);
  const tooLong = length > QUESTION_LIMIT;
  const canSend = !!value.trim() && !tooLong && !blocked && !waiting && !sending;

  return (
    <form onSubmit={event => { event.preventDefault(); if (canSend) onSend(); }}
      className={cn("rounded-panel border bg-sheet transition-[border-color,box-shadow] duration-150",
        "border-edge/60 focus-within:border-archive/70 focus-within:shadow-[0_0_0_3px_var(--archive-wash)]")}>
      <label htmlFor="composer" className="sr-only">Question</label>
      <textarea id="composer" ref={area} value={value} rows={1} placeholder={placeholder}
        onChange={event => onChange(event.target.value)}
        onKeyDown={event => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (canSend) onSend(); }
        }}
        aria-describedby="composer-help" aria-invalid={tooLong || undefined}
        className="block max-h-[40dvh] focus-visible:shadow-none min-h-[3.25rem] w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-body leading-6 text-ink outline-none placeholder:text-faint" />
      <div className="flex items-end justify-between gap-3 px-3 pb-2.5 pt-1">
        <p id="composer-help" className="min-w-0 pb-1.5 pl-1 text-meta text-faint" aria-live="polite">
          {tooLong ? <span className="text-fault">{length.toLocaleString()} of {QUESTION_LIMIT.toLocaleString()} characters. Shorten the question to send it.</span>
            : blocked ? <span className="text-graphite">{blocked}</span>
            : length > QUESTION_LIMIT - 500 ? `${length.toLocaleString()} of ${QUESTION_LIMIT.toLocaleString()} characters`
            : footer}
        </p>
        {waiting && onStop ? (
          <button type="button" onClick={onStop} aria-label="Stop waiting for the answer"
            className="press grid size-9 shrink-0 place-items-center rounded-control border border-edge/70 bg-sheet text-ink hover:bg-well touch-44">
            <Square className="size-3 fill-current" aria-hidden="true" />
          </button>
        ) : (
          <button type="submit" disabled={!canSend} aria-label="Send question"
            className="press grid size-9 shrink-0 place-items-center rounded-control bg-archive text-archive-ink hover:bg-archive-hover disabled:bg-well disabled:text-faint touch-44">
            {sending ? <Spinner className="size-4" /> : <ArrowUp className="size-4" strokeWidth={2.25} aria-hidden="true" />}
          </button>
        )}
      </div>
    </form>
  );
});
