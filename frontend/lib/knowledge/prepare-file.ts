import {
  buildVectorIndex,
  chunkDocuments,
  ingestDriveFiles,
  pollUntilJobDone,
} from "@/lib/api/indexing";

/** Index a single file through ingest → chunk → build (fast path for one file). */
export async function prepareSingleFile(fileId: string): Promise<void> {
  const acceptedIngest = await ingestDriveFiles(fileId);
  await pollUntilJobDone(acceptedIngest.job_id, { timeoutMs: 120_000 });

  const acceptedChunk = await chunkDocuments(fileId);
  await pollUntilJobDone(acceptedChunk.job_id, { timeoutMs: 60_000 });

  const acceptedBuild = await buildVectorIndex(fileId);
  await pollUntilJobDone(acceptedBuild.job_id, { timeoutMs: 120_000 });
}
