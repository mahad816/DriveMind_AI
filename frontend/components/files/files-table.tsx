"use client";

import { useId } from "react";
import { Folder } from "lucide-react";
import { FileStatusBadge } from "@/components/files/file-status-badge";
import type { DriveFileRead } from "@/lib/api/types";
import { fileTypeIcon, fileTypeLabel, formatFileDate } from "@/lib/files/utils";
import { preparationEligibility } from "@/lib/knowledge/single-file-preparation";

type Props = {
  files: DriveFileRead[];
  selected: readonly string[];
  owner: string | null;
  disabled: boolean;
  disabledReason: string;
  onToggle: (file: DriveFileRead) => void;
  onPreview: (file: DriveFileRead) => void;
};

/** Presentation only: the library and preparation controller remain authoritative. */
export function FilesTable({ files, ...selection }: Props) {
  return <div className="files-table" role="table" aria-label="Drive files">
    <div className="files-table-head" role="row">
      <span role="columnheader" className="files-check-cell"><span className="sr-only">Selection</span></span>
      <span role="columnheader">Name</span>
      <span role="columnheader" className="files-location">Location</span>
      <span role="columnheader" className="files-modified">Modified</span>
      <span role="columnheader" className="files-status">Status</span>
    </div>
    {files.map(file => <FileRow key={file.id} file={file} {...selection} />)}
  </div>;
}

function FileRow({ file, selected, owner, disabled, disabledReason, onToggle, onPreview }: Omit<Props, "files"> & { file: DriveFileRead }) {
  const description = useId();
  const checked = selected.includes(file.id);
  const eligibility = file.user_id !== owner ? "Account could not be verified." : preparationEligibility(file);
  const atLimit = !checked && selected.length >= 5;
  const reason = disabled ? disabledReason : eligibility ?? (atLimit ? "Five-document limit reached. Remove one to choose another." : "Selection does not prepare this document.");
  const Icon = fileTypeIcon(file.mime_type);
  return <div role="row" className={`files-table-row${checked ? " is-selected" : ""}`}>
    <div role="cell" className="files-check-cell">
      <label title={reason} className="files-check-target">
        <input type="checkbox" checked={checked} disabled={disabled || (!checked && (!!eligibility || atLimit))}
          onChange={() => onToggle(file)} aria-label={`Select ${file.name} for preparation`} aria-describedby={description} />
        <span id={description} className="sr-only">{reason}</span>
      </label>
    </div>
    <div role="cell" className="files-name-cell">
      <span className="files-type-icon"><Icon aria-hidden="true" className="size-4" /></span>
      <div className="min-w-0 flex-1">
        <button type="button" className="files-name-button" onClick={() => onPreview(file)} title={`Preview ${file.name}`}>{file.name}</button>
        <p className="files-metadata">{fileTypeLabel(file.mime_type)}</p>
      </div>
    </div>
    <div role="cell" className="files-location"><Folder aria-hidden="true" className="size-3" /><span title={file.folder_path ?? ""}>{file.folder_path || "—"}</span></div>
    <div role="cell" className="files-modified">{formatFileDate(file.modified_at)}</div>
    <div role="cell" className="files-status"><FileStatusBadge status={file.status} /></div>
  </div>;
}
