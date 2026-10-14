import { StrictMode, useSyncExternalStore } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApplicationSessionProvider, useApplicationSession } from "./application-session-provider";
import { ServerConversationsProvider } from "./server-conversations-provider";
import { AppShell } from "@/components/layout/app-shell";
import { ChatInterface } from "@/components/chat/chat-interface";
import { ConversationLayout } from "@/components/layout/conversation-layout";
import { ToastProvider } from "@/components/ui/toast-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SESSION_TRANSITION_KEY, setSessionOwner } from "@/lib/api/session-events";
import fixture from "@/lib/api/fixtures/conversation-backend-dto.json";
import type { ConversationMetadata, StoredTurn } from "@/lib/api/conversations";

const nav = vi.hoisted(() => ({ path: "/chat", push: vi.fn(), replace: vi.fn(), listeners: new Set<() => void>(), query: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  usePathname: () => useSyncExternalStore(callback => { nav.listeners.add(callback); return () => { nav.listeners.delete(callback); }; }, () => nav.path),
  useSearchParams: () => nav.query,
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
}));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: () => ({ data: { connected: false }, error: null, isLoading: false, refetch: vi.fn() }) }));
vi.mock("@/lib/hooks/use-knowledge-status", () => ({ useKnowledgeStatus: () => ({ needsConnect: true, needsPrepare: false, setupState: "not_connected", isReady: false }) }));
const A = "00000000-0000-0000-0000-000000000065", B = "00000000-0000-0000-0000-000000000066";
const X = fixture.metadata.id, Y = "00000000-0000-0000-0000-000000000201";
type Row = { metadata: ConversationMetadata; turns: StoredTurn[] };
let cookie: string | null, data: Record<string, string>, rows: Map<string, Map<string, Row>>;
let session: ReturnType<typeof useApplicationSession>;
let intercept: ((path: string, options: RequestInit) => Promise<Response> | undefined) | null;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function go(path: string) { nav.path = path.split("?")[0]; nav.query = new URLSearchParams(path.split("?")[1]); nav.listeners.forEach(listener => listener()); }
function stored(answer = "A saved answer"): StoredTurn { return { ...fixture.detail.turns[0], answer } as StoredTurn; }
function seed(owner = A, id = X, title = "A title", turns: StoredTurn[] = [stored()]) {
  const row = { metadata: { ...fixture.metadata, id, title }, turns };
  const owned = rows.get(owner) ?? new Map(); owned.set(id, row); rows.set(owner, owned); return row;
}
async function server(url: string, options: RequestInit = {}): Promise<Response> {
  const path = url.replace(/^.*\/api\/v1/, ""), method = options.method ?? "GET";
  const overridden = intercept?.(path, options); if (overridden) return overridden;
  if (path === "/auth/session") return cookie ? json({ kind: "GOOGLE_ACCOUNT", user_id: cookie, csrf_token: "synthetic" }) : json({ detail: "Expired" }, 401);
  if (path === "/auth/session/logout") { cookie = null; return new Response(null, { status: 204 }); }
  if (path.startsWith("/sources/")) return json({ ...fixture.detail.turns[0].citations[0], mime_type: "text/plain", chunk_index: 0, text: "Live authorized evidence", modified_at: fixture.metadata.updated_at });
  if (!cookie) return json({ detail: "Expired" }, 401);
  const owned = rows.get(cookie) ?? new Map<string, Row>(); rows.set(cookie, owned);
  const [resource, id, sub, turnId] = path.split("?")[0].slice(1).split("/");
  const body = options.body ? JSON.parse(String(options.body)) : {};
  if (resource !== "conversations") throw new Error(`Unexpected test route: ${resource}`);
  if (!id) {
    if (method === "GET") return json({ conversations: [...owned.values()].map(row => row.metadata), next_cursor: null });
    const row = seed(cookie, Y, body.title ?? "New conversation", []); return json(row.metadata, 201);
  }
  const row = owned.get(id); if (!row) return json({ detail: "Conversation not found." }, 404);
  if (sub === "turns") {
    if (method === "GET") { const turn = row.turns.find(turn => turn.id === turnId); return turn ? json({ ...turn, execution_expired: false }) : json({ detail: "Not found" }, 404); }
    const existing = row.turns.find(turn => turn.client_request_id === body.client_request_id);
    if (existing) return json({ turn: { ...existing, execution_expired: false }, replayed: true });
    const turn = { ...stored("Server committed answer"), id: crypto.randomUUID(), sequence: row.turns.length + 1, question: body.question,
      client_request_id: body.client_request_id };
    row.turns.push(turn); row.metadata.content_version += 1;
    return json({ turn: { ...turn, execution_expired: false }, replayed: false });
  }
  if (method === "PATCH") { row.metadata = { ...row.metadata, title: body.title, title_is_manual: true, metadata_version: row.metadata.metadata_version + 1 }; return json(row.metadata); }
  if (method === "DELETE") { owned.delete(id); return new Response(null, { status: 204 }); }
  return json({ conversation: row.metadata, turns: row.turns, next_before_sequence: null });
}
function Controls() { session = useApplicationSession(); return <span>Verified {session.userId}</span>; }
function Route() { const path = useSyncExternalStore(callback => { nav.listeners.add(callback); return () => { nav.listeners.delete(callback); }; }, () => nav.path);
  return <ConversationLayout><ChatInterface conversationId={path.startsWith("/chat/") ? path.slice(6) : undefined} /></ConversationLayout>; }
