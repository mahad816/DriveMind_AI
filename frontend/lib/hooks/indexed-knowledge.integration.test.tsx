import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConversationSidebar } from "@/components/layout/conversation-sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useIndexedKnowledge } from "./use-indexed-knowledge";
import { listDriveFiles } from "@/lib/api/files";
import { invalidateSessionRequests, sessionOwner, sessionRevision, setSessionOwner } from "@/lib/api/session-events";
const owner = "00000000-0000-0000-0000-000000000065", other = "00000000-0000-0000-0000-000000000066";
vi.mock("next/navigation", () => ({ usePathname: () => "/files", useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/providers/server-conversations-provider", () => ({ useServerConversations: () => ({ state: { ownerId: owner, conversations: [], sessionRevision: 0 } }) }));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: () => ({ data: { connected: false, job: null }, error: null, isLoading: false, refetch: vi.fn() }) }));
let indexed: boolean, unavailable: boolean;
let intercept: (() => Promise<Response> | undefined) | null;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const inventory = (id = sessionOwner()) => ({ files: indexed ? [{ user_id: id, status: "indexed" }] : [], total: indexed ? 1 : 0 });
function ChatStatus() { const readiness = useIndexedKnowledge(sessionOwner(), sessionRevision()); return <p>Chat: {readiness.status}</p>; }
function mount() { return render(<TooltipProvider><ConversationSidebar /><ChatStatus /></TooltipProvider>); }
beforeEach(() => {
  setSessionOwner(owner); invalidateSessionRequests(); indexed = false; unavailable = false; intercept = null;
  vi.stubGlobal("fetch", vi.fn(() => intercept?.() ?? Promise.resolve(unavailable ? json({ detail: "Offline" }, 503) : json(inventory()))));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setSessionOwner(null); });
it("sidebar and chat reflect a fresh indexed inventory read without Drive or polling", async () => {
  mount(); await screen.findByText("Chat: empty"); expect(screen.getByText("Connect Drive to choose documents")).toBeInTheDocument();
  const before = vi.mocked(fetch).mock.calls.length;
  indexed = true; await act(async () => { await listDriveFiles(); });
  expect(screen.getByText("1 document ready")).toBeInTheDocument(); expect(screen.getByText("Chat: ready")).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls).toHaveLength(before + 1);
  expect(vi.mocked(fetch).mock.calls.every(([, opts]) => !opts?.method || opts.method === "GET")).toBe(true);
  expect(screen.queryByRole("link", { name: "Knowledge" })).toBeNull();
  expect(screen.getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
});
it("inventory failure is unavailable, not a definitive empty state", async () => {
  indexed = true; mount(); await screen.findByText("Chat: ready"); unavailable = true;
  await act(async () => { await listDriveFiles().catch(() => {}); });
  expect(screen.getByText("Knowledge status unavailable")).toBeInTheDocument();
  expect(screen.getByText("Chat: unavailable")).toBeInTheDocument(); expect(screen.queryByText("Connect Drive to choose documents")).toBeNull();
});
it("an older successful inventory response cannot overwrite a newer unavailable response", async () => {
  mount(); await screen.findByText("Chat: empty"); let resolve!: (value: Response) => void;
  intercept = () => new Promise(done => { resolve = done; }); const old = listDriveFiles();
  intercept = null; unavailable = true;
  await act(async () => { await listDriveFiles().catch(() => {}); });
  indexed = true; await act(async () => { resolve(json(inventory())); await old; });
  expect(screen.getByText("Chat: unavailable")).toBeInTheDocument();
});
it("an aborted newer read does not strand an older valid completion in checking", async () => {
  mount(); await screen.findByText("Chat: empty"); let resolve!: (value: Response) => void;
  intercept = () => new Promise(done => { resolve = done; }); const old = listDriveFiles();
  const abort = new AbortController(); abort.abort();
  intercept = () => Promise.reject(new DOMException("Aborted", "AbortError"));
  await listDriveFiles(abort.signal).catch(() => {});
  indexed = true; await act(async () => { resolve(json(inventory())); await old; });
  expect(screen.getByText("Chat: ready")).toBeInTheDocument();
});
it("owner/session changes fence late responses and clear previous readiness", async () => {
  mount(); await screen.findByText("Chat: empty"); let resolve!: (value: Response) => void;
  let parked = false;
  intercept = () => { if (parked) return undefined; parked = true; return new Promise(done => { resolve = done; }); }; const old = listDriveFiles();
  act(() => { setSessionOwner(other); invalidateSessionRequests(); });
  indexed = true; await act(async () => { resolve(json(inventory(owner))); await old.catch(() => {}); });
  expect(screen.queryByText("Chat: ready")).toBeNull(); expect(screen.queryByText("1 document ready")).toBeNull();
});
it("another owner's metadata is unavailable and never published as ready", async () => {
  intercept = () => Promise.resolve(json({ files: [{ user_id: other, status: "indexed" }], total: 1 }));
  mount(); await screen.findByText("Chat: unavailable"); expect(screen.queryByText("1 document ready")).toBeNull();
});
