import { StrictMode } from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "@/lib/api/fixtures/conversation-backend-dto.json";
import * as api from "@/lib/api/conversations";
import { setSessionOwner, sessionOwner, invalidateSessionRequests } from "@/lib/api/session-events";
import { ServerConversationController } from "./server-controller";
import type { ConversationTransport } from "./server-controller";
import { ApplicationSessionProvider } from "@/components/providers/application-session-provider";
import { ServerConversationsProvider, useServerConversations } from "@/components/providers/server-conversations-provider";
const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", async (importOriginal) => ({ ...await importOriginal<typeof import("@/lib/demo")>(), get DEMO_MODE() { return mode.demo; } }));
const A = "00000000-0000-0000-0000-000000000065", B = "00000000-0000-0000-0000-000000000066";
const X = fixture.metadata.id, Y = "00000000-0000-0000-0000-000000000201";
const meta = (id = X, title = "A title"): api.ConversationMetadata => ({ ...fixture.metadata, id, title });
function turn(status: api.StoredTurn["status"] = "COMPLETED", overrides = {}): api.TurnStatus {
  return { ...fixture.submission.turn, status, ...(status === "COMPLETED" ? {} : {
      answer: null, query_id: null, citations: [], retrieval_count: 0,
      finished_at: status === "RUNNING" ? null : fixture.submission.turn.finished_at,
      error_code: status === "RUNNING" ? null : status === "FAILED" ? "TURN_FAILED" : "TURN_INTERRUPTED",
    }), ...overrides } as api.TurnStatus;
}
function detail(id = X, turns: api.StoredTurn[] = []): api.ConversationDetail {
  return { conversation: meta(id), turns, next_before_sequence: null };
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function transport() {
  return {
    listConversations: vi.fn<ConversationTransport["listConversations"]>().mockResolvedValue({ conversations: [meta(), meta(Y)], next_cursor: null }),
    getConversation: vi.fn<ConversationTransport["getConversation"]>().mockImplementation(async (id) => detail(id)),
    createConversation: vi.fn<ConversationTransport["createConversation"]>().mockResolvedValue({ httpStatus: 201, conversation: meta() }),
    renameConversation: vi.fn<ConversationTransport["renameConversation"]>().mockResolvedValue({ ...meta(), title: "Server renamed", metadata_version: 2 }),
    deleteConversation: vi.fn<ConversationTransport["deleteConversation"]>().mockResolvedValue(undefined),
    submitTurn: vi.fn<ConversationTransport["submitTurn"]>().mockImplementation(async (_id, body) => ({ httpStatus: 200, replayed: false,
      turn: turn("COMPLETED", { question: body.question.trim(), client_request_id: body.client_request_id }) })),
    getTurnStatus: vi.fn<ConversationTransport["getTurnStatus"]>().mockResolvedValue(turn()),
    interruptExpiredTurn: vi.fn<ConversationTransport["interruptExpiredTurn"]>().mockResolvedValue(turn("INTERRUPTED")),
  };
}
let controllers: ServerConversationController[];
beforeEach(() => { controllers = []; mode.demo = false; setSessionOwner(A); invalidateSessionRequests(); });
afterEach(() => {
  cleanup();
  for (const controller of controllers)
    controller.dispose();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  mode.demo = false;
  setSessionOwner(null);
});
async function ready() {
  const rpc = transport(), controller = new ServerConversationController(rpc);
  controllers.push(controller);
  controller.connect();
  await controller.initialize();
  return { rpc, controller };
}
function switchOwner(owner: string | null) { setSessionOwner(owner); invalidateSessionRequests(); }
it("initializes only from verified session authority and reloads server state for the same owner", async () => {
  const { rpc, controller } = await ready();
  expect(controller.getSnapshot().ownerId).toBe(A);
  expect(controller.getSnapshot().conversations.map(row => row.id)).toEqual([Y, X]);
  rpc.listConversations.mockResolvedValue({ conversations: [meta(X, "Server after reload")], next_cursor: null });
  await controller.initialize();
  expect(controller.getSnapshot().conversations[0].title).toBe("Server after reload");
  switchOwner(null);
  expect(controller.getSnapshot().conversations).toEqual([]);
  await controller.initialize();
  expect(rpc.listConversations).toHaveBeenCalledTimes(2);
});
it("create selects the canonical server ID rather than the creation request UUID", async () => {
  const { rpc, controller } = await ready();
  await controller.create("My title");
  const requestId = rpc.createConversation.mock.calls[0][0].create_request_id;
  expect(requestId).not.toBe(X);
  expect(controller.getSnapshot().selectedId).toBe(X);
  expect(controller.getSnapshot().conversation?.id).toBe(X);
});
it("uncertain creation reconciles with the same immutable key", async () => {
  const { rpc, controller } = await ready();
  rpc.createConversation.mockRejectedValueOnce(new TypeError("lost ack"));
  await controller.create("Title");
  expect(controller.getSnapshot().creation?.uncertain).toBe(true);
  await controller.retryCreate();
  expect(rpc.createConversation.mock.calls[0][0]).toEqual(rpc.createConversation.mock.calls[1][0]);
  expect(controller.getSnapshot().creation).toBeNull();
});
it("a late creation cannot replace a newer selection", async () => {
  const { rpc, controller } = await ready();
  const result = deferred<api.CreateConversationResult>();
  rpc.createConversation.mockReturnValueOnce(result.promise);
  const pending = controller.create();
  await controller.select(Y);
  result.resolve({ httpStatus: 201, conversation: meta() });
  await pending;
  expect(controller.getSnapshot().selectedId).toBe(Y);
});
it("list pages deduplicate and preserve exact server microsecond ordering", async () => {
  const { rpc, controller } = await ready();
  const latest = { ...meta(X), last_activity_at: "2026-10-13T12:00:00.000002Z" };
  const older = { ...meta(Y), last_activity_at: "2026-10-13T12:00:00.000001Z" };
  rpc.listConversations.mockResolvedValueOnce({ conversations: [latest], next_cursor: "page2" });
  await controller.refreshList();
  rpc.listConversations.mockResolvedValueOnce({ conversations: [latest, older], next_cursor: null });
  await controller.loadMoreConversations();
  expect(rpc.listConversations.mock.calls.at(-1)![0]).toEqual({ limit: 30, cursor: "page2" });
  expect(controller.getSnapshot().conversations.map(row => row.id)).toEqual([X, Y]);
});
it("turn pages preserve server order and canonical IDs without treating the first page as all history", async () => {
  const { rpc, controller } = await ready();
  const newest = turn("COMPLETED", { id: Y, sequence: 2 });
  rpc.getConversation.mockResolvedValueOnce({ ...detail(), turns: [newest], next_before_sequence: 2 });
  await controller.select(X);
  expect(controller.getSnapshot().nextTurnCursor).toBe(2);
  rpc.getConversation.mockResolvedValueOnce({ ...detail(), turns: [turn(), newest], next_before_sequence: null });
  await controller.loadOlderTurns();
  expect(rpc.getConversation.mock.calls.at(-1)![1]).toEqual({ limit: 50, before_sequence: 2 });
  expect(controller.getSnapshot().turns.map(row => row.sequence)).toEqual([1, 2]);
});
it("A to B clears state synchronously and discards A's late list", async () => {
  const { rpc, controller } = await ready();
  const old = deferred<api.ConversationPage>();
  rpc.listConversations.mockReturnValueOnce(old.promise);
  const pending = controller.refreshList();
  switchOwner(B);
  expect(controller.getSnapshot().ownerId).toBeNull();
  expect(controller.getSnapshot().conversations).toEqual([]);
  rpc.listConversations.mockResolvedValueOnce({ conversations: [meta(Y, "B title")], next_cursor: null });
  await controller.initialize();
  old.resolve({ conversations: [meta(X, "A secret")], next_cursor: null });
  await pending;
  expect(controller.getSnapshot().ownerId).toBe(B);
  expect(controller.getSnapshot().conversations.map(row => row.title)).toEqual(["B title"]);
});
it.each(["success", "401"])("late A detail %s cannot alter B state or authority", async (kind) => {
  const { rpc, controller } = await ready();
  const old = deferred<api.ConversationDetail>();
  rpc.getConversation.mockReturnValueOnce(old.promise);
  const pending = controller.select(X);
  switchOwner(B);
  await controller.initialize();
  await controller.select(Y);
  if (kind === "success")
    old.resolve({ ...detail(), turns: [turn("COMPLETED", { answer: "A_SECRET" })] });
  else
    old.reject(new api.ConversationApiError(401, "unauthenticated"));
  await pending;
  expect(sessionOwner()).toBe(B);
  expect(controller.getSnapshot().selectedId).toBe(Y);
  expect(JSON.stringify(controller.getSnapshot())).not.toContain("A_SECRET");
  expect(controller.getSnapshot().error).toBeNull();
});
it("out-of-order selection responses cannot overwrite the selected conversation", async () => {
  const { rpc, controller } = await ready();
  const old = deferred<api.ConversationDetail>();
  rpc.getConversation.mockReturnValueOnce(old.promise);
  const x = controller.select(X);
  await controller.select(Y);
  old.resolve({ ...detail(X), turns: [turn()] });
  await x;
  expect(controller.getSnapshot().selectedId).toBe(Y);
  expect(controller.getSnapshot().turns).toEqual([]);
});
it("reversed list requests keep the latest list", async () => {
  const { rpc, controller } = await ready();
  const old = deferred<api.ConversationPage>();
  rpc.listConversations.mockReturnValueOnce(old.promise);
  const first = controller.refreshList();
  rpc.listConversations.mockResolvedValueOnce({ conversations: [meta(Y, "New list")], next_cursor: null });
  await controller.refreshList();
  old.resolve({ conversations: [meta(X, "Old list")], next_cursor: null });
  await first;
  expect(controller.getSnapshot().conversations.map(row => row.title)).toEqual(["New list"]);
});
it("rename conflict reloads canonical metadata and never claims optimistic success", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  rpc.renameConversation.mockRejectedValueOnce(new api.ConversationApiError(409, "metadata_version_conflict"));
  rpc.getConversation.mockResolvedValueOnce({ ...detail(), conversation: { ...meta(), title: "Other device", metadata_version: 3 } });
  expect(await controller.rename(X, "My attempted title")).toBe(false);
  expect(controller.getSnapshot().conversation?.title).toBe("Other device");
  expect(controller.getSnapshot().error?.category).toBe("metadata_version_conflict");
});
it("older metadata cannot undo a successful rename", async () => {
  const { rpc, controller } = await ready();
  const old = deferred<api.ConversationPage>();
  rpc.listConversations.mockReturnValueOnce(old.promise);
  const refresh = controller.refreshList();
  await controller.rename(X, "New");
  old.resolve({ conversations: [meta()], next_cursor: null });
  await refresh;
  expect(controller.getSnapshot().conversations[0].title).toBe("Server renamed");
});
it("confirmed delete cannot be resurrected by stale list or detail", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const page = deferred<api.ConversationPage>(), loaded = deferred<api.ConversationDetail>();
  rpc.listConversations.mockReturnValueOnce(page.promise);
  const list = controller.refreshList();
  rpc.getConversation.mockReturnValueOnce(loaded.promise);
  const select = controller.reloadSelected();
  await controller.delete(X);
  expect(controller.getSnapshot().selectedId).toBeNull();
  page.resolve({ conversations: [meta()], next_cursor: null });
  loaded.resolve(detail(X, [turn()]));
  await Promise.all([list, select]);
  expect(controller.getSnapshot().conversations.some(row => row.id === X)).toBe(false);
  expect(controller.getSnapshot().turns).toEqual([]);
});
it.each(["rename", "delete"])("late A %s cannot change B's state", async (operation) => {
  const { rpc, controller } = await ready();
  const pending = deferred<api.ConversationMetadata | void>();
  if (operation === "rename")
    rpc.renameConversation.mockImplementationOnce(async () => await pending.promise as api.ConversationMetadata);
  else
    rpc.deleteConversation.mockImplementationOnce(async () => { await pending.promise; });
  const result = operation === "rename" ? controller.rename(X, "A new title") : controller.delete(X);
  switchOwner(B);
  await controller.initialize();
  pending.resolve(operation === "rename" ? meta(X, "A_SECRET") : undefined);
  await result;
  expect(controller.getSnapshot().ownerId).toBe(B);
  expect(controller.getSnapshot().conversations.length).toBe(2);
  expect(JSON.stringify(controller.getSnapshot())).not.toContain("A_SECRET");
});
it("lost acknowledgement reuses exactly one frozen UUID and payload, with one visible completed turn", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  rpc.submitTurn.mockRejectedValueOnce(new TypeError("lost ack"));
  await controller.submitQuestion("Original question");
  const first = rpc.submitTurn.mock.calls[0][1];
  expect(Object.isFrozen(first)).toBe(true);
  expect(controller.getSnapshot().submission?.phase).toBe("unknown");
  await controller.submitQuestion("Do not create another logical request");
  expect(rpc.submitTurn).toHaveBeenCalledTimes(1);
  await controller.reconcileSubmission();
  const second = rpc.submitTurn.mock.calls[1][1];
  expect(second).toBe(first);
  expect(controller.getSnapshot().turns).toHaveLength(1);
  expect(controller.getSnapshot().submission?.phase).toBe("completed");
  const receipt = controller.getSnapshot().submission!.turn!;
  rpc.getTurnStatus.mockResolvedValue(receipt);
  await controller.reconcileSubmission();
  expect(rpc.submitTurn).toHaveBeenCalledTimes(2);
  expect(controller.getSnapshot().turns).toHaveLength(1);
});
it.each(["success", "401"])("late A submission %s cannot enter B's view", async (kind) => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const old = deferred<api.SubmitTurnResult>();
  rpc.submitTurn.mockReturnValueOnce(old.promise);
  const pending = controller.submitQuestion("A question");
  const body = rpc.submitTurn.mock.calls[0][1];
  switchOwner(B);
  await controller.initialize();
  await controller.select(Y);
  if (kind === "success")
    old.resolve({ httpStatus: 200, replayed: false, turn: turn("COMPLETED", { answer: "A_SECRET", client_request_id: body.client_request_id }) });
  else
    old.reject(new api.ConversationApiError(401, "unauthenticated"));
  await pending;
  expect(sessionOwner()).toBe(B);
  expect(controller.getSnapshot().error).toBeNull();
  expect(controller.getSnapshot().submission).toBeNull();
  expect(JSON.stringify(controller.getSnapshot())).not.toContain("A_SECRET");
});
it("X generation completing while Y is selected cannot replace Y messages", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const old = deferred<api.SubmitTurnResult>();
  rpc.submitTurn.mockReturnValueOnce(old.promise);
  const pending = controller.submitQuestion("X question");
  const body = rpc.submitTurn.mock.calls[0][1];
  await controller.select(Y);
  old.resolve({ httpStatus: 200, replayed: false, turn: turn("COMPLETED", { question: body.question, client_request_id: body.client_request_id, answer: "X_SECRET" }) });
  await pending;
  expect(controller.getSnapshot().selectedId).toBe(Y);
  expect(controller.getSnapshot().turns).toEqual([]);
  expect(controller.getSnapshot().submission).toBeNull();
});
it("known RUNNING receipt uses status lookup and bounded polling to reach a terminal state", async () => {
  vi.useFakeTimers();
  const { rpc, controller } = await ready();
  await controller.select(X);
  rpc.submitTurn.mockImplementationOnce(async (_id, body) => ({ httpStatus: 202, replayed: true, turn: turn("RUNNING", { question: body.question, client_request_id: body.client_request_id }) }));
  await controller.submitQuestion("Question");
  const row = controller.getSnapshot().submission!.turn!;
  expect(row.answer).toBeNull();
  rpc.getTurnStatus.mockResolvedValueOnce(row).mockResolvedValueOnce(turn("COMPLETED", { question: row.question, client_request_id: row.client_request_id }));
  const polling = controller.pollTurn(row.id, { intervalMs: 100, maxAttempts: 2 });
  await vi.advanceTimersByTimeAsync(100);
  await polling;
  expect(controller.getSnapshot().submission?.phase).toBe("completed");
  expect(controller.getSnapshot().polling).toBe(false);
  expect(rpc.submitTurn).toHaveBeenCalledTimes(1);
  expect(rpc.getTurnStatus).toHaveBeenCalledTimes(2);
});
it.each(["FAILED", "INTERRUPTED"] as const)("%s is terminal with no fabricated answer", async (status) => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  rpc.submitTurn.mockImplementationOnce(async (_id, body) => { throw new api.ConversationApiError(503, "unavailable", undefined, { replayed: false, turn: turn(status, { client_request_id: body.client_request_id, question: body.question }) }); });
  await controller.submitQuestion("Question");
  expect(controller.getSnapshot().submission?.phase).toBe(status.toLowerCase());
  expect(controller.getSnapshot().turns[0].answer).toBeNull();
  expect(controller.getSnapshot().error?.category).toBe("unavailable");
});
it("expired RUNNING stops polling and requires explicit interruption", async () => {
  const { rpc, controller } = await ready();
  rpc.getConversation.mockResolvedValueOnce(detail(X, [turn("RUNNING")]));
  await controller.select(X);
  rpc.getTurnStatus.mockResolvedValue(turn("RUNNING", { execution_expired: true }));
  await controller.pollTurn(fixture.submission.turn.id);
  expect(rpc.interruptExpiredTurn).not.toHaveBeenCalled();
  expect(controller.getSnapshot().turns[0].status).toBe("RUNNING");
  await controller.interruptExpiredTurn(fixture.submission.turn.id);
  expect(controller.getSnapshot().turns[0].status).toBe("INTERRUPTED");
  expect(rpc.submitTurn).not.toHaveBeenCalled();
});
it("polling limit does not invent a failure, and disposal joins its cancelled timer", async () => {
  vi.useFakeTimers();
  const { rpc, controller } = await ready();
  await controller.select(X);
  rpc.getTurnStatus.mockResolvedValue(turn("RUNNING"));
  const poll = controller.pollTurn(fixture.submission.turn.id, { intervalMs: 100, maxAttempts: 2 });
  await vi.advanceTimersByTimeAsync(100);
  await poll;
  expect(rpc.getTurnStatus).toHaveBeenCalledTimes(2);
  expect(controller.getSnapshot().turns[0].status).toBe("RUNNING");
  const another = controller.pollTurn(fixture.submission.turn.id);
  await Promise.resolve();
  controller.dispose();
  await another;
  expect(controller.getSnapshot().ownerId).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});
