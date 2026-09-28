import type { CitationItem } from "@/lib/api/types";

/** Count files cited in the answer, never retrieved but uncited chunks. */
export function formatSourceCount(_retrievalCount: number, citations: CitationItem[]): string {
  const count = new Set(citations.map((citation) => citation.drive_file_id)).size;
  return count === 0 ? "" : `Sources · ${count}`;
}
