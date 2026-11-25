import { cn } from "@/lib/utils";

/** Small determinate-looking arc. Used only inside a control that already says what it is doing. */
export function Spinner({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={cn("size-4 animate-spin [animation-duration:900ms]", className)}>
      <circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" strokeOpacity=".22" strokeWidth="1.75" />
      <path d="M8 1.75a6.25 6.25 0 0 1 6.25 6.25" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  );
}
