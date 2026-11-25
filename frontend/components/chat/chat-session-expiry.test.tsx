// @vitest-environment jsdom
// Restores the critical guarantee of the removed session-browser-boundary test ("mid-stream session expiry clears
// private output and reauthentication observes the interrupted attempt without replay") against the rebuilt UI:
// the real session boundary, workspace and chat screen, with only fetch and Next navigation stubbed.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "@/lib/api/fixtures/conversation-backend-dto.json";
import { ApplicationSessionProvider } from "@/components/providers/application-session-provider";
import { WorkspaceRoot } from "@/components/workspace/workspace-root";
import { ChatWorkspace } from "@/components/chat/chat-workspace";
import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { setSessionOwner } from "@/lib/api/session-events";

const OWNER = "00000000-0000-4000-8000-000000000065";
const X = fixture.metadata.id;
vi.mock("next/navigation", () => ({
  usePathname: () => `/chat/${X}`,
  useParams: () => ({ id: X }),
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const encoder = new TextEncoder();
const frame = (event: string, data: unknown) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }

/** A tiny synthetic backend: the session can be switched off, and the question request is held open. */
function backend(streaming: boolean) {
  const state = { signedIn: true, turnPosts: 0 };
  const held = deferred<Response>();
  let pipe: ReadableStreamDefaultController<Uint8Array> | null = null;
  const fetch = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, "http://localhost"); const path = url.pathname.replace(/^\/api\/v1/, ""); const method = init?.method ?? "GET";
    if (path === "/auth/session" && method === "GET")
      return state.signedIn ? json({ kind: "GOOGLE_ACCOUNT", user_id: OWNER, csrf_token: "synthetic-csrf" }) : json({ detail: "Session expired" }, 401);
    if (!state.signedIn) return json({ detail: "Session expired" }, 401);
    if (path === "/files") return json({ files: [{ id: "00000000-0000-4000-8000-000000000106", user_id: OWNER, drive_file_id: "synthDrive1", name: "synthetic.txt",
      mime_type: "text/plain", folder_path: null, modified_at: "2026-10-01T00:00:00Z", indexed_at: "2026-10-02T00:00:00Z", status: "indexed",
      created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-02T00:00:00Z" }], total: 1 });
    if (path === "/index/status") return json({ connected: true, demo_mode: false, job: null });
    if (path === "/conversations" && method === "GET") return json({ conversations: [fixture.metadata], next_cursor: null });
    if (path === `/conversations/${X}` && method === "GET") return json(fixture.detail);
    if (path.startsWith(`/conversations/${X}/turns`) && method === "POST") {
      state.turnPosts += 1;
      if (!streaming) return held.promise;
      const body = JSON.parse(String(init?.body)) as { client_request_id: string; question: string };
      const running = { ...fixture.submission, turn: { ...fixture.submission.turn, id: "00000000-0000-4000-8000-0000000002a1", sequence: 2,
        client_request_id: body.client_request_id, question: body.question, status: "RUNNING", answer: null, citations: [], query_id: null, finished_at: null, error_code: null, retrieval_count: 0 } };
      const stream = new ReadableStream<Uint8Array>({ start(c) { pipe = c; c.enqueue(frame("accepted", running)); c.enqueue(frame("provisional", { text: "Private provisional words" })); } });
      init?.signal?.addEventListener("abort", () => { try { pipe?.error(new DOMException("Aborted", "AbortError")); } catch { /* closed */ } }, { once: true });
      return new Response(stream, { headers: { "content-type": "text/event-stream" } });
    }
    return json({ detail: "Not found" }, 404);
  });
  vi.stubGlobal("fetch", fetch);
  return { state, held, fetch, pipe: () => pipe };
}

function App() {
  return (
    <ToastProvider><TooltipProvider><ApplicationSessionProvider><WorkspaceRoot><ChatWorkspace /></WorkspaceRoot></ApplicationSessionProvider></TooltipProvider></ToastProvider>
  );
}

// Node 26 defines its own global localStorage getter that returns undefined, shadowing jsdom's. A real in-memory
// Storage is installed so the app's storage use (and the "nothing private stored" check) is actually exercised.
class MemoryStorage implements Storage {
  private map = new Map<string, string>();
  get length() { return this.map.size; }
  clear() { this.map.clear(); }
  getItem(key: string) { return this.map.has(key) ? this.map.get(key)! : null; }
  key(index: number) { return [...this.map.keys()][index] ?? null; }
  removeItem(key: string) { this.map.delete(key); }
  setItem(key: string, value: string) { this.map.set(key, String(value)); }
  entries() { return [...this.map.entries()]; }
}
let local: MemoryStorage;
beforeEach(() => {
  local = new MemoryStorage(); vi.stubGlobal("localStorage", local); window.sessionStorage.clear();
  // jsdom has no matchMedia; the layout asks for breakpoints and reduced motion.
  Element.prototype.scrollTo = function scrollTo() {};
  vi.stubGlobal("matchMedia", (media: string) => ({ matches: false, media, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); setSessionOwner(null); });

it.each([false, true])("session expiry during an active question hides private output at once and never replays it (streaming=%s)", async streaming => {
  vi.stubEnv("NEXT_PUBLIC_CHAT_STREAMING_ENABLED", streaming ? "true" : "false");
  const server = backend(streaming);
  render(<App />);
  expect(await screen.findByText("Synthetic canonical answer.")).toBeInTheDocument();

  const composer = await screen.findByRole("textbox", { name: /question/i });
  fireEvent.change(composer, { target: { value: "Private follow-up question" } });
  fireEvent.keyDown(composer, { key: "Enter" });
  await waitFor(() => expect(server.state.turnPosts).toBe(1));
  expect(await screen.findAllByText("Private follow-up question")).not.toHaveLength(0);
  if (streaming) expect(await screen.findByText(/Private provisional words/)).toBeInTheDocument();

  // The session ends while the question is still running; the next verification sees 401.
  server.state.signedIn = false;
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(await screen.findByText(/Your session expired/)).toBeInTheDocument();
  expect(screen.queryByText("Synthetic canonical answer.")).not.toBeInTheDocument();
  expect(screen.queryByText("Private follow-up question")).not.toBeInTheDocument();
  expect(screen.queryByText(/Private provisional words/)).not.toBeInTheDocument();

  // A late answer from the ended session cannot bring anything back.
  await act(async () => {
    if (streaming) { try { server.pipe()?.enqueue(frame("provisional", { text: "Late private words" })); } catch { /* aborted */ } }
    else server.held.resolve(json({ ...fixture.submission, turn: { ...fixture.submission.turn, answer: "Late private answer." } }));
  });
  expect(screen.queryByText(/Late private/)).not.toBeInTheDocument();

  // Signing in again (announced by another tab) reloads the conversation from the server and does not resend.
  server.state.signedIn = true;
  await act(async () => { window.dispatchEvent(new StorageEvent("storage", { key: "drivemind:session-transition:v1", newValue: "signed-in-elsewhere" })); });
  expect(await screen.findByText("Synthetic canonical answer.")).toBeInTheDocument();
  expect(server.state.turnPosts).toBe(1);
  expect(screen.queryByText(/Late private/)).not.toBeInTheDocument();
});

it("normal mode keeps no question or answer text in browser storage once sent", async () => {
  vi.stubEnv("NEXT_PUBLIC_CHAT_STREAMING_ENABLED", "false");
  const server = backend(false);
  render(<App />);
  await screen.findByText("Synthetic canonical answer.");
  const composer = await screen.findByRole("textbox", { name: /question/i });
  fireEvent.change(composer, { target: { value: "Private follow-up question" } });
  fireEvent.keyDown(composer, { key: "Enter" });
  await waitFor(() => expect(server.state.turnPosts).toBe(1));
  const stored = local.entries().map(([k, v]) => `${k}=${v}`).join("\n") + "\n" + Object.keys(window.sessionStorage).map(k => `${k}=${window.sessionStorage.getItem(k)}`).join("\n");
  expect(stored).not.toContain("Private follow-up question");
  expect(stored).not.toContain("Synthetic canonical answer.");
});
