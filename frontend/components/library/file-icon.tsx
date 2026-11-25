import { FileArchive, FileImage, FileSpreadsheet, FileText, File, Presentation } from "lucide-react";
import { cn } from "@/lib/utils";

/** Type at a glance; the type is also written next to the name, so the icon is never the only signal. */
export function FileTypeIcon({ mime, className }: { mime: string; className?: string }) {
  const Icon = mime.includes("spreadsheet") || mime === "text/csv" ? FileSpreadsheet
    : mime.includes("presentation") ? Presentation
    : mime.startsWith("image/") ? FileImage
    : mime.includes("zip") ? FileArchive
    : mime === "application/pdf" || mime.includes("document") || mime.startsWith("text/") ? FileText : File;
  return <Icon aria-hidden="true" strokeWidth={1.5} className={cn("size-4 shrink-0 text-faint", className)} />;
}
