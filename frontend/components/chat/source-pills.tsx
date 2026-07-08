"use client";

import type { CitationItem } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { SourcePill } from "@/components/chat/source-pill";

export function uniqueCitationsByFilename(citations: CitationItem[]): CitationItem[] {
  const seen = new Set<string>();
  const result: CitationItem[] = [];

  for (const citation of citations) {
    const key = citation.filename.trim().toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(citation);
  }

  return result;
}

type SourcePillsProps = {
  citations: CitationItem[];
  onSelect: (citation: CitationItem) => void;
  className?: string;
};

export function SourcePills({ citations, onSelect, className }: SourcePillsProps) {
  const unique = uniqueCitationsByFilename(citations);

  if (unique.length === 0) {
    return null;
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-x-1.5 gap-y-2", className)}>
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Sources
      </span>
      {unique.map((citation, index) => (
        <span key={citation.chunk_id} className="inline-flex items-center">
          {index > 0 ? (
            <span className="mx-1 text-source text-muted-foreground" aria-hidden="true">
              ·
            </span>
          ) : null}
          <SourcePill label={citation.filename} onClick={() => onSelect(citation)} />
        </span>
      ))}
    </div>
  );
}
