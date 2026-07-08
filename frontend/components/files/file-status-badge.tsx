"use client";

import type { DriveFileStatus } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const statusTextClass: Record<DriveFileStatus, string> = {
  discovered: "border-slate-500/40 text-slate-700 dark:text-slate-400",
  indexing: "border-amber-500/40 text-amber-700 dark:text-amber-400",
  indexed: "border-emerald-500/40 text-emerald-700 dark:text-emerald-400",
  failed: "border-destructive/40 text-destructive dark:text-destructive",
  skipped: "border-sky-500/40 text-sky-700 dark:text-sky-400",
};

const statusLabel: Record<DriveFileStatus, string> = {
  discovered: "Discovered",
  indexing: "Indexing",
  indexed: "Indexed",
  failed: "Failed",
  skipped: "Skipped",
};

export function FileStatusBadge({ status }: { status: DriveFileStatus }) {
  return (
    <Badge
      variant="outline"
      className={cn("text-xs font-normal", statusTextClass[status])}
    >
      {statusLabel[status]}
    </Badge>
  );
}

