"use client";

import { FileText, Loader2, Scissors, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import type { DriveFileRead, DriveFileStatus } from "@/lib/api/types";
import { FileStatusBadge } from "@/components/files/file-status-badge";

export type ReindexAction = "ingest" | "chunk" | "build";

type FilesTableProps = {
  files: DriveFileRead[];
  isConnected: boolean;
  busyAction:
    | null
    | {
        fileId: string;
        action: ReindexAction;
      };
  onRunAction: (fileId: string, action: ReindexAction) => Promise<void>;
};

function formatMime(mimeType: string) {
  if (mimeType === "application/pdf") return "PDF";
  if (mimeType.includes("document")) return "DOC";
  if (mimeType.includes("spreadsheet")) return "SHEET";
  if (mimeType.startsWith("image/")) return "IMAGE";
  return mimeType;
}

function formatNullableDate(value: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString();
}

export function FilesTable({
  files,
  isConnected,
  busyAction,
  onRunAction,
}: FilesTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Folder</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Modified</TableHead>
          <TableHead>Indexed</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>

      <TableBody>
        {files.map((file) => {
          const isBusyForRow = busyAction?.fileId === file.id;
          const actionBusy = isBusyForRow ? busyAction?.action : null;

          return (
            <TableRow key={file.id}>
              <TableCell className="max-w-[220px] truncate">{file.name}</TableCell>
              <TableCell className="max-w-[180px] truncate">
                {file.folder_path ?? "—"}
              </TableCell>
              <TableCell>{formatMime(file.mime_type)}</TableCell>
              <TableCell>
                <FileStatusBadge status={file.status as DriveFileStatus} />
              </TableCell>
              <TableCell>{formatNullableDate(file.modified_at)}</TableCell>
              <TableCell>{formatNullableDate(file.indexed_at)}</TableCell>
              <TableCell className="text-right">
                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    type="button"
                    aria-label={`Re-ingest ${file.name}`}
                    disabled={!isConnected || busyAction !== null}
                    onClick={() => void onRunAction(file.id, "ingest")}
                  >
                    {actionBusy === "ingest" ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <FileText className="size-4" />
                    )}
                  </Button>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    type="button"
                    aria-label={`Re-chunk ${file.name}`}
                    disabled={!isConnected || busyAction !== null}
                    onClick={() => void onRunAction(file.id, "chunk")}
                  >
                    {actionBusy === "chunk" ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Scissors className="size-4" />
                    )}
                  </Button>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    type="button"
                    aria-label={`Rebuild vectors ${file.name}`}
                    disabled={!isConnected || busyAction !== null}
                    onClick={() => void onRunAction(file.id, "build")}
                  >
                    {actionBusy === "build" ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Sparkles className="size-4" />
                    )}
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