it("cancelled submission remains uncertain and late success is discarded", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const old = deferred<api.SubmitTurnResult>();
  rpc.submitTurn.mockReturnValueOnce(old.promise);
  const pending = controller.submitQuestion("Question");
  const body = rpc.submitTurn.mock.calls[0][1];
  controller.cancelSubmission();
  expect(controller.getSnapshot().submission?.phase).toBe("unknown");
  old.resolve({ httpStatus: 200, replayed: false, turn: turn("COMPLETED", { client_request_id: body.client_request_id }) });
  await pending;
  expect(controller.getSnapshot().turns).toEqual([]);
  expect(controller.getSnapshot().submission?.phase).toBe("unknown");
});
it("generic 409 leaves the original logical request unresolved instead of guessing its cause", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  rpc.submitTurn.mockRejectedValueOnce(new api.ConversationApiError(409, "request_conflict"));
  await controller.submitQuestion("Question");
  expect(controller.getSnapshot().error?.category).toBe("request_conflict");
  expect(controller.getSnapshot().submission?.phase).toBe("unknown");
});
it("controller never accesses legacy browser storage", async () => {
  const forbidden = vi.fn(() => { throw new Error("Storage forbidden"); });
  vi.stubGlobal("localStorage", { getItem: forbidden, setItem: forbidden });
  vi.stubGlobal("sessionStorage", { getItem: forbidden, setItem: forbidden });
  const { controller } = await ready();
  await controller.select(X);
  await controller.submitQuestion("Question");
  expect(forbidden).not.toHaveBeenCalled();
});
it("normal controller stays inactive in demo", async () => {
  mode.demo = true;
  const { rpc, controller } = await ready();
  expect(rpc.listConversations).not.toHaveBeenCalled();
  await controller.create();
  expect(rpc.createConversation).not.toHaveBeenCalled();
  expect(controller.getSnapshot().ownerId).toBeNull();
});
it("the real session provider supplies one shared controller to independent React consumers", async () => {
  const rpc = transport();
  const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ kind: "GOOGLE_ACCOUNT", user_id: A, csrf_token: "synthetic" })));
  function Consumer({ label }: {
    label: string;
  }) { const { state } = useServerConversations(); return <p>{label}:{state.ownerId}:{state.conversations.length}</p>; }
  render(<StrictMode><ApplicationSessionProvider><ServerConversationsProvider transport={rpc}><Consumer label="chat"/><Consumer label="sidebar"/></ServerConversationsProvider></ApplicationSessionProvider></StrictMode>);
  await screen.findByText(`chat:${A}:2`);
  expect(screen.getByText(`sidebar:${A}:2`)).toBeInTheDocument();
  expect(rpc.listConversations).toHaveBeenCalledTimes(2);
  expect(rpc.listConversations.mock.calls[0][1]?.aborted).toBe(true);
  expect(rpc.listConversations.mock.calls[1][1]?.aborted).toBe(false);
  await act(async () => { switchOwner(null); });
  await waitFor(() => expect(screen.queryByText(`chat:${A}:2`)).toBeNull());
});
it("owner fence rejects A metadata refresh after B becomes verified", async () => {
  const { rpc, controller } = await ready();
  const started = deferred<void>(), old = deferred<api.ConversationDetail>();
  rpc.renameConversation.mockRejectedValueOnce(new api.ConversationApiError(409, "metadata_version_conflict"));
  rpc.getConversation.mockImplementationOnce(() => { started.resolve(); return old.promise; });
  const pending = controller.rename(X, "Attempted title");
  await started.promise;
  switchOwner(B);
  rpc.listConversations.mockResolvedValueOnce({ conversations: [meta(Y, "B title")], next_cursor: null });
  await controller.initialize();
  old.resolve({ ...detail(X), conversation: meta(X, "A_METADATA_SECRET") });
  await pending;
  expect(controller.getSnapshot().ownerId).toBe(B);
  expect(controller.getSnapshot().conversations.map(row => row.title)).toEqual(["B title"]);
});
it("completed receipt cannot be regressed by a late RUNNING history page", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const gen = deferred<api.SubmitTurnResult>(), read = deferred<api.ConversationDetail>();
  rpc.submitTurn.mockReturnValueOnce(gen.promise);
  const pending = controller.submitQuestion("Question");
  const body = rpc.submitTurn.mock.calls[0][1];
  rpc.getConversation.mockReturnValueOnce(read.promise);
  const loading = controller.reloadSelected();
  const completed = turn("COMPLETED", { question: body.question, client_request_id: body.client_request_id });
  gen.resolve({ httpStatus: 200, replayed: false, turn: completed });
  await pending;
  read.resolve(detail(X, [turn("RUNNING", { question: body.question, client_request_id: body.client_request_id })]));
  await loading;
  expect(controller.getSnapshot().turns).toHaveLength(1);
  expect(controller.getSnapshot().turns[0].status).toBe("COMPLETED");
});
it("404 for a conversation removes only that resource, while a missing turn does not delete a healthy conversation", async () => {
  const { rpc, controller } = await ready();
  rpc.getConversation.mockRejectedValueOnce(new api.ConversationApiError(404, "not_found"));
  await controller.select(X);
  expect(controller.getSnapshot().conversations.map(row => row.id)).toEqual([Y]);
  expect(controller.getSnapshot().selectedId).toBeNull();
  await controller.select(Y);
  rpc.getTurnStatus.mockRejectedValueOnce(new api.ConversationApiError(404, "not_found"));
  await controller.refreshTurn(fixture.submission.turn.id);
  expect(controller.getSnapshot().selectedId).toBe(Y);
  expect(controller.getSnapshot().conversations.map(row => row.id)).toEqual([Y]);
});
it("server-confirmed completion waits for refreshed content version before another new request", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const metadata = deferred<api.ConversationDetail>(), started = deferred<void>();
  rpc.getConversation.mockImplementationOnce(() => { started.resolve(); return metadata.promise; });
  const pending = controller.submitQuestion("Question one");
  await started.promise;
  expect(controller.getSnapshot().metadataLoading).toBe(true);
  await controller.submitQuestion("Question two");
  expect(rpc.submitTurn).toHaveBeenCalledTimes(1);
  metadata.resolve({ ...detail(), conversation: { ...meta(), content_version: 4 } });
  await pending;
  expect(controller.getSnapshot().metadataLoading).toBe(false);
  expect(controller.getSnapshot().conversation?.content_version).toBe(4);
});
it("selecting another conversation stops a pending poll without publishing its late result", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const old = deferred<api.TurnStatus>();
  rpc.getTurnStatus.mockReturnValueOnce(old.promise);
  const poll = controller.pollTurn(fixture.submission.turn.id);
  await controller.select(Y);
  old.resolve(turn());
  await poll;
  expect(controller.getSnapshot().turns).toEqual([]);
  expect(controller.getSnapshot().polling).toBe(false);
});
it("adapter protocol failures stay safe and do not invent a successful durable turn", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  rpc.submitTurn.mockRejectedValueOnce(new api.UncertainSubmissionError({ conversation_id: X, payload: {
      client_request_id: fixture.submission.turn.client_request_id, question: "Question", expected_content_version: 2,
    } }, "protocol"));
  await controller.submitQuestion("Question");
  expect(controller.getSnapshot().turns).toEqual([]);
  expect(controller.getSnapshot().submission?.phase).toBe("unknown");
  expect(controller.getSnapshot().error?.category).toBe("unavailable");
});
it("loaded server RUNNING work blocks a new local question until status is resolved", async () => {
  const { rpc, controller } = await ready();
  rpc.getConversation.mockResolvedValueOnce(detail(X, [turn("RUNNING")]));
  await controller.select(X);
  await controller.submitQuestion("Do not compete with another device");
  expect(rpc.submitTurn).not.toHaveBeenCalled();
  expect(controller.getSnapshot().error?.category).toBe("pending_submission");
});
it("status lookup exposes observed expiry for an existing server turn without a local request", async () => {
  const { rpc, controller } = await ready();
  rpc.getConversation.mockResolvedValueOnce(detail(X, [turn("RUNNING")]));
  await controller.select(X);
  expect(controller.getSnapshot().executionExpired[fixture.submission.turn.id]).toBeUndefined();
  rpc.getTurnStatus.mockResolvedValue(turn("RUNNING", { execution_expired: true }));
  await controller.refreshTurn(fixture.submission.turn.id);
  expect(controller.getSnapshot().executionExpired[fixture.submission.turn.id]).toBe(true);
  await controller.interruptExpiredTurn(fixture.submission.turn.id);
  expect(controller.getSnapshot().executionExpired[fixture.submission.turn.id]).toBe(false);
});
it("published snapshots and their canonical answer/citation objects are immutable", async () => {
  const { rpc, controller } = await ready();
  rpc.getConversation.mockResolvedValueOnce(detail(X, [turn()]));
  await controller.select(X);
  const snapshot = controller.getSnapshot();
  expect(Object.isFrozen(snapshot)).toBe(true);
  expect(Object.isFrozen(snapshot.conversation)).toBe(true);
  expect(Object.isFrozen(snapshot.turns[0].citations)).toBe(true);
  const saved = snapshot.turns[0];
  if (saved.status !== "COMPLETED")
    throw new Error("Expected completed fixture");
  expect(() => { saved.citations.push({ ...fixture.submission.turn.citations[0] }); }).toThrow();
});
it("contradictory duplicate turn sequences fail closed without showing an invented answer", async () => {
  const { rpc, controller } = await ready();
  rpc.getConversation.mockResolvedValueOnce(detail(X, [turn(), turn("COMPLETED", { id: Y })]));
  await controller.select(X);
  expect(controller.getSnapshot().turns).toEqual([]);
  expect(controller.getSnapshot().error?.category).toBe("unavailable");
});
it("canonicalizes owned conversation URL UUID casing", async () => {
  const { rpc, controller } = await ready();
  const id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
  rpc.getConversation.mockResolvedValueOnce(detail(id));
  await controller.select(id.toUpperCase());
  expect(controller.getSnapshot().selectedId).toBe(id);
  expect(controller.getSnapshot().conversation?.id).toBe(id);
});
it("polling has an elapsed bound even when the status transport suppresses cancellation", async () => {
  vi.useFakeTimers();
  const { rpc, controller } = await ready();
  await controller.select(X);
  const old = deferred<api.TurnStatus>();
  rpc.getTurnStatus.mockReturnValueOnce(old.promise);
  const pending = controller.pollTurn(fixture.submission.turn.id, { maxAttempts: 1, intervalMs: 100 });
  await vi.advanceTimersByTimeAsync(5000);
  await pending;
  expect(controller.getSnapshot().polling).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
  old.resolve(turn("COMPLETED", { answer: "LATE_PAUSED_POLL" }));
  await Promise.resolve();
  expect(controller.getSnapshot().turns).toEqual([]);
});
it("demo React composition constructs no normal controller or session request", () => {
  mode.demo = true;
  const rpc = transport(), fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<ApplicationSessionProvider><ServerConversationsProvider transport={rpc}><p>HarborDesk isolated</p></ServerConversationsProvider></ApplicationSessionProvider>);
  expect(screen.getByText("HarborDesk isolated")).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
  expect(rpc.listConversations).not.toHaveBeenCalled();
});
it("new canonical list metadata updates a selected conversation without regressing its versions", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  rpc.listConversations.mockResolvedValueOnce({ conversations: [{ ...meta(), title: "Remote rename", metadata_version: 3, content_version: 4 }], next_cursor: null });
  await controller.refreshList();
  expect(controller.getSnapshot().conversation).toMatchObject({ title: "Remote rename", metadata_version: 3, content_version: 4 });
  rpc.listConversations.mockResolvedValueOnce({ conversations: [meta()], next_cursor: null });
  await controller.refreshList();
  expect(controller.getSnapshot().conversation?.content_version).toBe(4);
});

