/** Shared API types mirroring backend Pydantic schemas. */

export type DriveFileStatus =
  | "discovered"
  | "indexing"
  | "indexed"
  | "failed"
  | "skipped";

export type IndexingJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "canceled";

export type HealthResponse = {
  status: string;
};

export type ReadinessResponse = {
  status: string;
  database: string;
};

export type CitationItem = {
  chunk_id: string;
  drive_file_id: string;
  filename: string;
  snippet: string;
  score: number | null;
};

export type ChatRequest = {
  question: string;
};

export type ChatResponse = {
  query_id: string;
  user_id: string;
  answer: string;
  citations: CitationItem[];
  retrieval_count: number;
  message: string;
};

export type SourceChunkRead = {
  chunk_id: string;
  drive_file_id: string;
  filename: string;
  mime_type: string;
  chunk_index: number;
  text: string;
  modified_at: string;
};

export type DriveFileRead = {
  id: string;
  user_id: string;
  drive_file_id: string;
  name: string;
  mime_type: string;
  folder_path: string | null;
  modified_at: string;
  indexed_at: string | null;
  status: DriveFileStatus;
  created_at: string;
  updated_at: string;
};

export type DriveFileListResponse = {
  files: DriveFileRead[];
  total: number;
};

export type IndexingJobRead = {
  id: string;
  user_id: string;
  status: IndexingJobStatus;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type DriveSyncStatusResponse = {
  connected: boolean;
  job: IndexingJobRead | null;
};

export type DriveSyncResponse = {
  job_id: string;
  user_id: string;
  mode: string;
  created: number;
  updated: number;
  unchanged: number;
  removed: number;
  total_seen: number;
  message: string;
};

export type IngestionResponse = {
  job_id: string;
  user_id: string;
  ingested: number;
  unchanged: number;
  failed: number;
  skipped: number;
  total: number;
  message: string;
};

export type ChunkingResponse = {
  job_id: string;
  user_id: string;
  chunked: number;
  unchanged: number;
  skipped: number;
  total: number;
  message: string;
};

export type IndexBuildResponse = {
  job_id: string;
  user_id: string;
  embedded: number;
  unchanged: number;
  skipped: number;
  failed: number;
  removed: number;
  total: number;
  message: string;
};

export type OAuthCallbackResponse = {
  status: string;
  message: string;
  user_id: string;
  email: string;
};

export type FastApiValidationError = {
  loc: (string | number)[];
  msg: string;
  type: string;
};

export type FastApiErrorBody = {
  detail: string | FastApiValidationError[];
};
