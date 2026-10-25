import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "./fixtures/conversation-backend-dto.json";
import { submitTurn, ConversationApiError, UncertainSubmissionError } from "./conversations";
import { invalidateSessionRequests, setSessionOwner, sessionRevision, SESSION_INVALID_EVENT } from "./session-events";

const owner = "00000000-0000-0000-0000-000000000065";
const cid = fixture.metadata.id;
const body = { client_request_id: fixture.submission.turn.client_request_id, question: fixture.submission.turn.question, expected_content_version: 0 };
const running = { ...fixture.submission, turn: { ...fixture.submission.turn, status: "RUNNING", answer: null, citations: [], query_id: null, finished_at: null, error_code: null, retrieval_count: 0 } };
const encoder = new TextEncoder();
const frame = (event: string, data: unknown) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

function mock() {
  let pipe!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(controller) { pipe = controller; } });
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/auth/session")) return new Response(JSON.stringify({ kind: "GOOGLE_ACCOUNT", user_id: owner, csrf_token: "synthetic-csrf" }), { headers: { "content-type": "application/json" } });
    init?.signal?.addEventListener("abort", () => pipe.error(new DOMException("Aborted", "AbortError")), { once: true });
    return new Response(stream, { headers: { "content-type": "text/event-stream" } });
  });
  vi.stubGlobal("fetch", fetch);
  return { pipe, fetch };
}
beforeEach(() => { setSessionOwner(owner); invalidateSessionRequests(); vi.stubEnv("NEXT_PUBLIC_CHAT_STREAMING_ENABLED", "true"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); setSessionOwner(null); });

it.each([undefined, "false"])("keeps the existing non-streaming endpoint when the build flag is %s", async flag => {
  vi.stubEnv("NEXT_PUBLIC_CHAT_STREAMING_ENABLED", flag);
  const fetch = vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith("/auth/session")
    ? { kind: "GOOGLE_ACCOUNT", user_id: owner, csrf_token: "synthetic-csrf" } : fixture.submission), { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  expect(await submitTurn(cid, body)).toMatchObject({ httpStatus: 200, turn: { status: "COMPLETED" } });
  expect(fetch.mock.calls.at(-1)?.[0]).toBe(`/api/v1/conversations/${cid}/turns`);
});

it("delivers multiple provisional updates before the canonical completed receipt, with auth and CSRF", async () => {
  const { pipe, fetch } = mock(), progress = vi.fn(), accepted = vi.fn();
  const answer = submitTurn(cid, body, undefined, progress, accepted);
  pipe.enqueue(frame("accepted", running));
  await vi.waitFor(() => expect(accepted).toHaveBeenCalledWith(running.turn));
  pipe.enqueue(frame("state", { phase: "searching" }));
  pipe.enqueue(frame("provisional", { text: "First " }));
  await vi.waitFor(() => expect(progress).toHaveBeenCalledWith({ phase: "generating", text: "First " }));
  pipe.enqueue(frame("provisional", { text: "First second " }));
  await vi.waitFor(() => expect(progress).toHaveBeenCalledWith({ phase: "generating", text: "First second " }));
  pipe.enqueue(frame("complete", { receipt: fixture.submission, http_status: 200 }));
  expect((await answer).turn).toEqual(fixture.submission.turn);
  expect(fetch.mock.calls.at(-1)).toMatchObject([`/api/v1/conversations/${cid}/turns/stream`, { credentials: "include", headers: { "X-CSRF-Token": "synthetic-csrf" } }]);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(progress.mock.calls.at(-1)?.[0].text).toBe("");
});

it("handles UTF-8 and SSE frames split at arbitrary network byte boundaries", async () => {
  const { pipe } = mock(), progress = vi.fn();
  const answer = submitTurn(cid, body, undefined, progress);
  const bytes = new Uint8Array([...frame("accepted", running), ...frame("provisional", { text: "Résumé " }), ...frame("complete", { receipt: fixture.submission, http_status: 200 })]);
  for (const byte of bytes) pipe.enqueue(Uint8Array.of(byte));
  await answer;
  expect(progress).toHaveBeenCalledWith({ phase: "generating", text: "Résumé " });
});

it.each(["disconnect", "cancel", "account", "invalid citation"])("rejects %s and clears provisional content", async reason => {
  const { pipe } = mock(), progress = vi.fn(), abort = new AbortController();
  const answer = submitTurn(cid, body, abort.signal, progress);
  const rejected = expect(answer).rejects.toBeInstanceOf(reason === "account" ? ConversationApiError : UncertainSubmissionError);
  pipe.enqueue(frame("accepted", running)); pipe.enqueue(frame("provisional", { text: "Unverified " }));
  await vi.waitFor(() => expect(progress).toHaveBeenCalledWith({ phase: "generating", text: "Unverified " }));
  if (reason === "cancel") abort.abort();
  else if (reason === "account") { setSessionOwner("00000000-0000-0000-0000-000000000066"); invalidateSessionRequests(); pipe.enqueue(frame("provisional", { text: "stale " })); }
  else if (reason === "invalid citation") pipe.enqueue(frame("complete", { receipt: { ...fixture.submission, turn: { ...fixture.submission.turn, citations: [{ ...fixture.submission.turn.citations[0], chunk_id: "invalid" }] } }, http_status: 200 }));
  else pipe.close();
  await rejected;
  expect(progress.mock.calls.at(-1)?.[0].text).toBe("");
  expect(progress).not.toHaveBeenCalledWith({ phase: "generating", text: "stale " });
});