function mount(strict = false) { const app = (<ToastProvider><TooltipProvider><ApplicationSessionProvider><Controls /><ServerConversationsProvider><AppShell><Route /></AppShell></ServerConversationsProvider></ApplicationSessionProvider></TooltipProvider></ToastProvider>); return render(strict ? <StrictMode>{app}</StrictMode> : app); }
function send(question = "Private follow up") { fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: question } }); fireEvent.click(screen.getByRole("button", { name: "Send message" })); }
function requests() { return vi.mocked(fetch).mock.calls.filter(([url, options]) => String(url).includes("/turns") && options?.method === "POST"); }
beforeEach(() => {
  cookie = A; data = { "drivemind:conversations": "LEGACY_SECRET", [`drivemind:v1:normal:${A}:conversations`]: "QUARANTINED_SECRET" }; rows = new Map(); intercept = null; seed();
  setSessionOwner(null); nav.path = `/chat/${X}`; nav.query = new URLSearchParams(); nav.listeners.clear(); vi.clearAllMocks();
  nav.push.mockImplementation(go); nav.replace.mockImplementation(go);
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (key: string) => data[key] ?? null, setItem: (key: string, value: string) => { data[key] = value; }, removeItem: (key: string) => { delete data[key]; } } });
  vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) => server(url, options)));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setSessionOwner(null); });
