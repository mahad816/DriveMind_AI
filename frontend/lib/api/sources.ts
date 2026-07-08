import { apiFetch } from "@/lib/api/client";
import type { SourceChunkRead } from "@/lib/api/types";

export async function getSourceChunk(chunkId: string): Promise<SourceChunkRead> {
  return apiFetch<SourceChunkRead>(`/sources/${encodeURIComponent(chunkId)}`);
}
