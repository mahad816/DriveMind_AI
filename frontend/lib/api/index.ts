export { getGoogleAuthUrl } from "@/lib/api/auth";
export { askQuestion } from "@/lib/api/chat";
export { apiFetch, buildQueryString, formatApiErrorDetail } from "@/lib/api/client";
export { apiBaseUrl, backendUrl, serverApiBaseUrl } from "@/lib/api/config";
export { ApiError, isApiError } from "@/lib/api/errors";
export { getDriveFileContentUrl, listDriveFiles } from "@/lib/api/files";
export { getHealth, getReadiness } from "@/lib/api/health";
export {
  buildVectorIndex,
  chunkDocuments,
  getDriveSyncStatus,
  ingestDriveFiles,
  syncDriveMetadata,
} from "@/lib/api/indexing";
export { getSourceChunk } from "@/lib/api/sources";
export type * from "@/lib/api/types";
