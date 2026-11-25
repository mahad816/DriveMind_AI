import { cn } from "@/lib/utils";

/** A page with a margin rule and one highlighted line: the product in one glyph. */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className={cn("size-5 shrink-0", className)}>
      <rect x="2.75" y="2.75" width="14.5" height="14.5" rx="2.5" fill="var(--sheet)" stroke="var(--ink)" strokeWidth="1.5" />
      <path d="M12.75 3v14" stroke="var(--ink)" strokeOpacity=".35" strokeWidth="1.25" />
      <rect x="5" y="7.25" width="6" height="2.5" rx="0.75" fill="var(--highlight-edge)" />
      <path d="M5 12.25h5M5 14.5h3.5" stroke="var(--ink)" strokeOpacity=".55" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}

export function Wordmark({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-ink", className)}>
      <Mark />
      {compact ? <span className="sr-only">DriveMind</span> : <span className="font-serif text-[1.0625rem] font-semibold tracking-[-0.01em]">DriveMind</span>}
    </span>
  );
}
