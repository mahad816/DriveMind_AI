import { cn } from "@/lib/utils";

type UserMessageProps = {
  content: string;
  className?: string;
};

export function UserMessage({ content, className }: UserMessageProps) {
  return (
    <div className={cn("flex justify-end", className)}>
      <div className="max-w-[88%] rounded-2xl rounded-br-md border border-border/50 bg-muted/50 px-4 py-3 shadow-sm">
        <p className="text-base leading-relaxed text-foreground">{content}</p>
      </div>
    </div>
  );
}
