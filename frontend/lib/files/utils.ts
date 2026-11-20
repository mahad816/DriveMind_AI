import { DEMO_MODE } from "@/lib/demo";
import type { DriveFileRead } from "@/lib/api/types";
import { FileImage, FileSpreadsheet, FileText, FileType, Presentation } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export function driveFileUrl(driveFileId: string): string {
  return `https://drive.google.com/file/d/${encodeURIComponent(driveFileId)}/view`;
}

export function formatFileDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function fileTypeLabel(mimeType: string): string {
  if (mimeType === "application/pdf") return "PDF";
  // Spreadsheet and presentation first: their Office MIME types also contain "document".
  if (mimeType.includes("spreadsheet")) return "Spreadsheet";
  if (mimeType.includes("presentation")) return "Presentation";
  if (mimeType.includes("document")) return "Document";
  if (mimeType.startsWith("image/")) return "Image";
  if (mimeType.startsWith("text/")) return "Text";
  return "File";
}

export function fileTypeIcon(mimeType: string): LucideIcon {
  if (mimeType.includes("spreadsheet")) return FileSpreadsheet;
  if (mimeType.includes("presentation")) return Presentation;
  if (mimeType.startsWith("image/")) return FileImage;
  if (mimeType === "application/pdf" || mimeType.includes("document") || mimeType.startsWith("text/")) {
    return FileText;
  }
  return FileType;
}

export function buildAskAboutFileHref(file: Pick<DriveFileRead, "name">): string {
  return DEMO_MODE ? `/chat?ask=${encodeURIComponent(`Tell me about "${file.name}"`)}` : "/chat";
}

export function truncatePreview(text: string, maxChars = 480): string {
  const trimmed = text.trim();
  if (trimmed.length <= maxChars) return trimmed;
  return `${trimmed.slice(0, maxChars)}…`;
}
