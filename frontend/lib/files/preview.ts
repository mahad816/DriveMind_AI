import { getDriveFileContentUrl } from "@/lib/api/files";
import { truncatePreview } from "@/lib/files/utils";

const TEXT_LIKE_PREFIXES = ["text/", "application/json", "application/xml"];

function isTextLikeMime(mimeType: string): boolean {
  return TEXT_LIKE_PREFIXES.some((prefix) => mimeType.startsWith(prefix));
}

export async function fetchFileTextPreview(
  fileId: string,
  mimeType: string,
): Promise<string | null> {
  if (!isTextLikeMime(mimeType)) {
    return null;
  }

  try {
    const response = await fetch(getDriveFileContentUrl(fileId));
    if (!response.ok) {
      return null;
    }
    const text = await response.text();
    const normalized = text.replace(/\s+/g, " ").trim();
    if (!normalized) {
      return null;
    }
    return truncatePreview(normalized);
  } catch {
    return null;
  }
}