it("correction: transient reload preserves confirmed content and cursors", async () => {
  const { rpc, controller } = await ready();
  rpc.getConversation.mockResolvedValueOnce({ ...detail(X, [turn()]), next_before_sequence: 1 });
  await controller.select(X);
  const confirmed = controller.getSnapshot();
  const late = deferred<api.ConversationDetail>();
  rpc.getConversation.mockReturnValueOnce(late.promise);
  const pending = controller.reloadSelected();
  expect(controller.getSnapshot().detailLoading).toBe(true);
  late.reject(new api.ConversationApiError(503, "unavailable"));
  await pending;
  expect(controller.getSnapshot().conversation).toEqual(confirmed.conversation);
  expect(controller.getSnapshot().turns).toEqual(confirmed.turns);
  expect(controller.getSnapshot().nextTurnCursor).toBe(1);
  expect(controller.getSnapshot().error?.category).toBe("unavailable");
  expect(controller.getSnapshot().detailLoading).toBe(false);
});

it("correction: stale metadata 404 cannot remove newer confirmed detail", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const late = deferred<api.ConversationDetail>(), started = deferred<void>();
  rpc.renameConversation.mockRejectedValueOnce(new api.ConversationApiError(409, "metadata_version_conflict"));
  rpc.getConversation.mockImplementationOnce(() => { started.resolve(); return late.promise; });
  const pending = controller.rename(X, "rename");
  await started.promise;
  rpc.getConversation.mockResolvedValueOnce({ ...detail(), conversation: { ...meta(), metadata_version: 3, title: "Canonical" } });
  await controller.reloadSelected();
  late.reject(new api.ConversationApiError(404, "not_found"));
  await pending;
  expect(controller.getSnapshot().selectedId).toBe(X);
  expect(controller.getSnapshot().conversation?.metadata_version).toBe(3);
  expect(controller.getSnapshot().conversations.some(row => row.id === X)).toBe(true);
});