it("mounted create and submit use canonical server ID, no browser history or question URL", async () => {
  rows.get(A)!.clear(); go("/chat"); mount(); await screen.findByText(`Verified ${A}`);
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Private follow up" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Send message" })); await screen.findByText("Server committed answer");
  expect(nav.path).toBe(`/chat/${Y}`); expect(nav.query.has("ask")).toBe(false);
  const body = JSON.parse(String(requests()[0][1]!.body)); expect(body.question).toBe("Private follow up"); expect(body.history).toBeUndefined();
  expect(rows.get(A)!.get(Y)!.turns).toHaveLength(1);
});
it("refresh and a second isolated browser mount reload canonical history without local records", async () => {
  mount(); await screen.findByText("A saved answer"); send(); await screen.findByText("Server committed answer"); cleanup();
  data = {}; mount(); await screen.findByText("Server committed answer"); expect(requests()).toHaveLength(1);
  expect(screen.queryByText(/LEGACY_SECRET|QUARANTINED_SECRET/)).toBeNull();
});
it("mounted sidebar creates, renames and confirms deletion using shared server state", async () => {
  const user = userEvent.setup(); mount(); await screen.findByText("A saved answer");
  fireEvent.click(screen.getByRole("button", { name: "Conversation options" })); fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
  const input = screen.getByRole("textbox", { name: "Rename conversation" }); fireEvent.change(input, { target: { value: "Canonical renamed" } }); fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(rows.get(A)!.get(X)!.metadata.title).toBe("Canonical renamed"));
  expect(await screen.findByRole("link", { name: /Canonical renamed/ })).toBeInTheDocument();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Conversation options" })); fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
  await waitFor(() => expect(rows.get(A)!.has(X)).toBe(false)); expect(screen.queryByText("A saved answer")).toBeNull();
  await user.click(screen.getByRole("button", { name: "New Chat" })); await waitFor(() => expect(nav.path).toBe(`/chat/${Y}`));
});
it("mounted list and turn pagination remain accessible", async () => {
  let listPages = 0;
  intercept = (path) => {
    if (path === "/conversations?limit=30") return Promise.resolve(json({ conversations: [fixture.metadata], next_cursor: "page2" }));
    if (path.includes("cursor=page2")) { listPages++; return Promise.resolve(json({ conversations: [{ ...fixture.metadata, id: Y, title: "Older conversation" }], next_cursor: null })); }
    if (path.includes("before_sequence=2")) return Promise.resolve(json({ ...fixture.detail, conversation: fixture.metadata }));
    if (path.includes(`/conversations/${X}?limit=50`)) return Promise.resolve(json({ ...fixture.detail, turns: Array.from({ length: 50 }, (_, i) => ({ ...stored(i === 0 ? "Newest answer" : `Page answer ${i}`), id: `00000000-0000-0000-0000-${String(i + 300).padStart(12, "0")}`, client_request_id: `00000000-0000-0000-0000-${String(i + 400).padStart(12, "0")}`, sequence: i + 2 })), next_before_sequence: 2 }));
  };
  mount(); await screen.findByText("Newest answer"); fireEvent.click(screen.getByRole("button", { name: "Load more conversations" })); await screen.findByRole("link", { name: /Older conversation/ });
  fireEvent.click(screen.getByRole("button", { name: "Load older turns" })); await screen.findByText("Synthetic canonical answer."); expect(screen.getByText("Newest answer")).toBeInTheDocument(); expect(listPages).toBe(1);
});
it.each(["list", "detail", "submission", "401"])("late A %s cannot affect verified B or write browser history", async (kind) => {
  const late = deferred<Response>(); let started = false;
  mount(); await screen.findByText("A saved answer"); const before = { ...data };
  intercept = (path, options) => {
    const hit = kind === "list" ? path === "/conversations?limit=30" : kind === "detail" ? path.includes(`/${X}?limit=50`) : path.endsWith("/turns") && options.method === "POST";
    if (hit && cookie === A) { started = true; return late.promise; }
  };
  if (kind === "list") fireEvent.click(screen.getByRole("button", { name: "Refresh conversations" }));
  else if (kind === "detail") fireEvent.click(screen.getByRole("button", { name: "Refresh conversation" }));
  else send();
  await waitFor(() => expect(started).toBe(true)); cookie = B; seed(B, Y, "B title", [stored("B answer")]);
  fireEvent(window, new StorageEvent("storage", { key: SESSION_TRANSITION_KEY, newValue: "external-notice" }));
  expect(screen.queryByText("A saved answer")).toBeNull(); await screen.findByText(`Verified ${B}`);
  await act(async () => { late.resolve(kind === "401" ? json({ detail: "Expired" }, 401) : kind === "list" ? json({ conversations: [fixture.metadata], next_cursor: null }) : kind === "detail" ? json(fixture.detail) : json(fixture.submission)); });
  expect(screen.getByText(`Verified ${B}`)).toBeInTheDocument(); expect(screen.queryByText(/A saved answer|Synthetic canonical answer|Private follow up/)).toBeNull();
  expect(Object.fromEntries(Object.entries(data).filter(([key]) => key.includes("normal:") || key === "drivemind:conversations"))).toEqual(Object.fromEntries(Object.entries(before).filter(([key]) => key.includes("normal:") || key === "drivemind:conversations")));
});
it("logout and another owner cannot open A URL; A can return to saved SQL history", async () => {
  mount(); await screen.findByText("A saved answer"); await act(() => session.logout()); expect(screen.queryByText("A saved answer")).toBeNull();
  cookie = B; fireEvent(window, new Event("focus")); await screen.findByText(`Verified ${B}`); expect(screen.queryByText("A saved answer")).toBeNull();
  cookie = A; fireEvent(window, new Event("focus")); await screen.findByText("A saved answer");
});
it("X generation completing while Y is selected never replaces Y", async () => {
  seed(A, Y, "Y title", [stored("Y answer")]); const late = deferred<Response>();
  mount(); await screen.findByText("A saved answer"); intercept = (path, options) => path.endsWith("/turns") && options.method === "POST" ? late.promise : undefined;
  send(); await waitFor(() => expect(requests()).toHaveLength(1)); act(() => go(`/chat/${Y}`)); await screen.findByText("Y answer");
  await act(async () => late.resolve(json(fixture.submission))); expect(screen.getByText("Y answer")).toBeInTheDocument(); expect(screen.queryByText("Synthetic canonical answer.")).toBeNull();
});
it("lost acknowledgement reconciles the same frozen request and displays one canonical turn", async () => {
  mount(); await screen.findByText("A saved answer"); let lost = true;
  intercept = (path, options) => { if (path.endsWith("/turns") && options.method === "POST" && lost) { lost = false; const hook = intercept; intercept = null; const committed = server(`/api/v1${path}`, options); intercept = hook; return committed.then(() => { throw new TypeError("Lost acknowledgement"); }); } };
  send(); await screen.findByRole("button", { name: "Reconcile submission" }); fireEvent.click(screen.getByRole("button", { name: "Reconcile submission" })); await screen.findByText("Server committed answer");
  expect(requests()).toHaveLength(2); expect(requests()[0][1]!.body).toEqual(requests()[1][1]!.body); expect(rows.get(A)!.get(X)!.turns).toHaveLength(2);
});
it.each(["FAILED", "INTERRUPTED"] as const)("stored %s renders truthful terminal state without a fabricated answer", async status => {
  rows.get(A)!.get(X)!.turns = [{ ...stored(), status, answer: null, query_id: null, citations: [], error_code: status === "FAILED" ? "TURN_FAILED" : "TURN_INTERRUPTED" } as StoredTurn];
  mount(); await screen.findByText(status === "FAILED" ? /This attempt failed/ : /This attempt was interrupted/); expect(screen.queryByText("A saved answer")).toBeNull();
});
it("RUNNING only becomes INTERRUPTED after explicit expired-turn confirmation", async () => {
  const running = { ...stored(), status: "RUNNING", answer: null, query_id: null, citations: [], finished_at: null, error_code: null } as StoredTurn;
  rows.get(A)!.get(X)!.turns = [running];
  intercept = (path, options) => {
    if (path.endsWith("/interrupt")) return Promise.resolve(json({ ...stored(), status: "INTERRUPTED", query_id: null, answer: null, citations: [], error_code: "TURN_INTERRUPTED", execution_expired: false }));
    if (path.includes(`/turns/${running.id}`) && options.method !== "POST") return Promise.resolve(json({ ...running, execution_expired: true }));
  };
  mount(); await screen.findByText("Server turn RUNNING"); expect(screen.queryByRole("button", { name: "Interrupt expired attempt" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Check progress" })); await screen.findByRole("button", { name: "Interrupt expired attempt" });
  fireEvent.click(screen.getByRole("button", { name: "Interrupt expired attempt" })); await screen.findByText(/This attempt was interrupted/); expect(requests().filter(([url]) => String(url).endsWith("/turns"))).toHaveLength(0);
});
it("stop waiting leaves an unknown outcome, not an invented interruption", async () => {
  const late = deferred<Response>(); mount(); await screen.findByText("A saved answer"); intercept = (path, options) => path.endsWith("/turns") && options.method === "POST" ? late.promise : undefined;
  send(); await screen.findByRole("button", { name: "Stop waiting" }); fireEvent.click(screen.getByRole("button", { name: "Stop waiting" }));
  await screen.findByRole("button", { name: "Reconcile submission" }); expect(screen.queryByText(/This attempt was interrupted/)).toBeNull();
  await act(async () => late.resolve(json(fixture.submission))); expect(screen.queryByText("Synthetic canonical answer.")).toBeNull();
});
it("transient mounted reload preserves confirmed content; a current 404 invalidates", async () => {
  mount(); await screen.findByText("A saved answer"); intercept = path => path.includes(`/${X}?limit=50`) ? Promise.resolve(json({ detail: "Unavailable" }, 503)) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Refresh conversation" })); await screen.findAllByText("Conversation service is unavailable."); expect(screen.getByText("A saved answer")).toBeInTheDocument();
  intercept = path => path.includes(`/${X}?limit=50`) ? Promise.resolve(json({ detail: "Not found" }, 404)) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Refresh conversation" })); await waitFor(() => expect(screen.queryByText("A saved answer")).toBeNull());
});
it("citation opens an authorized source route, never Google Drive with a SQL UUID", async () => {
  const user = userEvent.setup(); mount(); await screen.findByText("A saved answer"); await user.click(screen.getByRole("button", { name: /Sources/ }));
  const link = await screen.findByRole("link", { name: "Open source" }); expect(link).toHaveAttribute("href", `/sources/${fixture.detail.turns[0].citations[0].chunk_id}`);
  expect(screen.queryByRole("link", { name: /Open in.*Drive/i })).toBeNull(); expect(screen.getByRole("link", { name: /Ask about/ })).toHaveAttribute("href", "/chat");
});
it("private ask URL is discarded without submission; disconnected Drive does not block saved history", async () => {
  nav.query = new URLSearchParams("ask=URL_SECRET"); mount(); await screen.findByText("A saved answer"); await waitFor(() => expect(nav.query.has("ask")).toBe(false));
  expect(requests()).toHaveLength(0); expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(""); expect(nav.replace).not.toHaveBeenCalledWith("/onboarding");
});
it("expiry during mounted submission removes private state", async () => {
  mount(); await screen.findByText("A saved answer"); intercept = (path, options) => path.endsWith("/turns") && options.method === "POST" ? Promise.resolve(json({ detail: "Expired" }, 401)) : undefined;
  send(); await screen.findByRole("button", { name: "Sign in with Google" }); expect(screen.queryByText(/A saved answer|Private follow up/)).toBeNull();
});
it("no normal history storage access occurs, even with disabled storage", async () => {
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: vi.fn(() => { throw new Error("Disabled"); }), setItem: vi.fn(() => { throw new Error("Disabled"); }), removeItem: vi.fn() } });
  mount(); await screen.findByText("A saved answer"); send(); await screen.findByText("Server committed answer");
  expect(window.localStorage.getItem).not.toHaveBeenCalled();
  // Authentication may broadcast an opaque transition nonce; never conversation content.
  for (const [key, value] of vi.mocked(window.localStorage.setItem).mock.calls) { expect(key).toBe(SESSION_TRANSITION_KEY); expect(value).not.toMatch(/answer|question|title/i); }
});
it.each([409, 503])("mounted submission %s remains uncertain and does not invent an answer", async status => {
  mount(); await screen.findByText("A saved answer"); intercept = (path, options) => path.endsWith("/turns") && options.method === "POST" ? Promise.resolve(json({ detail: "Safe conflict or unavailable" }, status)) : undefined;
  send(); await screen.findByRole("button", { name: "Reconcile submission" }); expect(screen.queryByText("Server committed answer")).toBeNull(); expect(rows.get(A)!.get(X)!.turns).toHaveLength(1);
});
it("202 replay stays RUNNING until explicit checking confirms completion", async () => {
  const running = { ...stored(), status: "RUNNING", query_id: null, answer: null, citations: [], finished_at: null, error_code: null, execution_expired: false };
  mount(); await screen.findByText("A saved answer");
  intercept = (path, options) => path.endsWith("/turns") && options.method === "POST" ? Promise.resolve(json({ turn: { ...running, id: Y, sequence: 2, question: JSON.parse(String(options.body)).question, client_request_id: JSON.parse(String(options.body)).client_request_id }, replayed: true }, 202))
    : path.includes(`/turns/${Y}`) ? Promise.resolve(json({ ...fixture.submission.turn, id: Y, sequence: 2, question: "Private follow up", client_request_id: JSON.parse(String(requests()[0][1]!.body)).client_request_id })) : undefined;
  send(); await screen.findByText("Server turn RUNNING"); expect(screen.queryByText("Synthetic canonical answer.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Check progress" })); await screen.findByText("Synthetic canonical answer."); expect(requests()).toHaveLength(1);
});
it("rename 409 reloads canonical title instead of pretending the draft was saved", async () => {
  mount(); await screen.findByText("A saved answer");
  intercept = (_path, options) => options.method === "PATCH" ? Promise.resolve(json({ detail: "Conversation metadata version is stale." }, 409)) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Conversation options" })); fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
  const input = screen.getByRole("textbox", { name: "Rename conversation" }); fireEvent.change(input, { target: { value: "Unconfirmed draft" } }); fireEvent.keyDown(input, { key: "Enter" });
  await screen.findAllByText("Conversation metadata version is stale."); expect(screen.queryByRole("link", { name: /Unconfirmed draft/ })).toBeNull(); expect(screen.getByRole("link", { name: /A title/ })).toBeInTheDocument();
});
it("delete during pending generation cannot be undone by its late response", async () => {
  const late = deferred<Response>(); mount(); await screen.findByText("A saved answer"); intercept = (path, options) => path.endsWith("/turns") && options.method === "POST" ? late.promise : undefined;
  send(); await screen.findByRole("button", { name: "Stop waiting" }); vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Conversation options" })); fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
  await waitFor(() => expect(rows.get(A)!.has(X)).toBe(false)); await act(async () => late.resolve(json(fixture.submission)));
  expect(screen.queryByText(/A saved answer|Synthetic canonical answer/)).toBeNull(); expect(nav.path).toBe("/chat");
});
it("late create cannot send a draft into a newer selected conversation", async () => {
  go("/chat"); const late = deferred<Response>(); intercept = (path, options) => path === "/conversations" && options.method === "POST" ? late.promise : undefined;
  mount(); await screen.findByText(`Verified ${A}`); send(); await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url, options]) => String(url).endsWith("/conversations") && options?.method === "POST")).toBe(true));
  act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer"); seed(A, Y, "Created late", []);
  await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 201)));
  expect(nav.path).toBe(`/chat/${X}`); expect(requests()).toHaveLength(0);
});
it("obsolete mounted metadata 404 cannot erase newer canonical detail", async () => {
  const late = deferred<Response>(); let refreshing = false;
  mount(); await screen.findByText("A saved answer");
  intercept = (path, options) => {
    if (options.method === "PATCH") return Promise.resolve(json({ detail: "Conversation metadata version is stale." }, 409));
    if (path.includes(`/${X}?limit=1`)) { refreshing = true; return late.promise; }
  };
  fireEvent.click(screen.getByRole("button", { name: "Conversation options" })); fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Rename conversation" }), { target: { value: "Rename draft" } }); fireEvent.keyDown(screen.getByRole("textbox", { name: "Rename conversation" }), { key: "Enter" });
  await waitFor(() => expect(refreshing).toBe(true)); rows.get(A)!.get(X)!.metadata = { ...fixture.metadata, metadata_version: 3, title: "New canonical title" };
  fireEvent.click(screen.getByRole("button", { name: "Refresh conversation" })); await screen.findByRole("link", { name: /New canonical title/ });
  await act(async () => late.resolve(json({ detail: "Not found" }, 404)));
  expect(screen.getByRole("link", { name: /New canonical title/ })).toBeInTheDocument(); expect(screen.getByText("A saved answer")).toBeInTheDocument();
});
it("desktop and mobile sidebar use one shared server controller", async () => {
  mount(); await screen.findByText("A saved answer");
  const listCount = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/conversations?limit=30")).length;
  expect(listCount()).toBe(1); fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
  await waitFor(() => expect(screen.getAllByRole("navigation", { name: "Recent conversations", hidden: true }).length).toBe(2));
  expect(listCount()).toBe(1);
});
it("StrictMode restart and unmount discard obsolete private state", async () => {
  mount(true); await screen.findByText("A saved answer"); cleanup(); cookie = B; seed(B, Y, "B title", [stored("B answer")]); go(`/chat/${Y}`);
  mount(true); await screen.findByText("B answer"); expect(screen.queryByText("A saved answer")).toBeNull(); expect(requests()).toHaveLength(0);
});
