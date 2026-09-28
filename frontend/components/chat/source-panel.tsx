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
  citations?: CitationItem[];
  onCitationSelect?: (citation: CitationItem) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

type SourceDetailState = {
  chunkId: string;
  excerpt: string;
  modifiedAt: string | null;
  mimeType?: string;
  isLoading: boolean;
  error: string | null;
};

export function SourcePanel({
  citation,
  citations,
  onCitationSelect,
  open,
  onOpenChange,
}: SourcePanelProps) {
  const [detail, setDetail] = useState<SourceDetailState | null>(null);

  useEffect(() => {
    if (!open || !citation) {
      return;
    }

    const activeCitation = citation;
    const chunkId = activeCitation.chunk_id;
    let cancelled = false;

    async function load() {
      setDetail({
        chunkId,
        excerpt: activeCitation.snippet,
        modifiedAt: null,
        isLoading: true,
        error: null,
      });

      try {
        const result = await getSourceChunk(chunkId);
        if (!cancelled) {
          setDetail({
            chunkId,
            excerpt: result.text?.trim() || activeCitation.snippet,
            modifiedAt: result.modified_at,
            mimeType: result.mime_type,
            isLoading: false,
            error: null,
          });
        }
      } catch (err) {
        if (!cancelled) {
          const message = isApiError(err)
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Unable to load source";
          setDetail({
            chunkId,
            excerpt: activeCitation.snippet,
            modifiedAt: null,
            isLoading: false,
            error: message,
          });
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
  const currentDetail = citation && detail?.chunkId === citation.chunk_id ? detail : null;
  const answerCitations = citations ?? (citation ? [citation] : []);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-md">
        <SheetHeader className="sr-only">
          <SheetTitle>{filename}</SheetTitle>
          <SheetDescription>Source excerpt and actions.</SheetDescription>
        </SheetHeader>
        <div className="h-full overflow-y-auto px-6 py-5">
          {answerCitations.length > 1 ? (
            <nav aria-label="Cited passages" className="mb-5 space-y-1">
              {answerCitations.map((item, index) => (
                <button
                  key={item.chunk_id}
                  type="button"
                  aria-pressed={item.chunk_id === citation?.chunk_id}
                  onClick={() => onCitationSelect?.(item)}
                  className="block w-full rounded-md px-2 py-2 text-left text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring aria-pressed:bg-muted"
                >
                  <span className="block font-medium">Citation {index + 1}: {item.filename}</span>
                  <span className="block truncate text-xs text-muted-foreground">{item.snippet}</span>
                </button>
              ))}
            </nav>
          ) : null}
          <SourceTrustPanel
            filename={filename}
            excerpt={currentDetail?.excerpt ?? citation?.snippet ?? ""}
            driveFileId={driveFileId}
            modifiedAt={currentDetail?.modifiedAt ?? null}
            askHref={askHref}
            isLoading={Boolean(open && citation && (!currentDetail || currentDetail.isLoading))}
            error={currentDetail?.error ?? null}
            details={currentDetail?.mimeType ? { mimeType: currentDetail.mimeType, modifiedAt: currentDetail.modifiedAt } : undefined}
            onAskClick={() => onOpenChange(false)}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}
