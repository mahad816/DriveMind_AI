import type { DriveFileRead, DriveFileStatus } from "@/lib/api/types";
import type { Tone } from "@/components/ui/controls";
import { preparationEligibility } from "@/lib/knowledge/single-file-preparation";

export const fileStatusWord = (status: DriveFileStatus) => ({
  indexed: "Ready", discovered: "Not prepared", indexing: "Preparing", failed: "Couldn't prepare", skipped: "No readable text",
}[status]);
export const fileStatusTone = (status: DriveFileStatus): Tone => ({
  indexed: "ready", discovered: "neutral", indexing: "working", failed: "fault", skipped: "caution",
} as const)[status];

/** What a status means for the person, in one or two sentences. */
export function fileStatusExplanation(file: DriveFileRead): string {
  switch (file.status) {
    case "indexed": return "Ready. Answers can cite this document.";
    case "discovered": return supported(file) ? "Not prepared yet. Select it to make it available to answers." : "DriveMind can't read this file type yet, so it can't be prepared.";
    case "indexing": return "Being prepared now. It becomes ready when the last step finishes.";
    case "failed": return "DriveMind couldn't read this document. Your Drive wasn't changed. Trying again isn't available yet.";
    case "skipped": return "No readable text was found, so it was skipped. Scanned PDFs and images of text are the usual cause.";
  }
}

/** Why a file cannot be selected, in plain words, or null when it can (the kept controller's rule decides). */
export function selectionBlocker(file: DriveFileRead): string | null {
  const reason = preparationEligibility(file);
  if (!reason) return null;
  if (file.status === "indexed") return "Already ready.";
  if (file.status === "indexing") return "Already being prepared.";
  if (file.status === "failed") return "Couldn't be prepared before; trying again isn't available yet.";
  if (file.status === "skipped") return "No readable text was found.";
  if (!supported(file)) return "This file type isn't supported.";
  return "This document can't be selected right now.";
}
const supported = (file: DriveFileRead) => preparationEligibility({ ...file, status: "discovered" }) === null;

export function fileTypeName(mime: string): string {
  if (mime === "application/vnd.google-apps.document") return "Google Doc";
  if (mime === "application/vnd.google-apps.spreadsheet") return "Google Sheet";
  if (mime === "application/vnd.google-apps.presentation") return "Google Slides";
  if (mime === "application/pdf") return "PDF";
  if (mime.includes("wordprocessingml")) return "Word";
  if (mime.includes("spreadsheetml")) return "Excel";
  if (mime.includes("presentationml")) return "PowerPoint";
  if (mime === "text/csv") return "CSV";
  if (mime === "text/markdown") return "Markdown";
  if (mime.startsWith("text/")) return "Text";
  if (mime.startsWith("image/")) return "Image";
  if (mime.includes("zip")) return "Archive";
  return "File";
}

/** Google's own file id is needed; DriveMind's internal id never builds a Drive link. */
export const driveUrl = (googleFileId: string) => `https://drive.google.com/file/d/${encodeURIComponent(googleFileId)}/view`;
