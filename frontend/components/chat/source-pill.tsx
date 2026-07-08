import { FileText } from "lucide-react";

import { cn } from "@/lib/utils";

type SourcePillProps = {
  label: string;
  onClick: () => void;
  className?: string;
};

export function SourcePill({ label, onClick, className }: SourcePillProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-border bg-background px-2.5 py-1 text-source text-foreground transition-colors hover:bg-muted/60",
        className,
      )}
    >
      <FileText className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="max-w-[12rem] truncate">{label}</span>
    </button>
  );
}
