"use client";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { DEMO_MODE } from "@/lib/demo";
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
      <SheetContent side="right" className={cn("w-full gap-0 p-0 sm:max-w-lg", !DEMO_MODE && "data-[side=right]:w-[calc(100%-1rem)] sm:data-[side=right]:w-full")}>
        <SheetHeader className="sr-only">
          <SheetTitle>{file?.name ?? "File preview"}</SheetTitle>
          <SheetDescription>Preview and actions for the selected file.</SheetDescription>
        </SheetHeader>
        <div className={DEMO_MODE ? "h-full overflow-y-auto p-4" : "min-h-0 flex-1 overflow-hidden px-4 pb-4 pt-14"}>
          <FilePreviewPanel file={file} className={DEMO_MODE ? "min-h-[calc(100vh-2rem)] border-0" : "border-0"} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
