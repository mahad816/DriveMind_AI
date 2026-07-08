import { cn } from "@/lib/utils";

type ThinkingIndicatorProps = {
  className?: string;
};

export function ThinkingIndicator({ className }: ThinkingIndicatorProps) {
  return (
    <div
      className={cn("flex items-center gap-2 text-sm text-muted-foreground", className)}
      role="status"
      aria-label="Thinking"
    >
      <span className="flex gap-1" aria-hidden="true">
        <span className="size-1.5 animate-pulse rounded-full bg-primary/70 [animation-delay:0ms]" />
        <span className="size-1.5 animate-pulse rounded-full bg-primary/70 [animation-delay:150ms]" />
        <span className="size-1.5 animate-pulse rounded-full bg-primary/70 [animation-delay:300ms]" />
      </span>
      <span>Thinking…</span>
    </div>
  );
}
