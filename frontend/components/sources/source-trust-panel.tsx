"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, ExternalLink, MessageSquareQuote } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { driveFileUrl, fileTypeLabel, formatFileDate, truncatePreview } from "@/lib/files/utils";
import { sourceCopy } from "@/lib/user-language";
import { cn } from "@/lib/utils";

export type SourceTrustDetails = {
  mimeType?: string;
  folderPath?: string | null;
  modifiedAt?: string | null;
};

type SourceTrustPanelProps = {
  filename: string;
  excerpt: string;
  driveFileId?: string;
  modifiedAt?: string | null;
  askHref: string;
  isLoading?: boolean;
  error?: string | null;
  showBackLink?: boolean;
  backHref?: string;
  details?: SourceTrustDetails;
  className?: string;
  onAskClick?: () => void;
};

export function SourceTrustPanel({
  filename,
  excerpt,
  driveFileId,
  modifiedAt,
  askHref,
  isLoading = false,
  error = null,
  showBackLink = false,
  backHref = "/chat",
  details,
  className,
  onAskClick,
}: SourceTrustPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const displayExcerpt = expanded ? excerpt : truncatePreview(excerpt, 480);
  const canExpand = excerpt.trim().length > 480;

  return (
    <div className={cn("flex flex-col gap-6", className)}>
      {showBackLink ? (
        <Link
          href={backHref}
          className={buttonVariants({ variant: "link", className: "w-fit px-0" })}
        >
          <ArrowLeft className="size-4" />
          {sourceCopy.backToChat}
        </Link>
      ) : null}

      <div className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">{filename}</h1>
        <p className="text-sm text-muted-foreground">
          {modifiedAt
            ? `${sourceCopy.modified} ${formatFileDate(modifiedAt)}`
            : sourceCopy.fromDrive}
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : null}

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {!isLoading && !error ? (
        <div className="space-y-3">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {sourceCopy.excerpt}
          </p>
          <blockquote className="border-l-2 border-primary/30 pl-4 text-body-lg leading-relaxed text-foreground">
            &ldquo;{displayExcerpt}&rdquo;
          </blockquote>
          {canExpand ? (
            <button
              type="button"
              className="text-sm text-primary underline-offset-4 hover:underline"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-2">
        {driveFileId ? (
          <a
            href={driveFileUrl(driveFileId)}
            target="_blank"
            rel="noreferrer"
            className={buttonVariants({ variant: "outline", className: "justify-start" })}
          >
            <ExternalLink className="size-4" />
            {sourceCopy.openInDrive}
          </a>
        ) : null}

        <Link
          href={askHref}
          onClick={onAskClick}
          className={buttonVariants({ variant: "secondary", className: "justify-start" })}
        >
          <MessageSquareQuote className="size-4" />
          {sourceCopy.askAboutDocument}
        </Link>
      </div>

      {details ? (
        <details className="rounded-xl border border-border p-4">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            {sourceCopy.moreDetails}
          </summary>
          <dl className="mt-3 space-y-2 text-sm">
            {details.mimeType ? (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Type</dt>
                <dd className="text-right text-foreground">{fileTypeLabel(details.mimeType)}</dd>
              </div>
            ) : null}
            {details.folderPath !== undefined ? (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Folder</dt>
                <dd className="truncate text-right text-foreground">{details.folderPath ?? "—"}</dd>
              </div>
            ) : null}
            {details.modifiedAt ? (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">{sourceCopy.modified}</dt>
                <dd className="text-right text-foreground">{formatFileDate(details.modifiedAt)}</dd>
              </div>
            ) : null}
          </dl>
        </details>
      ) : null}
    </div>
  );
}
