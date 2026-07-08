import { cn } from "@/lib/utils";

type UserMessageProps = {
  content: string;
  className?: string;
};

export function UserMessage({ content, className }: UserMessageProps) {
  return (
    <div className={cn("flex justify-end", className)}>
      <div className="max-w-[85%] rounded-2xl bg-muted/80 px-4 py-3 text-sm text-[var(--text-secondary)]">
        <p className="text-base leading-relaxed text-foreground">{content}</p>
      </div>
    </div>
  );
}