it("preserves failed durable receipts without treating partial text as a valid answer", async () => {
  const { pipe } = mock(), progress = vi.fn();
  const answer = submitTurn(cid, body, undefined, progress);
  pipe.enqueue(frame("accepted", running)); pipe.enqueue(frame("provisional", { text: "Discard me " }));
  pipe.enqueue(frame("error", { receipt: { ...running, turn: { ...running.turn, status: "FAILED", finished_at: fixture.submission.turn.finished_at, error_code: "TURN_FAILED" } }, http_status: 503 }));
  await expect(answer).rejects.toMatchObject({ status: 503, receipt: { turn: { status: "FAILED", answer: null } } });
  expect(progress.mock.calls.at(-1)?.[0].text).toBe("");
});

it("rejects an unauthorized HTTP response before consuming a stream", async () => {
  const { fetch } = mock();
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({ kind: "GOOGLE_ACCOUNT", user_id: owner, csrf_token: "csrf" }), { headers: { "content-type": "application/json" } }));
  fetch.mockImplementationOnce(async () => new Response(JSON.stringify({ detail: "Forbidden" }), { status: 403, headers: { "content-type": "application/json" } }));
  await expect(submitTurn(cid, body)).rejects.toBeInstanceOf(ConversationApiError);
});

it("replaying the same running attempt only returns a receipt", async () => {
  const { pipe } = mock(), progress = vi.fn();
  const answer = submitTurn(cid, body, undefined, progress);
  pipe.enqueue(frame("receipt", { receipt: { ...running, replayed: true }, http_status: 202 }));
  expect(await answer).toMatchObject({ httpStatus: 202, replayed: true, turn: { status: "RUNNING", answer: null } });
  expect(progress).not.toHaveBeenCalledWith(expect.objectContaining({ phase: "generating" }));
});

it("reconciles an interrupted replay as its canonical outcome rather than a service error", async () => {
  const { pipe } = mock();
  const answer = submitTurn(cid, body);
  pipe.enqueue(frame("receipt", { receipt: { replayed: true, turn: { ...running.turn,
    status: "INTERRUPTED", finished_at: fixture.submission.turn.finished_at, error_code: "TURN_INTERRUPTED" } }, http_status: 200 }));
  expect(await answer).toMatchObject({ httpStatus: 200, replayed: true, turn: { status: "INTERRUPTED", answer: null } });
});

it("invalidates the existing session and discards provisional content on mid-stream expiry", async () => {
  vi.stubGlobal("window", new EventTarget());
  const { pipe, fetch } = mock(), progress = vi.fn(), invalid = vi.fn();
  window.addEventListener(SESSION_INVALID_EVENT, invalid);
  try {
    const revision = sessionRevision();
    const answer = submitTurn(cid, body, undefined, progress);
    const rejected = expect(answer).rejects.toMatchObject({ status: 401, category: "unauthenticated", submission: { conversation_id: cid, payload: body } });
    pipe.enqueue(frame("accepted", running));
    pipe.enqueue(frame("provisional", { text: "Discard this unverified answer " }));
    await vi.waitFor(() => expect(progress).toHaveBeenCalledWith({ phase: "generating", text: "Discard this unverified answer " }));
    pipe.enqueue(frame("error", { code: "SESSION_EXPIRED", message: "Your session expired. Sign in again to continue." }));
    await rejected;
    expect(invalid).toHaveBeenCalledTimes(1);
    expect(sessionRevision()).toBe(revision + 1);
    expect(progress.mock.calls.at(-1)?.[0].text).toBe("");
    expect(fetch).toHaveBeenCalledTimes(2); // Session preflight + original POST only.
  } finally { window.removeEventListener(SESSION_INVALID_EVENT, invalid); }
});

it("does not let an expired stream invalidate a replacement account's session", async () => {
  vi.stubGlobal("window", new EventTarget());
  const { pipe } = mock(), invalid = vi.fn();
  window.addEventListener(SESSION_INVALID_EVENT, invalid);
  try {
    const answer = submitTurn(cid, body);
    const rejected = expect(answer).rejects.toMatchObject({ status: 409, category: "session_changed" });
    pipe.enqueue(frame("accepted", running));
    await vi.waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2));
    setSessionOwner("00000000-0000-0000-0000-000000000066");
    invalidateSessionRequests();
    pipe.enqueue(frame("error", { code: "SESSION_EXPIRED", message: "Your session expired." }));
    await rejected;
    expect(invalid).not.toHaveBeenCalled();
  } finally { window.removeEventListener(SESSION_INVALID_EVENT, invalid); }
});
