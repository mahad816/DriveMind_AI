import {
  buildVectorIndex,
  chunkDocuments,
  ingestDriveFiles,
  pollUntilJobDone,
} from "@/lib/api/indexing";

/** Index a single file through ingest → chunk → build (fast path for one file). */
export async function prepareSingleFile(fileId: string): Promise<void> {
  const beforeIngest = new Date();
  await ingestDriveFiles(fileId);
  await pollUntilJobDone(beforeIngest, { timeoutMs: 120_000 });

  const beforeChunk = new Date();
  await chunkDocuments(fileId);
  await pollUntilJobDone(beforeChunk, { timeoutMs: 60_000 });

  const beforeBuild = new Date();
  await buildVectorIndex(fileId);
  await pollUntilJobDone(beforeBuild, { timeoutMs: 120_000 });
}
