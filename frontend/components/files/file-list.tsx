"use client";

import { FileListItem } from "@/components/files/file-list-item";
import type { DriveFileRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { preparationEligibility } from "@/lib/knowledge/single-file-preparation";
import { sessionOwner } from "@/lib/api/session-events";
import { useId } from "react";

type FileListProps = {
  files: DriveFileRead[];
  selectedId: string | null;
  onSelect: (file: DriveFileRead) => void;
  className?: string;
  preparation?: {
    selected: string[];
    disabled: boolean;
    onToggle: (file: DriveFileRead) => void;
  };
};

export function FileList({ files, selectedId, onSelect, className, preparation }: FileListProps) {
  return (
    <ul className={cn("min-w-0 divide-y divide-border border-y border-border", className)} aria-label="Drive files">
      {files.map((file) => (
        <li key={file.id} className={preparation ? "flex min-w-0 items-center" : undefined}>
          {preparation ? <PreparationCheckbox file={file} selection={preparation} /> : null}
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

function PreparationCheckbox({ file, selection }: { file: DriveFileRead; selection: NonNullable<FileListProps["preparation"]> }) {
  const description = useId();
  const checked = selection.selected.includes(file.id);
  const reason = file.user_id !== sessionOwner() ? "Account could not be verified." : preparationEligibility(file);
  const disabled = selection.disabled || (!checked && (!!reason || selection.selected.length >= 5));
  return <label className="flex min-h-11 min-w-11 shrink-0 items-center justify-center" title={reason ?? (disabled && !checked ? "Select up to five documents." : undefined)}>
    <input type="checkbox" checked={checked} disabled={disabled} onChange={() => selection.onToggle(file)}
      aria-describedby={description}
      aria-label={`Select ${file.name} for preparation`} className="size-4 accent-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring" />
    <span id={description} className="sr-only">{reason ?? (selection.disabled ? "Review existing preparation before making another selection." : selection.selected.length >= 5 && !checked ? "Five-document limit reached. Remove one to choose another." : "Selection does not prepare this document.")}</span>
  </label>;
}
