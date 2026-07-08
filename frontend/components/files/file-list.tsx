"use client";

import { FileListItem } from "@/components/files/file-list-item";
import type { DriveFileRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type FileListProps = {
  files: DriveFileRead[];
  selectedId: string | null;
  onSelect: (file: DriveFileRead) => void;
  className?: string;
};

export function FileList({ files, selectedId, onSelect, className }: FileListProps) {
  return (
    <ul className={cn("space-y-1", className)} aria-label="Knowledge library files">
      {files.map((file) => (
        <li key={file.id}>
          <FileListItem
            file={file}
            selected={selectedId === file.id}
            onSelect={() => onSelect(file)}
          />
        </li>
      ))}
    </ul>
  );
}
