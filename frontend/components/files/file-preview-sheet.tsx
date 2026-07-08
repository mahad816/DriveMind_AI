"use client";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { FilePreviewPanel } from "@/components/files/file-preview-panel";
import type { DriveFileRead } from "@/lib/api/types";

type FilePreviewSheetProps = {
  file: DriveFileRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function FilePreviewSheet({ file, open, onOpenChange }: FilePreviewSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-lg">
        <SheetHeader className="sr-only">
          <SheetTitle>{file?.name ?? "File preview"}</SheetTitle>
          <SheetDescription>Preview and actions for the selected file.</SheetDescription>
        </SheetHeader>
        <div className="h-full overflow-y-auto p-4">
          <FilePreviewPanel file={file} className="min-h-[calc(100vh-2rem)] border-0" />
        </div>
      </SheetContent>
    </Sheet>
  );
}
