import {
  buildVectorIndex,
  chunkDocuments,
  ingestDriveFiles,
  pollUntilJobDone,
} from "@/lib/api/indexing";

import { ApiError } from "@/lib/api/errors";
import { sessionRevision } from "@/lib/api/session-events";

/** Index a single file through ingest → chunk → build (fast path for one file). */
export async function prepareSingleFile(fileId: string): Promise<void> {
  const revision = sessionRevision();
  const checkSession = () => { if (revision !== sessionRevision()) throw new ApiError(401, "Your session changed. Preparation stopped."); };
  const acceptedIngest = await ingestDriveFiles(fileId);
  await pollUntilJobDone(acceptedIngest.job_id, { timeoutMs: 120_000 });

  checkSession();
  const acceptedChunk = await chunkDocuments(fileId);
  await pollUntilJobDone(acceptedChunk.job_id, { timeoutMs: 60_000 });

  checkSession();
  const acceptedBuild = await buildVectorIndex(fileId);
  await pollUntilJobDone(acceptedBuild.job_id, { timeoutMs: 120_000 });
}
