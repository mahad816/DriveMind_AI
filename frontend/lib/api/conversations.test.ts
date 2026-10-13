import { afterEach, beforeEach, expect, it, vi } from "vitest";
// Synthetic fixture serialized by the current backend ConversationRead,
// ConversationDetail and ConversationSubmission Pydantic models (no database).
import fixture from "./fixtures/conversation-backend-dto.json";
import { createConversation, listConversations, getConversation, renameConversation, deleteConversation, submitTurn, getTurnStatus, interruptExpiredTurn, ConversationApiError, ConversationProtocolError, UncertainSubmissionError, } from "./conversations";
import { invalidateSessionRequests, setSessionOwner } from "./session-events";
const owner = "00000000-0000-0000-0000-000000000065";
const other = "00000000-0000-0000-0000-000000000066";
const cid = fixture.metadata.id, tid = fixture.submission.turn.id;
const payload = { client_request_id: fixture.submission.turn.client_request_id,
  question: fixture.submission.turn.question, expected_content_version: 0 };
const session = { kind: "GOOGLE_ACCOUNT", user_id: owner, csrf_token: "synthetic-csrf" };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
function http(body: unknown, status = 200) {
  const fetch = vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith("/auth/session") ? json(session) : status === 204 ? new Response(null, { status }) : json(body, status)));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
