"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { CitationItem } from "@/lib/api/types";

function truncateSnippet(snippet: string, maxChars: number) {
  const s = snippet.trim();
  if (s.length <= maxChars) return s;
  return `${s.slice(0, maxChars)}…`;
}

export function CitationCard({
  citation,
  index,
}: {
  citation: CitationItem;
  index: number;
}) {
  const href = `/sources/${encodeURIComponent(citation.chunk_id)}`;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <CardTitle className="text-base">
              Source <span className="text-muted-foreground">[{index}]</span>
            </CardTitle>
            <CardDescription>{citation.filename}</CardDescription>
          </div>
          {citation.score !== null ? (
            <Badge variant="outline" className="text-xs font-normal">
              {citation.score.toFixed(2)}
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          {truncateSnippet(citation.snippet, 220)}
        </p>
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            chunk_id: <span className="font-mono">{citation.chunk_id}</span>
          </p>
          <Link
            href={href}
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            Open
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

