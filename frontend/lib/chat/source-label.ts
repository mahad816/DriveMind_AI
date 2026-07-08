import type { CitationItem } from "@/lib/api/types";

/** Human-readable source count for answer metadata. */
export function formatSourceCount(retrievalCount: number, citations: CitationItem[]): string {
  const uniqueFiles = new Set(citations.map((c) => c.filename.trim().toLowerCase())).size;
  const count = Math.max(retrievalCount, uniqueFiles, citations.length);

  if (count === 0) return "No sources found";
  if (count === 1) return "Based on 1 source";
  return `Based on ${count} sources`;
}
