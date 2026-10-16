import { StrictMode, useSyncExternalStore } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApplicationSessionProvider, useApplicationSession } from "./application-session-provider";
import { ServerConversationsProvider } from "./server-conversations-provider";
import { AppShell } from "@/components/layout/app-shell";
import { ChatInterface } from "@/components/chat/chat-interface";
import { ConversationLayout } from "@/components/layout/conversation-layout";
import { ToastProvider } from "@/components/ui/toast-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SESSION_TRANSITION_KEY, setSessionOwner, invalidateSessionRequests } from "@/lib/api/session-events";
import fixture from "@/lib/api/fixtures/conversation-backend-dto.json";
import type { ConversationMetadata, StoredTurn } from "@/lib/api/conversations";

const nav = vi.hoisted(() => ({ path: "/chat", push: vi.fn(), replace: vi.fn(), listeners: new Set<() => void>(), query: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  usePathname: () => useSyncExternalStore(callback => { nav.listeners.add(callback); return () => { nav.listeners.delete(callback); }; }, () => nav.path),
  useSearchParams: () => nav.query,
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
}));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: () => ({ data: { connected: false }, error: null, isLoading: false, refetch: vi.fn() }) }));
const knowledge = vi.hoisted(() => ({ ready: false }));
vi.mock("@/lib/hooks/use-knowledge-status", () => ({ useKnowledgeStatus: () => ({ needsConnect: !knowledge.ready, needsPrepare: false, setupState: knowledge.ready ? "ready" : "not_connected", isReady: knowledge.ready, fileStats: { indexed: knowledge.ready ? 1 : 0 } }) }));
const A = "00000000-0000-0000-0000-000000000065", B = "00000000-0000-0000-0000-000000000066";
const X = fixture.metadata.id, Y = "00000000-0000-0000-0000-000000000201";
type Row = { metadata: ConversationMetadata; turns: StoredTurn[] };
let inventory: "indexed" | "empty" | "unavailable";
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
  if (path === "/files") return inventory === "unavailable" ? json({ detail: "Temporary failure" }, 503) : json({ files: inventory === "indexed" ? [{ id: "00000000-0000-0000-0000-000000000987", user_id: cookie, drive_file_id: "provider-only", status: "indexed" }] : [], total: inventory === "indexed" ? 1 : 0 });
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
  if (path === "/files") return <p>Files view</p>;
  return <ConversationLayout key={path}><ChatInterface conversationId={path.startsWith("/chat/") ? path.slice(6) : undefined} /></ConversationLayout>; }
