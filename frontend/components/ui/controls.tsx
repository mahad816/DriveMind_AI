"use client";
import { Checkbox as BaseCheckbox } from "@base-ui/react/checkbox";
import { Check, Search, X } from "lucide-react";
import { forwardRef } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Checkbox({ checked, onCheckedChange, disabled, label, describedBy, className }: {
  checked: boolean; onCheckedChange: (checked: boolean) => void; disabled?: boolean; label: string; describedBy?: string; className?: string;
}) {
  return (
    <BaseCheckbox.Root checked={checked} disabled={disabled} onCheckedChange={value => onCheckedChange(value)}
      aria-label={label} aria-describedby={describedBy}
      className={cn(
        "hit press grid size-[18px] shrink-0 place-items-center rounded-[4px] border border-edge bg-sheet",
        "data-[checked]:border-archive data-[checked]:bg-archive data-[disabled]:border-rule data-[disabled]:bg-well data-[disabled]:cursor-not-allowed",
        className,
      )}>
      <BaseCheckbox.Indicator className="text-archive-ink transition-opacity duration-100 data-[unchecked]:opacity-0">
        <Check className="size-3.5" strokeWidth={2.5} aria-hidden="true" />
      </BaseCheckbox.Indicator>
    </BaseCheckbox.Root>
  );
}

type InputProps = InputHTMLAttributes<HTMLInputElement> & { label?: string };
export const TextInput = forwardRef<HTMLInputElement, InputProps>(function TextInput({ className, ...props }, ref) {
  return (
    <input ref={ref} {...props}
      className={cn("h-9 w-full rounded-control border border-edge/80 bg-sheet px-3 text-body text-ink placeholder:text-faint",
        "transition-[border-color,box-shadow] duration-100 hover:border-edge focus-visible:border-archive touch-44", className)} />
  );
});

/** Search field with an explicit clear button; Escape also clears. */
export const SearchField = forwardRef<HTMLInputElement, InputProps & { value: string; onValueChange: (value: string) => void; trailing?: ReactNode }>(
  function SearchField({ value, onValueChange, className, label, trailing, ...props }, ref) {
    return (
      <div className={cn("relative flex items-center", className)}>
        <Search aria-hidden="true" className="pointer-events-none absolute left-3 size-4 text-faint" />
        <input ref={ref} type="search" value={value} aria-label={label}
          onChange={event => onValueChange(event.target.value)}
          onKeyDown={event => { if (event.key === "Escape" && value) { event.stopPropagation(); onValueChange(""); } }}
          className="h-9 w-full rounded-control border border-edge/80 bg-sheet pl-9 pr-9 text-body placeholder:text-faint transition-[border-color] duration-100 hover:border-edge focus-visible:border-archive touch-44 [&::-webkit-search-cancel-button]:hidden"
          {...props} />
        {value ? (
          <button type="button" onClick={() => onValueChange("")} aria-label="Clear search"
            className="press absolute right-1.5 grid size-7 place-items-center rounded-control text-graphite hover:bg-well hover:text-ink">
            <X className="size-3.5" aria-hidden="true" />
          </button>
        ) : trailing}
      </div>
    );
  },
);

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <kbd className={cn("rounded-[4px] border border-rule bg-paper px-1.5 py-px font-sans text-meta text-faint", className)}>{children}</kbd>;
}

/** Static skeleton: no shimmer (blueprint §11). Reserves the space of what will load. */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cn("block rounded-[4px] bg-well", className)} />;
}

export type Tone = "ready" | "neutral" | "working" | "caution" | "fault";
/** Dot plus word, never colour alone. */
export function StatusDot({ tone, className }: { tone: Tone; className?: string }) {
  return (
    <span aria-hidden="true" className={cn("relative inline-block size-2 shrink-0 rounded-full transition-colors duration-150",
      tone === "ready" && "bg-archive",
      tone === "neutral" && "border border-edge bg-transparent",
      tone === "working" && "bg-archive/55 after:absolute after:inset-[-3px] after:rounded-full after:border after:border-archive/40 after:animate-ping after:[animation-duration:1.6s]",
      tone === "caution" && "bg-caution",
      tone === "fault" && "bg-fault",
      className)} />
  );
}

/** Persistent, page-level notice that stays until the condition is resolved. */
export function Banner({ tone, children, action }: { tone: "caution" | "fault" | "neutral"; children: ReactNode; action?: ReactNode }) {
  return (
    <div role={tone === "fault" ? "alert" : "status"}
      className={cn("enter-fade flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2.5 text-label md:px-6",
        tone === "caution" && "border-caution/25 bg-caution-wash text-ink",
        tone === "fault" && "border-fault/25 bg-fault-wash text-ink",
        tone === "neutral" && "border-rule bg-well text-ink")}>
      <span className={cn("size-1.5 shrink-0 rounded-full", tone === "caution" ? "bg-caution" : tone === "fault" ? "bg-fault" : "bg-graphite")} aria-hidden="true" />
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  );
}
