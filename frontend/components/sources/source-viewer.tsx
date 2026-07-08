"use client";

import { useEffect, useState } from "react";

import { SourceTrustPanel } from "@/components/sources/source-trust-panel";
import { isApiError } from "@/lib/api/errors";
import { getSourceChunk } from "@/lib/api/sources";
import type { SourceChunkRead } from "@/lib/api/types";
import { sourceCopy } from "@/lib/user-language";

type SourceViewerProps = {
  chunkId: string;
};

export function SourceViewer({ chunkId }: SourceViewerProps) {
  const [data, setData] = useState<SourceChunkRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!chunkId) {
      setError("Source not found");
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);

      try {
        const result = await getSourceChunk(chunkId);
        if (!cancelled) {
          setData(result);
        }
      } catch (err) {
        if (!cancelled) {
          const message = isApiError(err)
            ? err.detail
            : err instanceof Error
              ? err.message
              : sourceCopy.loadError;
          setError(message);
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
  }, [chunkId]);

  const filename = data?.filename ?? "Document";
  const askHref = `/chat?ask=${encodeURIComponent(`Tell me more about "${filename}"`)}`;

  return (
    <SourceTrustPanel
      filename={filename}
      excerpt={data?.text?.trim() ?? ""}
      driveFileId={data?.drive_file_id}
      modifiedAt={data?.modified_at ?? null}
      askHref={askHref}
      isLoading={isLoading}
      error={error}
      showBackLink
      details={
        data
          ? {
              mimeType: data.mime_type,
              modifiedAt: data.modified_at,
            }
          : undefined
      }
    />
  );
}
