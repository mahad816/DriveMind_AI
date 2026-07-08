"use client";

import { FileStatusBadge } from "@/components/files/file-status-badge";
import type { DriveFileRead } from "@/lib/api/types";
import { fileTypeIcon } from "@/lib/files/utils";
import { cn } from "@/lib/utils";

type FileListItemProps = {
  file: DriveFileRead;
  selected: boolean;
  onSelect: () => void;
};

export function FileListItem({ file, selected, onSelect }: FileListItemProps) {
  const Icon = fileTypeIcon(file.mime_type);

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left transition-colors",
        selected
          ? "border-primary/40 bg-primary/5"
          : "border-transparent bg-surface-elevated hover:bg-muted/50",
      )}
    >
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-4" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
        <p className="truncate text-xs text-muted-foreground">{file.folder_path ?? "Drive"}</p>
      </div>
      <FileStatusBadge status={file.status} />
    </button>
  );
}