function mount(strict = false) { const app = (<ToastProvider><TooltipProvider><ApplicationSessionProvider><Controls /><ServerConversationsProvider><AppShell><Route /></AppShell></ServerConversationsProvider></ApplicationSessionProvider></TooltipProvider></ToastProvider>); return render(strict ? <StrictMode>{app}</StrictMode> : app); }
function send(question = "Private follow up") { fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: question } }); fireEvent.click(screen.getByRole("button", { name: "Send message" })); }
function requests() { return vi.mocked(fetch).mock.calls.filter(([url, options]) => String(url).includes("/turns") && options?.method === "POST"); }
beforeEach(() => {
  knowledge.ready = false; inventory = "indexed"; cookie = A; data = { "drivemind:conversations": "LEGACY_SECRET", [`drivemind:v1:normal:${A}:conversations`]: "QUARANTINED_SECRET" }; rows = new Map(); intercept = null; seed();
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
  const link = await screen.findByRole("link", { name: "Open source" }); expect(link).toHaveAttribute("href", `/sources/${fixture.detail.turns[0].citations[0].chunk_id}?conversation=${X}`);
  expect(screen.queryByRole("link", { name: /Open in.*Drive/i })).toBeNull(); expect(screen.getByRole("link", { name: "Open chat" })).toHaveAttribute("href", `/chat/${X}`);
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

it.each([false, true])("rejects 4,001 characters without losing a draft or creating a conversation (new=%s)", async fresh => {
  if (fresh) { rows.get(A)!.clear(); go("/chat"); }
  mount(); await screen.findByText(`Verified ${A}`);
  if (fresh) await screen.findByRole("button", { name: "Find the latest meeting notes." });
  else await screen.findByText("A saved answer");
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Ready" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
  const input = screen.getByRole("textbox", { name: "Message" });
  const invalid = "x".repeat(4001);
  fireEvent.change(input, { target: { value: invalid } });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  expect(input).toHaveValue(invalid); expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("alert")).toHaveTextContent("Your draft is kept");
  expect(requests()).toHaveLength(0);
  expect(vi.mocked(fetch).mock.calls.filter(([url, opts]) => String(url).endsWith("/conversations") && opts?.method === "POST")).toHaveLength(0);
  fireEvent.change(input, { target: { value: "x".repeat(4000) } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
  fireEvent.keyDown(input, { key: "Enter" });
  await screen.findByText("Server committed answer");
  expect(requests()).toHaveLength(1);
  expect(JSON.parse(String(requests()[0][1]!.body)).question).toHaveLength(4000);
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
});
it.each(["", "   "])("empty normal draft %j makes no turn or conversation", async question => {
  rows.get(A)!.clear(); go("/chat"); mount(); await screen.findByText(`Verified ${A}`);
  const input = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(input, { target: { value: question } }); fireEvent.keyDown(input, { key: "Enter" });
  expect(requests()).toHaveLength(0); expect(rows.get(A)!.size).toBe(0);
});
it("zero indexed knowledge offers Files and keeps saved history readable", async () => {
  inventory = "empty"; mount(); await screen.findByText("A saved answer");
  expect(await screen.findByRole("link", { name: "Choose documents in Files" })).toHaveAttribute("href", "/files");
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Find a document" } });
  expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" }); expect(requests()).toHaveLength(0);
});
it("empty new chat has no enabled document suggestions", async () => {
  inventory = "empty"; rows.get(A)!.clear(); go("/chat"); mount();
  await screen.findByRole("link", { name: "Choose documents in Files" });
  expect(screen.queryByText("What would you like to know?")).toBeNull();
  expect(screen.getAllByRole("button").filter(button => /summarize|what.*documents/i.test(button.textContent ?? ""))).toHaveLength(0);
});
it("readiness failure is not zero; saved history remains and explicit retry can recover", async () => {
  inventory = "unavailable"; mount(); await screen.findByText("A saved answer");
  await screen.findByText(/Prepared knowledge is temporarily unavailable/);
  expect(screen.queryByRole("link", { name: "Choose documents in Files" })).toBeNull();
  expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  inventory = "indexed"; fireEvent.click(screen.getByRole("button", { name: "Check again" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Prepared query" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
});
it("checking readiness disables sending while saved history remains readable", async () => {
  const late = deferred<Response>(); intercept = path => path === "/files" ? late.promise : undefined;
  mount(); await screen.findByText("A saved answer"); expect(screen.getByText("Checking prepared knowledge…")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  await act(async () => late.resolve(json({ files: [{ user_id: A, status: "indexed" }], total: 1 })));
  send("Indexed knowledge works even though Drive is disconnected"); await screen.findByText("Server committed answer");
});
it("a delayed old-owner inventory cannot enable the new owner's chat", async () => {
  const late = deferred<Response>(); intercept = path => path === "/files" && cookie === A ? late.promise : undefined;
  mount(); await screen.findByText("A saved answer"); cookie = B; inventory = "empty";
  fireEvent(window, new Event("focus")); await screen.findByText(`Verified ${B}`);
  await screen.findByRole("link", { name: "Choose documents in Files" });
  await act(async () => late.resolve(json({ files: [{ user_id: A, status: "indexed" }], total: 1 })));
  expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled(); expect(screen.queryByText("A saved answer")).toBeNull();
});

it("readiness 401 invalidates the current application session", async () => {
  intercept = path => path === "/files" ? Promise.resolve(json({ detail: "Expired" }, 401)) : undefined;
  mount(); await screen.findByRole("button", { name: "Sign in with Google" });
  expect(screen.queryByText("A saved answer")).toBeNull(); expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
});
it("a constrained but unauthorized conversation destination still fails owner authorization", async () => {
  cookie = B; mount(); await screen.findByText(`Verified ${B}`);
  await screen.findByText(/Conversation unavailable or loading/);
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes(`/conversations/${X}?`))).toBe(true));
  expect(screen.queryByText("A saved answer")).toBeNull(); expect(requests()).toHaveLength(0);
});
it("duplicate keyboard and click sends retain one logical request", async () => {
  const late = deferred<Response>(); mount(); await screen.findByText("A saved answer");
  intercept = (path, opts) => path.endsWith("/turns") && opts.method === "POST" ? late.promise : undefined;
  const input = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(input, { target: { value: "One question" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
  fireEvent.keyDown(input, { key: "Enter" }); fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(requests()).toHaveLength(1));
  await act(async () => late.resolve(json(fixture.submission)));
});

// P1-D1-1: Route is keyed by pathname so each automatic transition destroys the
// source chat/composer and mounts a fresh destination under the persistent provider.
async function newChatWithDraft(text: string) {
  go("/chat"); mount(); await screen.findByText(`Verified ${A}`);
  await screen.findByRole("button", { name: "Find the latest meeting notes." });
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: text } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
}
function creationRequests() { return vi.mocked(fetch).mock.calls.filter(([url, opts]) => String(url).endsWith("/conversations") && opts?.method === "POST"); }
function holdCreation() {
  const late = deferred<Response>();
  intercept = (path, opts) => path === "/conversations" && opts.method === "POST" ? late.promise : undefined;
  return late;
}
it("creation handoff retains a newer rejected 4,001-character draft across a real route remount", async () => {
  await newChatWithDraft("Original valid question"); const late = holdCreation();
  const sourceInput = screen.getByRole("textbox", { name: "Message" });
  fireEvent.keyDown(sourceInput, { key: "Enter" }); await waitFor(() => expect(creationRequests()).toHaveLength(1));
  const newer = "n".repeat(4001);
  fireEvent.change(sourceInput, { target: { value: newer } }); fireEvent.keyDown(sourceInput, { key: "Enter" });
  expect(sourceInput).toHaveValue(newer); expect(screen.getByRole("alert")).toHaveTextContent("Your draft is kept");
  seed(A, Y, "Recovered", []); await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 201)));
  await screen.findByText("Server committed answer");
  const destination = screen.getByRole("textbox", { name: "Message" });
  expect(destination).not.toBe(sourceInput); expect(destination).toHaveValue(newer);
  expect(destination).toHaveAttribute("aria-invalid", "true"); expect(requests()).toHaveLength(1);
  expect(rows.get(A)!.get(Y)!.turns.map(t => t.question)).toEqual(["Original valid question"]);
  fireEvent.change(destination, { target: { value: "Corrected newer question" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
  fireEvent.keyDown(destination, { key: "Enter" });
  await waitFor(() => expect(requests()).toHaveLength(2));
  await waitFor(() => expect(rows.get(A)!.get(Y)!.turns.map(t => t.question)).toEqual(["Original valid question", "Corrected newer question"]));
});
it.each(["composer", "sidebar"])("lost creation acknowledgement handoff keeps the unsent question without automatic replay via %s", async control => {
  await newChatWithDraft("Unsubmitted original question");
  let lost = true;
  intercept = (path, opts) => {
    if (path === "/conversations" && opts.method === "POST") {
      const row = seed(A, Y, "Recovered", []);
      if (lost) { lost = false; return Promise.reject(new TypeError("Lost creation acknowledgement")); }
      return Promise.resolve(json(row.metadata, 200));
    }
  };
  const source = screen.getByRole("textbox", { name: "Message" }); fireEvent.keyDown(source, { key: "Enter" });
  const actions = await screen.findAllByRole("button", { name: "Recover chat" }); expect(requests()).toHaveLength(0);
  if (control === "sidebar") {
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    fireEvent.click(await screen.findByRole("button", { name: "Recover chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
  } else fireEvent.click(actions.at(-1)!);
  await waitFor(() => expect(nav.path).toBe(`/chat/${Y}`));
  const destination = screen.getByRole("textbox", { name: "Message" });
  expect(destination).not.toBe(source); expect(destination).toHaveValue("Unsubmitted original question");
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled());
  expect(requests()).toHaveLength(0); expect(rows.get(A)!.get(Y)!.turns).toEqual([]);
  expect(creationRequests()).toHaveLength(2); expect(creationRequests()[0][1]!.body).toBe(creationRequests()[1][1]!.body);
});
it("a normal first send clears only its submitted snapshot and a consumed handoff never resurrects on back/forward", async () => {
  await newChatWithDraft("One successful question");
  const source = screen.getByRole("textbox", { name: "Message" }); fireEvent.keyDown(source, { key: "Enter" });
  await screen.findByText("Server committed answer");
  expect(screen.getByRole("textbox", { name: "Message" })).not.toBe(source);
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(""); expect(requests()).toHaveLength(1);
  act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer");
  act(() => go(`/chat/${Y}`)); await screen.findByText("Server committed answer");
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(""); expect(requests()).toHaveLength(1);
});
it.each(["owner", "revision"])("a delayed creation cannot transfer a draft after verified %s change", async kind => {
  await newChatWithDraft("Old private draft"); const late = holdCreation();
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" });
  await waitFor(() => expect(creationRequests()).toHaveLength(1));
  if (kind === "owner") { cookie = B; fireEvent(window, new Event("focus")); await screen.findByText(`Verified ${B}`); }
  else { act(() => invalidateSessionRequests()); await waitFor(() => expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("")); }
  seed(A, Y, "Late A", []); await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 201)));
  expect(nav.path).toBe("/chat"); expect(requests()).toHaveLength(0);
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
});
it("intentional navigation disposes a pending creation and prevents extra turn submission or draft transfer", async () => {
  await newChatWithDraft("Abandoned first question"); const late = holdCreation();
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" }); await waitFor(() => expect(creationRequests()).toHaveLength(1));
  act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer");
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Destination draft" } });
  seed(A, Y, "Late result", []); await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 201)));
  expect(nav.path).toBe(`/chat/${X}`); expect(requests()).toHaveLength(0);
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Destination draft");
  act(() => go(`/chat/${Y}`)); await screen.findByText("Late result", { selector: "p" });
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
});
it("an available handoff follows the latest edits until navigation commits, then is consumed once", async () => {
  await newChatWithDraft("Submitted snapshot"); nav.replace.mockImplementation(() => {});
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" });
  await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`/chat/${Y}`));
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Edited before route commit" } });
  act(() => go(`/chat/${Y}`)); await screen.findByText("Server committed answer");
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Edited before route commit");
  act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer");
  act(() => go(`/chat/${Y}`)); await screen.findByText("Server committed answer");
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(""); expect(requests()).toHaveLength(1);
});
it.each(["unrelated route", "session revision", "expiry"])("an available handoff is invalidated by %s", async reason => {
  const timers = vi.spyOn(globalThis, "setTimeout");
  await newChatWithDraft("Submitted snapshot"); const late = holdCreation(); nav.replace.mockImplementation(() => {});
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" });
  await waitFor(() => expect(creationRequests()).toHaveLength(1));
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Unsubmitted handoff text" } });
  seed(A, Y, "Created", []); await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 201)));
  await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`/chat/${Y}`));
  if (reason === "unrelated route") { act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer"); }
  else if (reason === "session revision") act(() => invalidateSessionRequests());
  else {
    const expiry = timers.mock.calls.find(([, delay]) => delay === 60_000)?.[0];
    expect(expiry).toBeTypeOf("function"); act(() => (expiry as () => void)());
  }
  act(() => go(`/chat/${Y}`)); await screen.findByText("Server committed answer");
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(""); expect(requests()).toHaveLength(1);
});
it("stale reconciliation cannot overwrite an already edited destination composer", async () => {
  await newChatWithDraft("Unsubmitted source question"); let first = true; const late = deferred<Response>();
  intercept = (path, opts) => {
    if (path === "/conversations" && opts.method === "POST") {
      seed(A, Y, "Recovered", []);
      if (first) { first = false; return Promise.reject(new TypeError("Lost acknowledgement")); }
      return late.promise;
    }
  };
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" });
  const actions = await screen.findAllByRole("button", { name: "Recover chat" }); fireEvent.click(actions.at(-1)!);
  await waitFor(() => expect(creationRequests()).toHaveLength(2));
  act(() => go(`/chat/${Y}`)); await screen.findByText("Recovered", { selector: "p" });
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "New destination draft" } });
  await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 200)));
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("New destination draft");
  expect(nav.path).toBe(`/chat/${Y}`); expect(requests()).toHaveLength(0); expect(nav.replace).not.toHaveBeenCalled();
});
it("creation handoff does not clear the submitted snapshot before an accepted turn receipt", async () => {
  await newChatWithDraft("Awaiting turn acknowledgement"); const late = deferred<Response>();
  intercept = (path, opts) => path.endsWith("/turns") && opts.method === "POST" ? late.promise : undefined;
  const source = screen.getByRole("textbox", { name: "Message" }); fireEvent.keyDown(source, { key: "Enter" });
  await waitFor(() => expect(nav.path).toBe(`/chat/${Y}`));
  expect(screen.getByRole("textbox", { name: "Message" })).not.toBe(source);
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Awaiting turn acknowledgement");
  const body = JSON.parse(String(requests()[0][1]!.body));
  await act(async () => late.resolve(json({ ...fixture.submission, turn: { ...fixture.submission.turn,
    client_request_id: body.client_request_id, question: body.question } })));
  await screen.findByText("Synthetic canonical answer.");
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(""); expect(requests()).toHaveLength(1);
});
it("a failed turn preflight after creation keeps the unsubmitted draft at the destination", async () => {
  await newChatWithDraft("Never sent as a turn");
  let inspections = 0;
  intercept = (path, opts) => {
    if (path === "/auth/session" && opts.method !== "POST" && ++inspections === 2)
      return Promise.resolve(json({ detail: "Session inspection unavailable" }, 503));
  };
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" });
  await waitFor(() => expect(nav.path).toBe(`/chat/${Y}`));
  await screen.findByRole("button", { name: "Reconcile submission" });
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Never sent as a turn");
  expect(requests()).toHaveLength(0); expect(rows.get(A)!.get(Y)!.turns).toHaveLength(0);
});

