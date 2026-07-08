"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink, FileText, Loader2, MessageSquareQuote, RefreshCw, Sparkles } from "lucide-react";

import { FileStatusBadge } from "@/components/files/file-status-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchFileTextPreview } from "@/lib/files/preview";
import {
  buildAskAboutFileHref,
  driveFileUrl,
  fileTypeLabel,
  formatFileDate,
} from "@/lib/files/utils";
import type { DriveFileRead } from "@/lib/api/types";
import { prepareSingleFile } from "@/lib/knowledge/prepare-file";
import { filesCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";

type FilePreviewPanelProps = {
  file: DriveFileRead | null;
  className?: string;
};

export function FilePreviewPanel({ file, className }: FilePreviewPanelProps) {
  const [preview, setPreview] = useState<string | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState<string | null>(null);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }

    const activeFile = file;
    let cancelled = false;

    async function loadPreview() {
      setIsLoadingPreview(true);
      const text = await fetchFileTextPreview(activeFile.id, activeFile.mime_type);
      if (!cancelled) {
        setPreview(text);
        setIsLoadingPreview(false);
      }
    }

    void loadPreview();

    return () => {
      cancelled = true;
    };
  }, [file]);

  if (!file) {
    return (
      <div
        className={cn(
          "flex h-full min-h-[320px] flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border bg-surface-elevated p-8 text-center",
          className,
        )}
      >
        <div className="flex size-12 items-center justify-center rounded-2xl bg-muted">
          <FileText className="size-6 text-muted-foreground" />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-medium text-foreground">Select a file</p>
          <p className="text-xs text-muted-foreground">
            Pick any file on the left to preview its content and actions.
          </p>
        </div>
      </div>
    );
  }

  const askHref = buildAskAboutFileHref(file);
  const needsPrepare = file.status !== "indexed";

  async function handlePrepareFile() {
    setPrepareError(null);
    setIsPreparing(true);
    try {
      await prepareSingleFile(file.id);
    } catch (error) {
      setPrepareError(error instanceof Error ? error.message : "Could not prepare this file.");
    } finally {
      setIsPreparing(false);
    }
  }

  return (
    <div
      className={cn(
        "flex h-full min-h-[320px] flex-col rounded-2xl border border-border bg-surface-elevated overflow-hidden",
        className,
      )}
    >
      {/* Header */}
      <div className="border-b border-border px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-foreground">{file.name}</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {fileTypeLabel(file.mime_type)} · {filesCopy.modified} {formatFileDate(file.modified_at)}
            </p>
          </div>
          <FileStatusBadge status={file.status} />
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-5">
        {/* Excerpt */}
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <FileText className="size-3.5" />
            {filesCopy.preview}
          </p>
          {isLoadingPreview ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-4/6" />
            </div>
          ) : (
            <blockquote className="rounded-lg border-l-2 border-primary/30 bg-muted/50 p-3 text-sm leading-relaxed text-foreground">
              {preview ? `"${preview}"` : (
                <span className="text-muted-foreground">{filesCopy.previewUnavailable}</span>
              )}
            </blockquote>
          )}
        </div>

        {/* AI actions */}
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <Sparkles className="size-3.5" />
            Ask AI
          </p>
          <div className="flex flex-col gap-2">
            {needsPrepare ? (
              <Button
                type="button"
                variant="outline"
                className="justify-start rounded-xl"
                disabled={isPreparing}
                onClick={() => void handlePrepareFile()}
              >
                {isPreparing ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <RefreshCw className="size-4" />
                )}
                {isPreparing ? "Preparing this file…" : "Prepare this file for chat"}
              </Button>
            ) : null}
            {prepareError ? (
              <p className="text-xs text-destructive">{prepareError}</p>
            ) : null}
            <Link href={askHref} className={buttonVariants({ className: "justify-start rounded-xl" })}>
              <MessageSquareQuote className="size-4" />
              {filesCopy.askAboutFile}
            </Link>
            <a
              href={driveFileUrl(file.drive_file_id)}
              target="_blank"
              rel="noreferrer"
              className={buttonVariants({
                variant: "outline",
                className: "justify-start rounded-xl",
              })}
            >
              <ExternalLink className="size-4" />
              {filesCopy.openInDrive}
            </a>
          </div>
        </div>

        {/* Metadata */}
        <details className="rounded-xl border border-border">
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground">
            {filesCopy.details}
          </summary>
          <dl className="border-t border-border px-4 py-3 space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{filesCopy.type}</dt>
              <dd className="text-right text-foreground">{fileTypeLabel(file.mime_type)}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{filesCopy.folder}</dt>
              <dd className="truncate text-right text-foreground">{file.folder_path ?? "—"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{filesCopy.modified}</dt>
              <dd className="text-right text-foreground">{formatFileDate(file.modified_at)}</dd>
            </div>
          </dl>
        </details>
      </div>
    </div>
  );
}
