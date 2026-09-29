"use client";

import { FileStatusBadge } from "@/components/files/file-status-badge";
import type { DriveFileRead } from "@/lib/api/types";
import { fileTypeIcon, fileTypeLabel, formatFileDate } from "@/lib/files/utils";
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
        "flex w-full min-w-0 items-center gap-3 border-l-2 px-2 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-3",
        selected
          ? "border-primary bg-accent/60"
          : "border-transparent hover:bg-muted/60",
      )}
    >
      <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <Icon className="size-4" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
        <p className="truncate text-xs text-muted-foreground">
          {fileTypeLabel(file.mime_type)} · {formatFileDate(file.modified_at)}
          {file.folder_path ? ` · ${file.folder_path}` : ""}
        </p>
      </div>
      <FileStatusBadge status={file.status} />
    </button>
  );
}