// P1-D1-2: a newly mounted composer can recover shared creation state but
// cannot adopt its creation identity or transfer an unrelated conversation draft.
async function lostCreationFromOrigin() {
  await newChatWithDraft("Y originating unsent question");
  let lost = true;
  intercept = (path, opts) => {
    if (path === "/conversations" && opts.method === "POST") {
      const row = seed(A, Y, "Recovered Y", []);
      if (lost) { lost = false; return Promise.reject(new TypeError("Lost creation acknowledgement")); }
      return Promise.resolve(json(row.metadata, 200));
    }
  };
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" });
  await screen.findAllByRole("button", { name: "Recover chat" });
  return JSON.parse(String(creationRequests()[0][1]!.body)).create_request_id as string;
}
it.each(["composer", "sidebar"])("unrelated draft stays on X when %s recovers Y with the exact original creation identity", async control => {
  const creationId = await lostCreationFromOrigin();
  const origin = screen.getByRole("textbox", { name: "Message" });
  act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer");
  const input = screen.getByRole("textbox", { name: "Message" }); expect(input).not.toBe(origin);
  fireEvent.change(input, { target: { value: "X-specific private draft" } });
  const actions = screen.getAllByRole("button", { name: "Recover chat" });
  if (control === "sidebar") {
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    fireEvent.click(await screen.findByRole("button", { name: "Recover chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
  } else fireEvent.click(actions.at(-1)!);
  await screen.findByText(/Conversation recovered. It is available/);
  expect(nav.path).toBe(`/chat/${X}`); expect(input).toHaveValue("X-specific private draft");
  expect(screen.getByText("A saved answer")).toBeInTheDocument();
  expect(nav.push).not.toHaveBeenCalled(); expect(nav.replace).not.toHaveBeenCalled();
  expect(requests()).toHaveLength(0); expect(creationRequests()).toHaveLength(2);
  expect(creationRequests().map(([, opts]) => JSON.parse(String(opts!.body)).create_request_id)).toEqual([creationId, creationId]);
  expect(rows.get(A)!.get(Y)!.turns).toHaveLength(0);
  // Recovery is available through canonical history; explicitly opening Y never
  // adopts X's draft or resurrects the discarded origin's transfer permission.
  const link = screen.getByRole("link", { name: /Recovered Y/ });
  expect(link).toHaveAttribute("href", `/chat/${Y}`);
  act(() => go(link.getAttribute("href")!)); await screen.findByText("Recovered Y", { selector: "p" });
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(""); expect(requests()).toHaveLength(0);
});
it("returning to the originating URL creates no ownership for a replacement composer", async () => {
  await lostCreationFromOrigin(); act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer");
  act(() => go("/chat"));
  await screen.findByRole("button", { name: "Find the latest meeting notes." });
  const input = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(input, { target: { value: "Replacement new-chat draft" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Recover chat" }).at(-1)!);
  await screen.findByText(/Conversation recovered. It is available/);
  expect(nav.path).toBe("/chat"); expect(input).toHaveValue("Replacement new-chat draft");
  expect(requests()).toHaveLength(0); expect(creationRequests()).toHaveLength(2);
});
it("duplicate composer/sidebar recovery preserves X and reuses one creation request without duplicate attempts", async () => {
  const creationId = await lostCreationFromOrigin();
  act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer");
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Keep on X" } });
  const late = deferred<Response>();
  intercept = (path, opts) => path === "/conversations" && opts.method === "POST" ? late.promise : undefined;
  const actions = screen.getAllByRole("button", { name: "Recover chat" });
  fireEvent.click(actions.at(-1)!);
  fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
  fireEvent.click(await screen.findByRole("button", { name: "Recover chat" }));
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(actions.at(-1)!);
  await waitFor(() => expect(creationRequests()).toHaveLength(2));
  expect(JSON.parse(String(creationRequests()[1][1]!.body)).create_request_id).toBe(creationId);
  await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 200)));
  await screen.findByText(/Conversation recovered. It is available/);
  expect(nav.path).toBe(`/chat/${X}`); expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Keep on X");
  expect(requests()).toHaveLength(0); expect(creationRequests()).toHaveLength(2);
});
it("late unrelated recovery cannot override intentional navigation or the next composer's draft", async () => {
  await lostCreationFromOrigin(); act(() => go(`/chat/${X}`)); await screen.findByText("A saved answer");
  const late = deferred<Response>();
  intercept = (path, opts) => path === "/conversations" && opts.method === "POST" ? late.promise : undefined;
  fireEvent.click(screen.getAllByRole("button", { name: "Recover chat" }).at(-1)!);
  await waitFor(() => expect(creationRequests()).toHaveLength(2));
  act(() => go("/chat")); await screen.findByRole("button", { name: "Find the latest meeting notes." });
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Intentional destination draft" } });
  await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 200)));
  expect(nav.path).toBe("/chat"); expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Intentional destination draft");
  expect(requests()).toHaveLength(0); expect(nav.push).not.toHaveBeenCalled(); expect(nav.replace).not.toHaveBeenCalled();
});
it.each(["owner", "revision"])("old creation ownership cannot be reused during reconciliation after %s transition", async kind => {
  await lostCreationFromOrigin(); const late = deferred<Response>();
  intercept = (path, opts) => path === "/conversations" && opts.method === "POST" ? late.promise : undefined;
  fireEvent.click(screen.getAllByRole("button", { name: "Recover chat" }).at(-1)!);
  await waitFor(() => expect(creationRequests()).toHaveLength(2));
  if (kind === "owner") { cookie = B; fireEvent(window, new Event("focus")); await screen.findByText(`Verified ${B}`); }
  else act(() => invalidateSessionRequests());
  await screen.findByRole("button", { name: "Find the latest meeting notes." });
  fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "New session draft" } });
  await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 200)));
  expect(nav.path).toBe("/chat"); expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("New session draft");
  expect(requests()).toHaveLength(0); expect(nav.replace).not.toHaveBeenCalled();
});

