/** PostgreSQL adapter only: no cache, storage, polling or mounted UI.
 * Requires the existing provider's verified owner. Backend cookies still authorize.
 * Submission errors preserve a frozen original payload; never retry with a new key
 * until its outcome is reconciled. 503 receipts are errors, not successful answers.
 * before_sequence accepts exact decimal BIGINT strings. JSON versions/sequences
 * must be JS-safe integers; reject precision loss rather than silently rounding.
 */
import { inspectApplicationSession } from "@/lib/api/auth";
import { apiFetchWithStatus, buildQueryString } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import type { CitationItem } from "@/lib/api/types";
import { DEMO_MODE, questionCharacters } from "@/lib/demo";
export type ConversationMetadata = {
  id: string;
  title: string;
  title_is_manual: boolean;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  metadata_version: number;
  content_version: number;
};
type TurnBase = {
  id: string;
  client_request_id: string;
  sequence: number;
  question: string;
  operation: "ASK" | "RETRY" | "REGENERATE";
  source_turn_id: string | null;
  created_at: string;
  updated_at: string;
  retrieval_count: number;
};
export type StoredTurn = TurnBase & ({
  status: "COMPLETED";
  finished_at: string;
  error_code: null;
  query_id: string;
  answer: string;
  citations: CitationItem[];
} | {
  status: "RUNNING";
  finished_at: null;
  error_code: null;
  query_id: null;
  answer: null;
  citations: [];
} | {
  status: "FAILED";
  finished_at: string;
  error_code: "TURN_FAILED";
  query_id: null;
  answer: null;
  citations: [];
} | {
  status: "INTERRUPTED";
  finished_at: string;
  error_code: "TURN_INTERRUPTED";
  query_id: null;
  answer: null;
  citations: [];
});
export type TurnStatus = StoredTurn & {
  execution_expired: boolean;
};
export type ConversationPage = {
  conversations: ConversationMetadata[];
  next_cursor: string | null;
};
export type ConversationDetail = {
  conversation: ConversationMetadata;
  turns: StoredTurn[];
  next_before_sequence: number | null;
};
export type TurnReceipt = {
  turn: TurnStatus;
  replayed: boolean;
};
export type CreateConversationRequest = {
  create_request_id: string;
  title?: string;
};
export type SubmitTurnRequest = {
  client_request_id: string;
  question: string;
  expected_content_version: number;
};
export type CreateConversationResult = {
  httpStatus: 200 | 201;
  conversation: ConversationMetadata;
};
export type SubmitTurnResult = TurnReceipt & {
  httpStatus: 200 | 202;
};
export type ConversationErrorCategory = "unauthenticated" | "forbidden" | "not_found" | "metadata_version_conflict" | "request_conflict" | "invalid_request" | "unavailable" | "session_changed" | "http_error";
export type SubmissionIdentity = {
  readonly conversation_id: string;
  readonly payload: Readonly<SubmitTurnRequest>;
};
/** Safe HTTP details, with an optional authoritative 503 turn receipt. */
export class ConversationApiError extends ApiError {
  constructor(status: number, readonly category: ConversationErrorCategory, readonly submission?: SubmissionIdentity, readonly receipt?: TurnReceipt) {
    const messages: Record<ConversationErrorCategory, string> = {
      unauthenticated: "Sign in to access conversations.", forbidden: "Conversation request is forbidden.",
      not_found: "Conversation not found.", metadata_version_conflict: "Conversation metadata version is stale.",
      request_conflict: "Conversation request conflicts with existing state.",
      invalid_request: "Invalid conversation request.", unavailable: "Conversation service is unavailable.",
      session_changed: "Your application session changed. Verify your account again.",
      http_error: "Conversation request was rejected.",
    };
    super(status, messages[category]);
    this.name = "ConversationApiError";
  }
  /** Missing receipts and RUNNING receipts do not establish a terminal outcome. */
  get outcomeUnknown(): boolean { return this.submission !== undefined && (this.receipt === undefined || this.receipt.turn.status === "RUNNING"); }
}
export class ConversationProtocolError extends Error {
  constructor() { super("Conversation response is incompatible or malformed."); this.name = "ConversationProtocolError"; }
}
/** Cancellation/network/protocol failure never proves server generation stopped. */
export class UncertainSubmissionError extends Error {
  readonly outcomeUnknown = true;
  constructor(readonly submission: SubmissionIdentity, readonly reason: "transport" | "aborted" | "protocol") {
    super("The submission outcome is unknown. Reconcile the original request before retrying.");
    this.name = "UncertainSubmissionError";
  }
}
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const BIGINT_MAX = BigInt("9223372036854775807");
const fail = (): never => { throw new ConversationProtocolError(); };
function object(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return fail();
  const result = value as Record<string, unknown>;
  if (Object.keys(result).some(key => !keys.includes(key)) || keys.some(key => !(key in result)))
    return fail();
  return result;
}
function string(value: unknown, max: number): string {
  if (typeof value !== "string" || !value.length || questionCharacters(value) > max)
    return fail();
  return value;
}
function uuid(value: unknown): string {
  const id = string(value, 36);
  if (!UUID_PATTERN.test(id))
    return fail();
  return id;
}
function integer(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min || value > max)
    return fail();
  return value;
}
function boolean(value: unknown): boolean { if (typeof value !== "boolean")
  return fail(); return value; }
