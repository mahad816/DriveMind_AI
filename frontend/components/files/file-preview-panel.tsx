"use client";

import { DEMO_MODE } from "@/lib/demo";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink, FileText, MessageSquareQuote } from "lucide-react";

import { FileStatusBadge } from "@/components/files/file-status-badge";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchFileTextPreview } from "@/lib/files/preview";
import {
  buildAskAboutFileHref,
  driveFileUrl,
  fileTypeLabel,
  formatFileDate,
} from "@/lib/files/utils";
import type { DriveFileRead } from "@/lib/api/types";
import { filesCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";
import { preparationEligibility } from "@/lib/knowledge/single-file-preparation";

type FilePreviewPanelProps = {
  file: DriveFileRead | null;
  className?: string;
};

export function FilePreviewPanel({ file, className }: FilePreviewPanelProps) {
  const [preview, setPreview] = useState<string | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  useEffect(() => {
    if (!file || !DEMO_MODE) {
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
          "flex h-full min-h-[320px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border p-8 text-center",
          className,
        )}
      >
        <div className="flex size-12 items-center justify-center rounded-md bg-muted">
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

  return (
    <div
      role={DEMO_MODE ? undefined : "region"}
      aria-label={DEMO_MODE ? undefined : "File inspector"}
      tabIndex={DEMO_MODE ? undefined : 0}
      className={cn(
        "flex h-full flex-col rounded-lg border border-border bg-surface-elevated",
        DEMO_MODE ? "min-h-[320px] overflow-hidden" : "min-h-0 overflow-y-auto overscroll-contain",
        className,
      )}
    >
      <div className="shrink-0 px-5 pt-5 pb-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="break-words text-base font-semibold text-foreground">{file.name}</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {fileTypeLabel(file.mime_type)} · {filesCopy.modified} {formatFileDate(file.modified_at)}
            </p>
          </div>
          <FileStatusBadge status={file.status} />
        </div>
      </div>

      <div className="shrink-0 space-y-3 px-5 pb-5">
        {!DEMO_MODE && file.status !== "indexed" ? <p className="text-sm text-muted-foreground">{preparationEligibility(file) ?? "Discovered metadata only. Select this document to review what will be processed before preparing it."}</p> : null}
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          {!DEMO_MODE && preparationEligibility(file) === null ? <Link href={`/prepare?file=${encodeURIComponent(file.id)}`} className={buttonVariants({ className: "w-full sm:w-auto" })}>Select for preparation</Link> : null}
          {(DEMO_MODE || file.status === "indexed") ? <Link href={askHref} className={buttonVariants({ className: "w-full justify-start sm:w-auto" })}>
            <MessageSquareQuote className="size-4" />
            {DEMO_MODE ? filesCopy.askAboutFile : "Open chat"}
          </Link> : null}
          {!DEMO_MODE ? <a
            href={driveFileUrl(file.drive_file_id)}
            target="_blank"
            rel="noreferrer"
            className={buttonVariants({ variant: "outline", className: "w-full justify-start sm:w-auto" })}
          >
            <ExternalLink className="size-4" />
            {filesCopy.openInDrive}
          </a> : null}
        </div>
      </div>

      <section className={cn("border-t border-border px-5 py-5", DEMO_MODE ? "min-h-0 flex-1 overflow-y-auto" : "shrink-0")} aria-label="File preview">
        <h3 className="mb-3 text-sm font-medium text-foreground">Preview</h3>
        {isLoadingPreview ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-4/6" />
          </div>
        ) : preview ? (
          <div className="whitespace-pre-wrap break-words text-sm leading-6 text-foreground">{preview}</div>
        ) : (
          <p className="text-sm leading-relaxed text-muted-foreground">{DEMO_MODE ? filesCopy.previewUnavailable : "Browsing shows metadata only. Open the original in Google Drive to read its content."}</p>
        )}
      </section>

      <section className="shrink-0 border-t border-border px-5 py-4" aria-label="File details">
        <h3 className="mb-2 text-sm font-medium text-foreground">File details</h3>
        <dl className="flex gap-4 text-sm">
          <dt className="shrink-0 text-muted-foreground">{filesCopy.folder}</dt>
          <dd className="min-w-0 break-words text-foreground">{file.folder_path ?? "—"}</dd>
        </dl>
      </section>
    </div>
  );
}
