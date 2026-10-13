import { notifySessionInvalid, sessionRevision } from "@/lib/api/session-events";
import { getDriveFileContentUrl } from "@/lib/api/files";
import { DEMO_MODE } from "@/lib/demo";
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
    const revision = sessionRevision();
    const response = await fetch(getDriveFileContentUrl(fileId), { credentials: "include" });
    if (revision !== sessionRevision()) return null;
    if (response.status === 401) notifySessionInvalid();
    if (!response.ok) {
      return null;
    }
    const text = await response.text();
    if (revision !== sessionRevision()) return null;
    if (DEMO_MODE) return text.trim() || null;
    const normalized = text.replace(/\s+/g, " ").trim();
    if (!normalized) {
      return null;
    }
    return truncatePreview(normalized);
  } catch {
    return null;
  }
}