function date(value: unknown): string {
  const result = string(value, 64);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(result) || !Number.isFinite(Date.parse(result)))
    return fail();
  return result;
}
function array<T>(value: unknown, max: number, parse: (item: unknown) => T): T[] {
  if (!Array.isArray(value) || value.length > max)
    return fail();
  return value.map(parse);
}
function metadata(value: unknown): ConversationMetadata {
  const row = object(value, ["id", "title", "title_is_manual", "created_at", "updated_at", "last_activity_at", "metadata_version", "content_version"]);
  return { id: uuid(row.id), title: string(row.title, 256), title_is_manual: boolean(row.title_is_manual),
    created_at: date(row.created_at), updated_at: date(row.updated_at), last_activity_at: date(row.last_activity_at),
    metadata_version: integer(row.metadata_version, 1), content_version: integer(row.content_version) };
}
function citation(value: unknown): CitationItem {
  const row = object(value, ["chunk_id", "drive_file_id", "filename", "snippet", "score"]);
  if (row.score !== null && (typeof row.score !== "number" || !Number.isFinite(row.score) || row.score < 0 || row.score > 1))
    return fail();
  return { chunk_id: uuid(row.chunk_id), drive_file_id: uuid(row.drive_file_id), filename: string(row.filename, 1024),
    snippet: string(row.snippet, 8000), score: row.score as number | null };
}
const TURN_KEYS = ["id", "client_request_id", "sequence", "question", "operation", "source_turn_id", "status", "created_at", "updated_at", "finished_at", "error_code", "query_id", "answer", "citations", "retrieval_count"];
function turn(value: unknown, withStatus: false): StoredTurn;
function turn(value: unknown, withStatus: true): TurnStatus;
function turn(value: unknown, withStatus: boolean): StoredTurn | TurnStatus {
  const row = object(value, withStatus ? [...TURN_KEYS, "execution_expired"] : TURN_KEYS);
  if (!["ASK", "RETRY", "REGENERATE"].includes(String(row.operation)))
    return fail();
  const base: TurnBase = { id: uuid(row.id), client_request_id: uuid(row.client_request_id), sequence: integer(row.sequence, 1),
    question: string(row.question, 8000), operation: row.operation as TurnBase["operation"],
    source_turn_id: row.source_turn_id === null ? null : uuid(row.source_turn_id),
    created_at: date(row.created_at), updated_at: date(row.updated_at), retrieval_count: integer(row.retrieval_count) };
  let parsed: StoredTurn;
  if (row.status === "COMPLETED") {
    if (row.error_code !== null)
      return fail();
    parsed = { ...base, status: "COMPLETED", finished_at: date(row.finished_at), error_code: null,
      query_id: uuid(row.query_id), answer: string(row.answer, 131072), citations: array(row.citations, 64, citation) };
  }
  else {
    if (row.query_id !== null || row.answer !== null || !Array.isArray(row.citations) || row.citations.length)
      return fail();
    if (row.status === "RUNNING") {
      if (row.finished_at !== null || row.error_code !== null)
        return fail();
      parsed = { ...base, status: "RUNNING", finished_at: null, error_code: null, query_id: null, answer: null, citations: [] };
    }
    else if (row.status === "FAILED" || row.status === "INTERRUPTED") {
      const status = row.status;
      const error = status === "FAILED" ? "TURN_FAILED" : "TURN_INTERRUPTED";
      if (row.error_code !== error)
        return fail();
      parsed = status === "FAILED"
        ? { ...base, status, finished_at: date(row.finished_at), error_code: "TURN_FAILED", query_id: null, answer: null, citations: [] }
        : { ...base, status, finished_at: date(row.finished_at), error_code: "TURN_INTERRUPTED", query_id: null, answer: null, citations: [] };
    }
    else
      return fail();
  }
  if (!withStatus)
    return parsed;
  const expired = boolean(row.execution_expired);
  if (parsed.status !== "RUNNING" && expired)
    return fail();
  return { ...parsed, execution_expired: expired };
}
function receipt(value: unknown): TurnReceipt {
  const row = object(value, ["turn", "replayed"]);
  return { turn: turn(row.turn, true), replayed: boolean(row.replayed) };
}
// Match Python str.strip used by the accepted backend (not JavaScript's BOM trim).
function canonicalQuestion(value: string): string {
  return value.replace(/^[\u0009-\u000D\u001C-\u0020\u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+|[\u0009-\u000D\u001C-\u0020\u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+$/g, "");
}
function writable(value: object, keys: readonly string[]): void {
  if (Object.keys(value).some(key => !keys.includes(key)))
    fail();
}
function input(check: () => void): void {
  try {
    check();
  }
  catch {
    throw new ConversationApiError(422, "invalid_request");
  }
}
function context(): {
  owner: string;
  revision: number;
} {
  if (DEMO_MODE)
    throw new ConversationApiError(403, "forbidden");
  const owner = sessionOwner();
  if (!owner)
    throw new ConversationApiError(401, "unauthenticated");
  return { owner, revision: sessionRevision() };
}
function current(ctx: ReturnType<typeof context>): void {
  if (ctx.owner !== sessionOwner() || ctx.revision !== sessionRevision())
    throw new ConversationApiError(409, "session_changed");
}
function category(error: ApiError): ConversationErrorCategory {
  if (error instanceof ConversationApiError)
    return error.category;
  if (error.status === 409 && error.body === undefined)
    return "session_changed";
  if (error.status === 409) {
    const detail = error.body && typeof error.body === "object" && "detail" in error.body ? error.body.detail : null;
    return detail === "Conversation metadata version is stale." ? "metadata_version_conflict" : "request_conflict";
  }
  return ({ 401: "unauthenticated", 403: "forbidden", 404: "not_found", 422: "invalid_request", 503: "unavailable" } as Record<number, ConversationErrorCategory>)[error.status] ?? "http_error";
}
async function send(path: string, signal?: AbortSignal, mutation?: {
  method: string;
  body: unknown;
}): Promise<{
  status: number;
  data: unknown;
}> {
  const ctx = context();
  try {
    signal?.throwIfAborted();
    let headers: Record<string, string> | undefined;
    if (mutation) {
      const session = await inspectApplicationSession(signal);
      current(ctx);
      if (session.user_id !== ctx.owner)
        throw new ConversationApiError(409, "session_changed");
      signal?.throwIfAborted();
      headers = { "X-CSRF-Token": session.csrf_token };
    }
    current(ctx);
    const response = await apiFetchWithStatus<unknown>(path, { cache: "no-store", signal,
      ...(mutation ? { method: mutation.method, body: JSON.stringify(mutation.body), headers } : {}) });
    current(ctx);
    signal?.throwIfAborted();
    return response;
  }
  catch (error) {
    // A 401 intentionally invalidates the local revision. Preserve that rejection.
    if (error instanceof ApiError && error.status === 401) {
      const nowOwner = sessionOwner();
      if (nowOwner !== null && (nowOwner !== ctx.owner || sessionRevision() !== ctx.revision + 1))
        throw new ConversationApiError(409, "session_changed");
    }
    else
      current(ctx);
    if (error instanceof ApiError && !(error instanceof ConversationApiError))
      throw new ConversationApiError(error.status, category(error), undefined, error.status === 503 && path.endsWith("/turns") && error.body !== null && typeof error.body === "object" && "turn" in error.body ? receipt(error.body) : undefined);
    if (error instanceof ConversationApiError)
      throw error;
    if (error instanceof SyntaxError)
      throw new ConversationProtocolError();
    if (signal?.aborted || (error instanceof Error && error.name === "AbortError"))
      throw new DOMException("Conversation request wait was cancelled.", "AbortError");
    throw new Error("Conversation request could not be completed.");
  }
}
function status(response: {
  status: number;
}, allowed: readonly number[]): void {
  if (!allowed.includes(response.status))
    fail();
}
function pageLimit(limit: number | undefined): void { if (limit !== undefined)
  integer(limit, 1, 100); }
function sequence(value: number | string | undefined): string | undefined {
  if (value === undefined)
    return undefined;
  const text = typeof value === "number" ? String(integer(value, 1)) : value;
  if (!/^[1-9]\d{0,18}$/.test(text) || BigInt(text) > BIGINT_MAX)
    return fail();
  return text;
}
export async function createConversation(body: CreateConversationRequest, signal?: AbortSignal): Promise<CreateConversationResult> {
  input(() => { writable(body, ["create_request_id", "title"]); uuid(body.create_request_id); if (body.title !== undefined) {
    string(body.title, 256);
    if (!canonicalQuestion(body.title))
      fail();
  } });
  const response = await send("/conversations", signal, { method: "POST", body: { ...body } });
  status(response, [200, 201]);
  return { httpStatus: response.status as 200 | 201, conversation: metadata(response.data) };
}
export async function listConversations(options: {
  limit?: number;
  cursor?: string;
} = {}, signal?: AbortSignal): Promise<ConversationPage> {
  input(() => { writable(options, ["limit", "cursor"]); pageLimit(options.limit); if (options.cursor !== undefined)
    string(options.cursor, 512); });
  const response = await send(`/conversations${buildQueryString({ limit: options.limit, cursor: options.cursor })}`, signal);
  status(response, [200]);
  const row = object(response.data, ["conversations", "next_cursor"]);
  return { conversations: array(row.conversations, options.limit ?? 30, metadata), next_cursor: row.next_cursor === null ? null : string(row.next_cursor, 512) };
}
export async function getConversation(id: string, options: {
  limit?: number;
  before_sequence?: number | string;
} = {}, signal?: AbortSignal): Promise<ConversationDetail> {
  let before: string | undefined;
  input(() => { writable(options, ["limit", "before_sequence"]); uuid(id); pageLimit(options.limit); before = sequence(options.before_sequence); });
  const response = await send(`/conversations/${id}${buildQueryString({ limit: options.limit, before_sequence: before })}`, signal);
  status(response, [200]);
  const row = object(response.data, ["conversation", "turns", "next_before_sequence"]);
  const conversation = metadata(row.conversation);
  if (conversation.id.toLowerCase() !== id.toLowerCase())
    return fail();
  const turns = array(row.turns, options.limit ?? 50, value => turn(value, false));
  if (turns.some((value, index) => (index > 0 && turns[index - 1].sequence >= value.sequence) || (before !== undefined && BigInt(value.sequence) >= BigInt(before))))
    return fail();
  const next = row.next_before_sequence === null ? null : integer(row.next_before_sequence, 1);
  if (next !== null && (!turns.length || next !== turns[0].sequence || turns.length !== (options.limit ?? 50)))
    return fail();
  return { conversation, turns, next_before_sequence: next };
}
export async function renameConversation(id: string, body: {
  title: string;
  expected_metadata_version: number;
}, signal?: AbortSignal): Promise<ConversationMetadata> {
  input(() => { writable(body, ["title", "expected_metadata_version"]); uuid(id); string(body.title, 256); if (!canonicalQuestion(body.title))
    fail(); integer(body.expected_metadata_version, 1, 2147483647); });
  const response = await send(`/conversations/${id}`, signal, { method: "PATCH", body: { ...body } });
  status(response, [200]);
  const parsed = metadata(response.data);
  if (parsed.id.toLowerCase() !== id.toLowerCase())
    fail();
  return parsed;
}
export async function deleteConversation(id: string, expectedMetadataVersion: number, signal?: AbortSignal): Promise<void> {
  input(() => { uuid(id); integer(expectedMetadataVersion, 1, 2147483647); });
  const response = await send(`/conversations/${id}`, signal, { method: "DELETE", body: { expected_metadata_version: expectedMetadataVersion } });
  status(response, [204]);
}
export async function getTurnStatus(id: string, turnId: string, signal?: AbortSignal): Promise<TurnStatus> {
  input(() => { uuid(id); uuid(turnId); });
  const response = await send(`/conversations/${id}/turns/${turnId}`, signal);
  status(response, [200]);
  const parsed = turn(response.data, true);
  if (parsed.id.toLowerCase() !== turnId.toLowerCase())
    fail();
  return parsed;
}
export async function interruptExpiredTurn(id: string, turnId: string, signal?: AbortSignal): Promise<TurnStatus> {
  input(() => { uuid(id); uuid(turnId); });
  const response = await send(`/conversations/${id}/turns/${turnId}/interrupt`, signal, { method: "POST", body: {} });
  status(response, [200]);
  const parsed = turn(response.data, true);
  if (parsed.id.toLowerCase() !== turnId.toLowerCase() || parsed.status === "RUNNING")
    fail();
  return parsed;
}
export async function submitTurn(id: string, body: SubmitTurnRequest, signal?: AbortSignal): Promise<SubmitTurnResult> {
  input(() => { writable(body, ["client_request_id", "question", "expected_content_version"]); uuid(id); uuid(body.client_request_id); string(body.question, 4000); if (!canonicalQuestion(body.question))
    fail(); integer(body.expected_content_version); });
  const submission = Object.freeze({ conversation_id: id, payload: Object.freeze({ ...body }) });
  const original = submission.payload;
  try {
    const response = await send(`/conversations/${id}/turns`, signal, { method: "POST", body: original });
    status(response, [200, 202]);
    const parsed = receipt(response.data);
    if (parsed.turn.client_request_id.toLowerCase() !== original.client_request_id.toLowerCase()
      || parsed.turn.question !== canonicalQuestion(original.question)
      || (response.status === 202 && (parsed.turn.status !== "RUNNING" || !parsed.replayed))
      || (response.status === 200 && (parsed.turn.status === "RUNNING" || (parsed.turn.status !== "COMPLETED" && !parsed.replayed))))
      fail();
    return { ...parsed, httpStatus: response.status as 200 | 202 };
  }
  catch (error) {
    if (error instanceof ConversationApiError) {
      if (error.receipt && (error.receipt.turn.client_request_id.toLowerCase() !== original.client_request_id.toLowerCase() || error.receipt.turn.question !== canonicalQuestion(original.question) || error.receipt.turn.status === "COMPLETED"))
        throw new UncertainSubmissionError(submission, "protocol");
      throw new ConversationApiError(error.status, error.category, submission, error.receipt);
    }
    throw new UncertainSubmissionError(submission, error instanceof ConversationProtocolError ? "protocol" : signal?.aborted ? "aborted" : "transport");
  }
}