it("correction: terminal metadata wait settles within polling budget", async () => {
  vi.useFakeTimers();
  const { rpc, controller } = await ready();
  await controller.select(X);
  const late = deferred<api.ConversationDetail>(), started = deferred<void>();
  rpc.getConversation.mockImplementationOnce(() => { started.resolve(); return late.promise; });
  let settled = false;
  const pending = controller.pollTurn(turn().id, { maxAttempts: 1, intervalMs: 100 }).then(() => { settled = true; });
  await started.promise;
  await vi.advanceTimersByTimeAsync(5000);
  const bounded = settled;
  const state = controller.getSnapshot();
  late.resolve({ ...detail(), conversation: { ...meta(), title: "Abandoned" } });
  await pending;
  expect(bounded).toBe(true);
  expect(state.polling).toBe(false);
  expect(state.metadataLoading).toBe(false);
  expect(state.turns[0].status).toBe("COMPLETED");
  expect(controller.getSnapshot().conversation?.title).not.toBe("Abandoned");
});

it("correction: delayed refresh retains citations until canonical replacement", async () => {
  const { rpc, controller } = await ready();
  rpc.getConversation.mockResolvedValueOnce(detail(X, [turn()]));
  await controller.select(X);
  const confirmed = controller.getSnapshot();
  const late = deferred<api.ConversationDetail>();
  rpc.getConversation.mockReturnValueOnce(late.promise);
  const pending = controller.reloadSelected();
  expect(controller.getSnapshot().conversation).toEqual(confirmed.conversation);
  expect(controller.getSnapshot().turns).toEqual(confirmed.turns);
  late.resolve({ ...detail(X, [turn("COMPLETED", { answer: "Canonical answer" })]), conversation: { ...meta(), metadata_version: 3 } });
  await pending;
  expect(controller.getSnapshot().turns[0].answer).toBe("Canonical answer");
  expect(controller.getSnapshot().conversation?.metadata_version).toBe(3);
  expect(controller.getSnapshot().detailLoading).toBe(false);
});
it("correction: navigation isolates an abandoned refresh and current detail 404 removes", async () => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const late = deferred<api.ConversationDetail>();
  rpc.getConversation.mockReturnValueOnce(late.promise);
  const pending = controller.reloadSelected();
  await controller.select(Y);
  late.resolve(detail(X, [turn()]));
  await pending;
  expect(controller.getSnapshot().selectedId).toBe(Y);
  expect(controller.getSnapshot().turns).toEqual([]);
  rpc.getConversation.mockRejectedValueOnce(new api.ConversationApiError(404, "not_found"));
  await controller.reloadSelected();
  expect(controller.getSnapshot().selectedId).toBeNull();
  expect(controller.getSnapshot().conversations.some(row => row.id === Y)).toBe(false);
});
it.each(["stale success", "current 404", "deleted", "owner"])("correction: metadata freshness handles %s", async (scenario) => {
  const { rpc, controller } = await ready();
  await controller.select(X);
  const late = deferred<api.ConversationDetail>(), started = deferred<void>();
  rpc.renameConversation.mockRejectedValueOnce(new api.ConversationApiError(409, "metadata_version_conflict"));
  rpc.getConversation.mockImplementationOnce(() => { started.resolve(); return late.promise; });
  const pending = controller.rename(X, "rename");
  await started.promise;
  if (scenario === "stale success") {
    rpc.getConversation.mockResolvedValueOnce({ ...detail(), conversation: { ...meta(), metadata_version: 3, title: "New canonical" } });
    await controller.reloadSelected();
    late.resolve({ ...detail(), conversation: { ...meta(), metadata_version: 4, title: "Obsolete response" } });
  }
  else if (scenario === "current 404")
    late.reject(new api.ConversationApiError(404, "not_found"));
  else if (scenario === "deleted") {
    await controller.delete(X);
    late.resolve(detail());
  }
  else {
    switchOwner(B);
    await controller.initialize();
    await controller.select(Y);
    late.resolve(detail());
  }
  await pending;
  expect(controller.getSnapshot().metadataLoading).toBe(false);
  if (scenario === "stale success") {
    expect(controller.getSnapshot().conversation?.title).toBe("New canonical");
    expect(controller.getSnapshot().conversation?.metadata_version).toBe(3);
  }
  else if (scenario === "owner") {
    expect(controller.getSnapshot().ownerId).toBe(B);
    expect(controller.getSnapshot().selectedId).toBe(Y);
  }
  else {
    expect(controller.getSnapshot().selectedId).toBeNull();
    expect(controller.getSnapshot().conversations.some(row => row.id === X)).toBe(false);
  }
});
it.each(["dispose", "late rejection", "timely"])("correction: terminal metadata cleanup handles %s", async (scenario) => {
  vi.useFakeTimers();
  const { rpc, controller } = await ready();
  await controller.select(X);
  const late = deferred<api.ConversationDetail>(), started = deferred<void>();
  rpc.getConversation.mockImplementationOnce(() => { started.resolve(); return late.promise; });
  let settled = false;
  const pending = controller.pollTurn(turn().id, { maxAttempts: 1, intervalMs: 100 }).then(() => { settled = true; });
  await started.promise;
  const signal = rpc.getConversation.mock.calls.at(-1)![2]!;
  if (scenario === "dispose") {
    controller.dispose();
    await pending;
    expect(settled).toBe(true);
    late.resolve({ ...detail(), conversation: { ...meta(), title: "Abandoned" } });
  }
  else if (scenario === "late rejection") {
    await vi.advanceTimersByTimeAsync(5000);
    expect(settled).toBe(true);
    expect(signal.aborted).toBe(true);
    expect(controller.getSnapshot().turns[0].status).toBe("COMPLETED");
    late.reject(new Error("Late transport rejection"));
  }
  else {
    late.resolve({ ...detail(), conversation: { ...meta(), content_version: 3 } });
    await pending;
    expect(signal.aborted).toBe(false);
    expect(controller.getSnapshot().conversation?.content_version).toBe(3);
  }
  await Promise.resolve();
  expect(controller.getSnapshot().polling).toBe(false);
  expect(controller.getSnapshot().metadataLoading).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
  if (scenario === "dispose")
    expect(controller.getSnapshot().ownerId).toBeNull();
  else
    expect(controller.getSnapshot().error).toBeNull();
});
