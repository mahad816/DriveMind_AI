"use client";

import { useEffect, useState } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { SourceTrustPanel } from "@/components/sources/source-trust-panel";
import { isApiError } from "@/lib/api/errors";
import { getSourceChunk } from "@/lib/api/sources";
import type { CitationItem } from "@/lib/api/types";

type SourcePanelProps = {
  citation: CitationItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function SourcePanel({ citation, open, onOpenChange }: SourcePanelProps) {
  const [excerpt, setExcerpt] = useState("");
  const [modifiedAt, setModifiedAt] = useState<string | null>(null);
  const [mimeType, setMimeType] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !citation) {
      return;
    }

    const activeCitation = citation;
    const chunkId = activeCitation.chunk_id;
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      setExcerpt(activeCitation.snippet);
      setModifiedAt(null);
      setMimeType(undefined);

      try {
        const result = await getSourceChunk(chunkId);
        if (!cancelled) {
          setExcerpt(result.text?.trim() || activeCitation.snippet);
          setModifiedAt(result.modified_at);
          setMimeType(result.mime_type);
        }
      } catch (err) {
        if (!cancelled) {
          const message = isApiError(err)
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Unable to load source";
          setError(message);
          setExcerpt(activeCitation.snippet);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [citation, open]);

  const filename = citation?.filename ?? "Document";
  const driveFileId = citation?.drive_file_id;
  const askHref = `/chat?ask=${encodeURIComponent(`Tell me more about "${filename}"`)}`;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-md">
        <SheetHeader className="sr-only">
          <SheetTitle>{filename}</SheetTitle>
          <SheetDescription>Source excerpt and actions.</SheetDescription>
        </SheetHeader>
        <div className="h-full overflow-y-auto px-6 py-5">
          <SourceTrustPanel
            filename={filename}
            excerpt={excerpt}
            driveFileId={driveFileId}
            modifiedAt={modifiedAt}
            askHref={askHref}
            isLoading={isLoading}
            error={error}
            details={mimeType ? { mimeType, modifiedAt } : undefined}
            onAskClick={() => onOpenChange(false)}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}