function state(status: "RUNNING" | "FAILED" | "INTERRUPTED", expired = false) {
  return { ...fixture.submission.turn, status, answer: null, query_id: null, citations: [],
    finished_at: status === "RUNNING" ? null : fixture.submission.turn.finished_at,
    error_code: status === "RUNNING" ? null : status === "FAILED" ? "TURN_FAILED" : "TURN_INTERRUPTED",
    execution_expired: expired, retrieval_count: 0 };
}
beforeEach(() => { setSessionOwner(owner); invalidateSessionRequests(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); setSessionOwner(null); });
const operations = [
  { name: "create", method: "POST", path: "/conversations", body: { create_request_id: payload.client_request_id, title: "Synthetic conversation" }, response: fixture.metadata, status: 201,
    call: (signal: AbortSignal) => createConversation({ create_request_id: payload.client_request_id, title: "Synthetic conversation" }, signal) },
  { name: "list", method: "GET", path: "/conversations?limit=10&cursor=opaque%2Bcursor", body: undefined,
    response: { conversations: [fixture.metadata], next_cursor: null }, status: 200,
    call: (signal: AbortSignal) => listConversations({ limit: 10, cursor: "opaque+cursor" }, signal) },
  { name: "detail", method: "GET", path: `/conversations/${cid}?limit=10&before_sequence=9223372036854775807`, body: undefined,
    response: fixture.detail, status: 200,
    call: (signal: AbortSignal) => getConversation(cid, { limit: 10, before_sequence: "9223372036854775807" }, signal) },
  { name: "rename", method: "PATCH", path: `/conversations/${cid}`, body: { title: "Renamed", expected_metadata_version: 1 }, response: { ...fixture.metadata, title: "Renamed", metadata_version: 2 }, status: 200,
    call: (signal: AbortSignal) => renameConversation(cid, { title: "Renamed", expected_metadata_version: 1 }, signal) },
  { name: "delete", method: "DELETE", path: `/conversations/${cid}`, body: { expected_metadata_version: 1 }, response: null, status: 204,
    call: (signal: AbortSignal) => deleteConversation(cid, 1, signal) },
  { name: "submit", method: "POST", path: `/conversations/${cid}/turns`, body: payload, response: fixture.submission, status: 200,
    call: (signal: AbortSignal) => submitTurn(cid, payload, signal) },
  { name: "status", method: "GET", path: `/conversations/${cid}/turns/${tid}`, body: undefined, response: fixture.submission.turn, status: 200,
    call: (signal: AbortSignal) => getTurnStatus(cid, tid, signal) },
  { name: "interrupt", method: "POST", path: `/conversations/${cid}/turns/${tid}/interrupt`, body: {}, response: state("INTERRUPTED"), status: 200,
    call: (signal: AbortSignal) => interruptExpiredTurn(cid, tid, signal) },
];
it.each(operations)("$name matches the mounted backend contract and authenticated fetch", async (op) => {
  const fetch = http(op.response, op.status);
  const signal = new AbortController().signal;
  const result = await op.call(signal);
  const [url, options] = fetch.mock.calls.at(-1)!;
  expect(url).toBe(`/api/v1${op.path}`);
  expect(options.method ?? "GET").toBe(op.method);
  expect(options).toMatchObject({ credentials: "include", cache: "no-store", signal });
  expect(options.body).toBe(op.body === undefined ? undefined : JSON.stringify(op.body));
  if (op.method !== "GET") {
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/auth/session");
    expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: "include", cache: "no-store" });
    expect(options.headers).toMatchObject({ "X-CSRF-Token": "synthetic-csrf", "Content-Type": "application/json" });
    // Browsers, not editable JavaScript account fields, generate Origin.
    expect(options.headers).not.toHaveProperty("Origin");
  }
  if (op.name === "delete")
    expect(result).toBeUndefined();
  expect(url).not.toContain(encodeURIComponent(payload.question));
});
it.each([200, 201] as const)("preserves creation HTTP %s", async (status) => {
  http(fixture.metadata, status);
  expect(await createConversation({ create_request_id: payload.client_request_id })).toEqual({ httpStatus: status, conversation: fixture.metadata });
});
it("parses the actual Pydantic DTO fixture without duplicating answer/citation identities", async () => {
  http(fixture.detail);
  const detail = await getConversation(cid);
  expect(detail).toEqual(fixture.detail);
  expect(detail.turns[0].question).toBe(payload.question);
  expect(detail.turns[0].citations[0].chunk_id).toBe(fixture.submission.turn.citations[0].chunk_id);
});
it.each(["RUNNING", "FAILED", "INTERRUPTED"] as const)("preserves durable %s replay without inventing an answer", async (status) => {
  http({ turn: state(status), replayed: true }, status === "RUNNING" ? 202 : 200);
  const result = await submitTurn(cid, payload);
  expect(result).toMatchObject({ httpStatus: status === "RUNNING" ? 202 : 200, replayed: true, turn: { status, answer: null, query_id: null } });
});
it("preserves a durable HTTP 503 receipt as an observable server error", async () => {
  http({ turn: state("FAILED"), replayed: false }, 503);
  try {
    await submitTurn(cid, payload);
    throw new Error("must reject");
  }
  catch (error) {
    expect(error).toBeInstanceOf(ConversationApiError);
    expect(error).toMatchObject({ status: 503, category: "unavailable", outcomeUnknown: false,
      submission: { conversation_id: cid, payload }, receipt: { turn: { status: "FAILED" } } });
  }
});
it.each([401, 403, 404, 409, 422, 503])("HTTP %s is never success and retains safe structured information", async (status) => {
  http({ detail: "private-provider-stack-trace-do-not-reflect" }, status);
  const pending = submitTurn(cid, payload);
  await expect(pending).rejects.toMatchObject({ status, outcomeUnknown: true, submission: { conversation_id: cid, payload } });
  await expect(pending).rejects.not.toHaveProperty("message", "private-provider-stack-trace-do-not-reflect");
});
it.each([
  ["Conversation metadata version is stale.", "metadata_version_conflict"],
  ["Conversation request conflicts with existing state.", "request_conflict"],
])("keeps meaningful safe 409 category %s", async (detail, category) => {
  http({ detail }, 409);
  await expect(renameConversation(cid, { title: "Name", expected_metadata_version: 1 })).rejects.toMatchObject({ status: 409, detail, category });
});
it.each(["network", "abort"])("%s after dispatch preserves the exact request for reconciliation", async (failure) => {
  const controller = new AbortController();
  const fetch = vi.fn().mockImplementation(async (url: string) => {
    if (url.endsWith("/auth/session"))
      return json(session);
    if (failure === "abort")
      controller.abort();
    throw failure === "abort" ? new DOMException("aborted", "AbortError") : new TypeError("network private diagnostics");
  });
  vi.stubGlobal("fetch", fetch);
  await expect(submitTurn(cid, payload, controller.signal)).rejects.toMatchObject({
    name: "UncertainSubmissionError", outcomeUnknown: true, reason: failure === "abort" ? "aborted" : "transport",
    submission: { conversation_id: cid, payload },
  });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][1].signal).toBe(controller.signal);
});
it("a lost acknowledgement can be reconciled with the same caller request key", async () => {
  const fetch = http(fixture.submission);
  fetch.mockImplementationOnce(async () => json(session)).mockRejectedValueOnce(new TypeError("lost acknowledgement"));
  await expect(submitTurn(cid, payload)).rejects.toBeInstanceOf(UncertainSubmissionError);
  const replay = await submitTurn(cid, payload);
  expect(replay.turn.id).toBe(tid);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/turns")).every(([, options]) => options.body === JSON.stringify(payload))).toBe(true);
});
it("session switch during CSRF inspection prevents conversation dispatch", async () => {
  const fetch = vi.fn().mockImplementation(async () => {
    setSessionOwner(other);
    invalidateSessionRequests();
    return json({ ...session, user_id: other });
  });
  vi.stubGlobal("fetch", fetch);
  await expect(submitTurn(cid, payload)).rejects.toMatchObject({ category: "session_changed" });
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("late success is discarded after an application-session generation change", async () => {
  const fetch = vi.fn().mockImplementation(async () => {
    setSessionOwner(other);
    invalidateSessionRequests();
    return json(fixture.detail);
  });
  vi.stubGlobal("fetch", fetch);
  await expect(getConversation(cid)).rejects.toMatchObject({ category: "session_changed" });
});
it.each([0, 101, 1.5, NaN, Infinity])("rejects invalid page limit %s before HTTP", async (limit) => {
  const fetch = http({});
  await expect(listConversations({ limit })).rejects.toMatchObject({ status: 422 });
  await expect(getConversation(cid, { limit })).rejects.toMatchObject({ status: 422 });
  expect(fetch).not.toHaveBeenCalled();
});
it.each(["9223372036854775808", "-1", "0", "01", "1.5", Number.MAX_SAFE_INTEGER + 1])("rejects invalid or imprecise turn cursor %s", async (before_sequence) => {
  const fetch = http({});
  await expect(getConversation(cid, { before_sequence })).rejects.toMatchObject({ status: 422 });
  expect(fetch).not.toHaveBeenCalled();
});
it("does not send arbitrary option fields or question text in query strings", async () => {
  const fetch = http({});
  await expect(listConversations({ question: "private question" } as never)).rejects.toMatchObject({ status: 422 });
  await expect(submitTurn(cid, { ...payload, owner_id: other } as never)).rejects.toMatchObject({ status: 422 });
  expect(fetch).not.toHaveBeenCalled();
});
it.each([
  null,
  { ...fixture.submission, turn: { ...fixture.submission.turn, answer: null } },
  { ...fixture.submission, turn: { ...state("RUNNING"), answer: "invented success" } },
  { ...fixture.submission, turn: { ...fixture.submission.turn, client_request_id: other } },
  { ...fixture.submission, turn: { ...fixture.submission.turn, execution_expired: true } },
  { ...fixture.submission, turn: { ...fixture.submission.turn, citations: [{ ...fixture.submission.turn.citations[0], score: 2 }] } },
])("malformed submission %j remains uncertain", async (value) => {
  http(value);
  await expect(submitTurn(cid, payload)).rejects.toMatchObject({ name: "UncertainSubmissionError", reason: "protocol" });
});
it.each([
  [202, fixture.submission],
  [200, { turn: state("RUNNING"), replayed: true }],
  [202, { turn: state("RUNNING"), replayed: false }],
  [201, fixture.submission],
])("rejects inconsistent submission status %s", async (status, value) => {
  http(value, status as number);
  await expect(submitTurn(cid, payload)).rejects.toBeInstanceOf(UncertainSubmissionError);
});
it("malformed list/detail and imprecise database numbers fail closed", async () => {
  http({ conversations: [fixture.metadata], next_cursor: 5 });
  await expect(listConversations()).rejects.toBeInstanceOf(ConversationProtocolError);
  http({ ...fixture.detail, conversation: { ...fixture.metadata, content_version: Number.MAX_SAFE_INTEGER + 1 } });
  await expect(getConversation(cid)).rejects.toBeInstanceOf(ConversationProtocolError);
  http({ ...fixture.detail, next_before_sequence: 2 });
  await expect(getConversation(cid)).rejects.toBeInstanceOf(ConversationProtocolError);
});
it("bounded turn pages preserve ordered continuation", async () => {
  http({ ...fixture.detail, next_before_sequence: 1 });
  expect((await getConversation(cid, { limit: 1 })).next_before_sequence).toBe(1);
});
it("non-JSON success and broken JSON never become a completed result", async () => {
  const fetch = http({});
  fetch.mockImplementation(async (url: string) => url.endsWith("/auth/session") ? json(session) : new Response("bad", { status: 200 }));
  await expect(submitTurn(cid, payload)).rejects.toBeInstanceOf(UncertainSubmissionError);
  fetch.mockImplementation(async (url: string) => url.endsWith("/auth/session") ? json(session) : new Response("{", { status: 200, headers: { "Content-Type": "application/json" } }));
  await expect(submitTurn(cid, payload)).rejects.toBeInstanceOf(UncertainSubmissionError);
});
it("adapter never reads or writes browser persistence", async () => {
  const forbidden = vi.fn(() => { throw new Error("storage forbidden"); });
  vi.stubGlobal("localStorage", { getItem: forbidden, setItem: forbidden, removeItem: forbidden });
  vi.stubGlobal("sessionStorage", { getItem: forbidden, setItem: forbidden });
  http(fixture.submission);
  await submitTurn(cid, payload);
  expect(forbidden).not.toHaveBeenCalled();
});
it("demo mode refuses the normal adapter before any HTTP request", async () => {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
  const adapter = await import("./conversations");
  const fetch = http({});
  await expect(adapter.listConversations()).rejects.toMatchObject({ status: 403 });
  expect(fetch).not.toHaveBeenCalled();
  vi.resetModules();
});
it("snapshots a submission before asynchronous CSRF inspection", async () => {
  const value = { ...payload };
  const fetch = vi.fn().mockImplementation(async (url: string) => {
    if (url.endsWith("/auth/session")) {
      value.client_request_id = other;
      value.question = "Changed during wait";
      return json(session);
    }
    return json(fixture.submission);
  });
  vi.stubGlobal("fetch", fetch);
  expect((await submitTurn(cid, value)).turn.client_request_id).toBe(payload.client_request_id);
  expect(fetch.mock.calls[1][1].body).toBe(JSON.stringify(payload));
});
it("an abort-resistant HTTP response does not imply successful client delivery", async () => {
  const controller = new AbortController();
  const fetch = vi.fn().mockImplementation(async (url: string) => {
    if (url.endsWith("/auth/session"))
      return json(session);
    controller.abort();
    return json(fixture.submission);
  });
  vi.stubGlobal("fetch", fetch);
  await expect(submitTurn(cid, payload, controller.signal)).rejects.toMatchObject({ outcomeUnknown: true, reason: "aborted" });
});
it("late error-body parsing cannot deliver an old 401 as B's authentication failure", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => {
      setSessionOwner(other);
      invalidateSessionRequests();
      return { detail: "Session expired" };
    } });
  vi.stubGlobal("fetch", fetch);
  await expect(getConversation(cid)).rejects.toMatchObject({ status: 409, category: "session_changed" });
});
it.each(["\u0085", "\u001c", "\u3000"])("matches backend question whitespace canonicalization %j", async (whitespace) => {
  http(fixture.submission);
  const question = whitespace + payload.question + whitespace;
  expect((await submitTurn(cid, { ...payload, question })).turn.question).toBe(payload.question);
});
it("unknown session state refuses private access without reading browser storage", async () => {
  setSessionOwner(null);
  const fetch = http({});
  await expect(listConversations()).rejects.toMatchObject({ status: 401 });
  expect(fetch).not.toHaveBeenCalled();
});
it("a mismatched inspected owner cannot supply another account's mutation CSRF", async () => {
  const fetch = vi.fn().mockImplementation(async (url: string) => url.endsWith("/auth/session") ? json({ ...session, user_id: other }) : json(fixture.metadata, 201));
  vi.stubGlobal("fetch", fetch);
  await expect(createConversation({ create_request_id: payload.client_request_id })).rejects.toMatchObject({ category: "session_changed" });
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("unavailable HTTP without a receipt does not invent durable failure", async () => {
  http({ detail: "Conversation storage is temporarily unavailable." }, 503);
  await expect(submitTurn(cid, payload)).rejects.toMatchObject({ status: 503, outcomeUnknown: true, receipt: undefined });
});
it("read transport and JSON errors expose safe diagnostics only", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private stacktrace document")));
  await expect(getConversation(cid)).rejects.toThrow("Conversation request could not be completed.");
});
it("malformed or mismatched 503 receipts never authorize retry as a known failure", async () => {
  http({ ...fixture.submission, turn: { ...state("FAILED"), client_request_id: other } }, 503);
  await expect(submitTurn(cid, payload)).rejects.toMatchObject({ outcomeUnknown: true, reason: "protocol" });
  http({ turn: null, replayed: false }, 503);
  await expect(submitTurn(cid, payload)).rejects.toMatchObject({ outcomeUnknown: true, reason: "protocol" });
});
it("a 200 non-replay FAILED result contradicts backend submission behavior", async () => {
  http({ turn: state("FAILED"), replayed: false });
  await expect(submitTurn(cid, payload)).rejects.toMatchObject({ outcomeUnknown: true, reason: "protocol" });
});
it("cancellation during CSRF inspection cancels that wait without dispatching a mutation", async () => {
  const controller = new AbortController();
  const fetch = vi.fn().mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
    expect(init.signal).toBeDefined();
    init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
  }));
  vi.stubGlobal("fetch", fetch);
  const pending = submitTurn(cid, payload, controller.signal);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ reason: "aborted", outcomeUnknown: true });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/v1/auth/session");
});

it("a 503 RUNNING receipt remains pending with an unknown terminal outcome", async () => {
  http({ turn: state("RUNNING", true), replayed: false }, 503);
  await expect(submitTurn(cid, payload)).rejects.toMatchObject({
    status: 503, outcomeUnknown: true, receipt: { turn: { status: "RUNNING", execution_expired: true } },
  });
});