// UX-B1: presentation uses the existing creation receipt; it grants no new permissions.
it("sidebar creation shows pending feedback once, preserves editable text and navigates only on acknowledgement", async () => {
  await newChatWithDraft("Keep this editable draft"); const late = holdCreation();
  const create = screen.getByRole("button", { name: "New Chat" });
  fireEvent.click(create); fireEvent.click(create);
  await waitFor(() => expect(creationRequests()).toHaveLength(1));
  expect(screen.getByRole("button", { name: "Creating chat…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Creating chat…" })).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Keep this editable draft");
  expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Recover chat" })).toBeNull();
  seed(A, Y, "Created once", []); await act(async () => late.resolve(json(rows.get(A)!.get(Y)!.metadata, 201)));
  await waitFor(() => expect(nav.path).toBe(`/chat/${Y}`));
  expect(creationRequests()).toHaveLength(1); expect(requests()).toHaveLength(0);
  expect(screen.queryByText(/We couldn't confirm/)).toBeNull();
});
it("uncertain creation has one primary recovery, explicit sending guidance and an unchanged receipt", async () => {
  const creationId = await lostCreationFromOrigin();
  expect(screen.getAllByRole("button", { name: "Recover chat" })).toHaveLength(1);
  expect(screen.getAllByText("We couldn't confirm the new chat. Recover it before starting another.")).toHaveLength(1);
  expect(screen.getByText("Recover the pending chat before sending. Your draft remains editable.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New Chat" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Y originating unsent question");
  fireEvent.click(screen.getByRole("button", { name: "Recover chat" }));
  await waitFor(() => expect(nav.path).toBe(`/chat/${Y}`));
  expect(creationRequests().map(([, opts]) => JSON.parse(String(opts!.body)).create_request_id)).toEqual([creationId, creationId]);
  expect(requests()).toHaveLength(0);
});
it("an unrelated list failure retains its own message and does not acquire creation recovery language", async () => {
  mount(); await screen.findByText("A saved answer");
  intercept = path => path.startsWith("/conversations?") ? Promise.resolve(json({ detail: "Unavailable" }, 503)) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Refresh conversations" }));
  await screen.findAllByText("Conversation service is unavailable.");
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Recover chat" })).toBeNull();
  expect(screen.queryByText(/We couldn't confirm the new chat/)).toBeNull();
  expect(screen.getByText("A saved answer")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New Chat" })).toBeEnabled();
});

it("recovery remains available outside Chat without forcing navigation or replaying a draft", async () => {
  const creationId = await lostCreationFromOrigin();
  act(() => go("/files")); await screen.findByText("Files view");
  expect(screen.getAllByRole("button", { name: "Recover chat" })).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Recover chat" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Recover chat" })).toBeNull());
  expect(nav.path).toBe("/files");
  expect(screen.getByRole("link", { name: /Recovered Y/ })).toHaveAttribute("href", `/chat/${Y}`);
  expect(creationRequests().map(([, opts]) => JSON.parse(String(opts!.body)).create_request_id)).toEqual([creationId, creationId]);
  expect(requests()).toHaveLength(0);
});
it("creation recovery retains a specific server error without claiming success", async () => {
  await newChatWithDraft("Unsent question");
  intercept = (path, opts) => path === "/conversations" && opts.method === "POST" ? Promise.resolve(json({ detail: "Unavailable" }, 503)) : undefined;
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Message" }), { key: "Enter" });
  await screen.findByRole("button", { name: "Recover chat" });
  expect(screen.getByRole("alert")).toHaveTextContent("Conversation service is unavailable.");
  expect(screen.getByRole("alert")).toHaveTextContent("We couldn't confirm the new chat.");
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Unsent question");
  expect(requests()).toHaveLength(0); expect(nav.path).toBe("/chat");
});

// UX-B2: history/navigation presentation delegates all mutations to existing handlers.
it("normal sidebar has one creation action, secondary history refresh and no ready-state chat footer", async () => {
  knowledge.ready = true; mount(); await screen.findByText("A saved answer");
  const sidebar = within(screen.getByRole("complementary", { name: "App navigation" }));
  expect(sidebar.getAllByRole("button", { name: "New Chat" })).toHaveLength(1);
  expect(sidebar.queryByRole("link", { name: "Open chat" })).toBeNull();
  expect(sidebar.getByText("1 document ready")).toBeInTheDocument();
  const heading = sidebar.getByRole("heading", { name: "Chats" });
  expect(heading.parentElement).toContainElement(sidebar.getByRole("button", { name: "Refresh conversations" }));
  expect(sidebar.getByRole("textbox", { name: "Search loaded chats" })).toHaveAttribute("placeholder", "Search loaded chats");
  expect(sidebar.getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
  expect(sidebar.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  expect(creationRequests()).toHaveLength(0);
});
it("loaded-title search makes no requests and includes later pages without losing its query", async () => {
  seed(A, Y, "Older travel chat", []);
  intercept = path => path === "/conversations?limit=30" ? Promise.resolve(json({ conversations: [rows.get(A)!.get(X)!.metadata], next_cursor: "more" }))
    : path.includes("cursor=more") ? Promise.resolve(json({ conversations: [rows.get(A)!.get(Y)!.metadata], next_cursor: null })) : undefined;
  mount(); await screen.findByText("A saved answer");
  const listRequests = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/conversations?"));
  const before = listRequests().length;
  const input = screen.getByRole("textbox", { name: "Search loaded chats" });
  fireEvent.change(input, { target: { value: "TRAVEL" } });
  expect(screen.getByText("No chats match your search.")).toBeInTheDocument();
  expect(listRequests()).toHaveLength(before);
  fireEvent.click(screen.getByRole("button", { name: "Load more conversations" }));
  await screen.findByRole("link", { name: /Older travel chat/ });
  expect(input).toHaveValue("TRAVEL");
  expect(screen.queryByRole("link", { name: /A title/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
  expect(screen.getByRole("link", { name: /A title/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Older travel chat/ })).toBeInTheDocument();
  expect(requests()).toHaveLength(0); expect(creationRequests()).toHaveLength(0);
});
it("keyboard refresh preserves the loaded-title query through loading", async () => {
  mount(); await screen.findByText("A saved answer");
  const input = screen.getByRole("textbox", { name: "Search loaded chats" });
  fireEvent.change(input, { target: { value: "title" } });
  const late = deferred<Response>();
  intercept = path => path.startsWith("/conversations?") ? late.promise : undefined;
  const refresh = screen.getByRole("button", { name: "Refresh conversations" });
  refresh.focus(); await userEvent.keyboard("{Enter}");
  await waitFor(() => expect(refresh).toBeDisabled());
  expect(input).toHaveValue("title");
  await act(async () => late.resolve(json({ conversations: [rows.get(A)!.get(X)!.metadata], next_cursor: null })));
  await waitFor(() => expect(refresh).toBeEnabled());
  expect(input).toHaveValue("title"); expect(screen.getByRole("link", { name: /A title/ })).toBeInTheDocument();
});
it("normal desktop collapse preserves search and stable navigation, then restores history", async () => {
  mount(); await screen.findByText("A saved answer");
  fireEvent.change(screen.getByRole("textbox", { name: "Search loaded chats" }), { target: { value: "title" } });
  const toggle = screen.getByRole("button", { name: "Collapse sidebar" });
  toggle.focus(); await userEvent.keyboard("{Enter}");
  expect(toggle).toHaveFocus();
  expect(screen.queryByRole("textbox", { name: "Search loaded chats" })).toBeNull();
  expect(screen.getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  await userEvent.keyboard("{Enter}");
  expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveFocus();
  expect(screen.getByRole("textbox", { name: "Search loaded chats" })).toHaveValue("title");
  expect(screen.getByRole("link", { name: /A title/ })).toHaveAttribute("aria-current", "page");
  expect(creationRequests()).toHaveLength(0);
});
it("collapsed non-chat recovery remains discoverable and expands without clearing its receipt", async () => {
  const id = await lostCreationFromOrigin(); act(() => go("/files")); await screen.findByText("Files view");
  fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
  const review = screen.getByRole("button", { name: "Expand sidebar to review chat status" });
  review.focus(); await userEvent.keyboard("{Enter}");
  expect(screen.getByRole("heading", { name: "Chats" })).toBeInTheDocument();
  const recover = screen.getByRole("button", { name: "Recover chat" });
  expect(recover).toBeVisible(); expect(recover).toBeEnabled(); expect(recover).toHaveFocus();
  expect(review).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New Chat" })).toBeDisabled();
  expect(creationRequests()).toHaveLength(1);
  expect(JSON.parse(String(creationRequests()[0][1]!.body)).create_request_id).toBe(id);
  expect(requests()).toHaveLength(0); expect(nav.path).toBe("/files");
  fireEvent.click(screen.getByRole("button", { name: "Recover chat" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Recover chat" })).toBeNull());
  expect(creationRequests().map(([, opts]) => JSON.parse(String(opts!.body)).create_request_id)).toEqual([id,id]);
  expect(nav.path).toBe("/files"); expect(requests()).toHaveLength(0);
});

it("Review focuses the stable collapse control when expanded feedback has no recovery action", async () => {
  go("/files"); mount(); await screen.findByText(`Verified ${A}`);
  await screen.findByRole("link", { name: /A title/ });
  intercept = path => path.startsWith("/conversations?") ? Promise.resolve(json({ detail: "Unavailable" }, 503)) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Refresh conversations" }));
  await screen.findByText("Conversation service is unavailable.");
  fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
  screen.getByRole("button", { name: "Expand sidebar to review chat status" }).focus();
  const before = vi.mocked(fetch).mock.calls.length;
  await userEvent.keyboard("{Enter}");
  const toggle = screen.getByRole("button", { name: "Collapse sidebar" });
  expect(toggle).toBeVisible(); expect(toggle).toBeEnabled(); expect(toggle).toHaveFocus();
  expect(screen.queryByRole("button", { name: "Recover chat" })).toBeNull();
  expect(vi.mocked(fetch).mock.calls).toHaveLength(before);
  expect(creationRequests()).toHaveLength(0); expect(requests()).toHaveLength(0);
  expect(nav.path).toBe("/files");
});

it("mobile navigation has the same history hierarchy and restores focus after Escape", async () => {
  knowledge.ready = true; mount(); await screen.findByText("A saved answer");
  const trigger = screen.getByRole("button", { name: "Open navigation menu" }); trigger.focus();
  await userEvent.keyboard("{Enter}");
  const dialog = await screen.findByRole("dialog", { name: "Navigation" });
  const drawer = within(dialog);
  expect(drawer.getByRole("heading", { name: "Chats" })).toBeInTheDocument();
  expect(drawer.getAllByRole("button", { name: "New Chat" })).toHaveLength(1);
  expect(drawer.queryByRole("link", { name: "Open chat" })).toBeNull();
  expect(drawer.getByRole("textbox", { name: "Search loaded chats" })).toBeInTheDocument();
  expect(drawer.queryByRole("button", { name: "Collapse sidebar" })).toBeNull();
  expect(drawer.getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
  expect(drawer.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull());
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(creationRequests()).toHaveLength(0);
});
