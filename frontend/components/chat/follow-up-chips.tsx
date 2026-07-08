"use client";

import { ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { chatCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";

type FollowUpChipsProps = {
  suggestions: string[];
  onSelect: (question: string) => void;
  disabled?: boolean;
  className?: string;
};

export function FollowUpChips({
  suggestions,
  onSelect,
  disabled = false,
  className,
}: FollowUpChipsProps) {
  if (suggestions.length === 0) return null;

  return (
    <div className={cn("space-y-2 pt-1", className)}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {chatCopy.followUpLabel}
      </p>
      <div className="flex flex-col gap-2">
        {suggestions.map((suggestion) => (
          <Button
            key={suggestion}
            type="button"
            variant="outline"
            disabled={disabled}
            className="h-auto justify-between gap-3 whitespace-normal rounded-xl px-4 py-3 text-left text-sm font-normal leading-snug"
            onClick={() => onSelect(suggestion)}
          >
            <span>{suggestion}</span>
            <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
          </Button>
        ))}
      </div>
    </div>
  );
}
