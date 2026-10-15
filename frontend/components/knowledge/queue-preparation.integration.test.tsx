import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { KnowledgeLibrary } from "@/components/files/knowledge-library";
import { QueuePreparationView } from "./queue-preparation-view";
import { PreparationView } from "./preparation-view";
import { preparationKey } from "@/lib/knowledge/single-file-preparation";
import { PreparationQueue } from "@/lib/knowledge/preparation-queue";
import { invalidateSessionRequests, setSessionOwner } from "@/lib/api/session-events";
import type { DriveFileRead, IndexingJobRead } from "@/lib/api/types";
const fixture = vi.hoisted(() => ({ owner: "00000000-0000-0000-0000-000000000065", demo: false, params: new URLSearchParams() }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return fixture.demo; } }));
vi.mock("@/components/providers/application-session-provider", () => ({ useApplicationSession: () => ({ userId: fixture.owner }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), useSearchParams: () => fixture.params }));
vi.mock("@/lib/hooks/use-connection-status", () => ({ useConnectionStatus: () => ({ data: { connected: true }, isLoading: false, error: null, refetch: vi.fn() }) }));
vi.mock("@/components/files/drive-discovery", () => ({ DriveDiscovery: () => <p>Metadata discovery</p> }));
vi.mock("@/components/files/file-preview-sheet", () => ({ FilePreviewSheet: () => null }));
const owner = fixture.owner, key = preparationKey(owner);
let files: DriveFileRead[], values: Map<string, string>, latest: IndexingJobRead | null, jobs: Map<string, IndexingJobRead>, count: number;
let intercept: (p: string, i: RequestInit) => Promise<Response> | undefined;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const stored = () => JSON.parse(values.get(key)!);
const posts = () => vi.mocked(fetch).mock.calls.filter(([, i]) => i?.method === "POST").map(([p]) => String(p));
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { resolve, promise }; }
beforeEach(() => {
  fixture.demo = false; fixture.params = new URLSearchParams(); setSessionOwner(owner); values = new Map(); jobs = new Map(); latest = null; count = 0; intercept = () => undefined;
  files = Array.from({ length: 7 }, (_, n) => ({ id: `00000000-0000-0000-0001-${String(n + 1).padStart(12, "0")}`, user_id: owner, drive_file_id: `synthetic-${n}`, name: `Document ${n + 1}.txt`, mime_type: "text/plain", status: "discovered", modified_at: "2026-01-01", indexed_at: null, folder_path: null, created_at: "", updated_at: "" }));
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) } });
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_k: string, fn: () => unknown) => fn() } });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ matches: false }) });
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit = {}) => {
    const custom = intercept(path, init); if (custom) return custom;
    const url = new URL(path, "http://localhost");
    if (url.pathname === "/api/v1/files") return json({ files, total: files.length });
    if (url.pathname === "/api/v1/auth/session") return json({ user_id: owner, csrf_token: "synthetic" });
    if (url.pathname === "/api/v1/index/status") return json({ connected: true, job: url.searchParams.has("job_id") ? jobs.get(url.searchParams.get("job_id")!) : latest });
    expect(init.method).toBe("POST"); expect(url.pathname).toMatch(/^\/api\/v1\/index\/(ingest|chunk|build)$/);
    expect(!latest || !["queued", "running"].includes(latest.status)).toBe(true);
    const file = files.find(f => f.id === url.searchParams.get("file_id")); expect(file).toBeDefined();
    latest = { id: `00000000-0000-0002-0000-${String(++count).padStart(12, "0")}`, user_id: owner, file_id: file!.id, operation: url.pathname.split("/").at(-1)!.toUpperCase() as IndexingJobRead["operation"], status: "running", recovery_required: false, total: 1, processed: 0, succeeded: 0, skipped: 0, failed: 0, started_at: null, completed_at: null, error: null, created_at: "", updated_at: "" };
    jobs.set(latest.id, latest); file!.status = "indexing"; return json({ job_id: latest.id, status: "queued" }, 202);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setSessionOwner(null); });
async function select(index: number) { await userEvent.click(await screen.findByRole("checkbox", { name: `Select Document ${index}.txt for preparation` })); }
async function review(number = 3) {
  render(<KnowledgeLibrary />); for (let n = 1; n <= number; n++) await select(n);
  await userEvent.click(screen.getByRole("button", { name: `Review ${number} ${number === 1 ? "document" : "documents"}` }));
  return screen.findByRole("button", { name: "Prepare first document" });
}
async function finishStage(extra: Partial<IndexingJobRead> = {}) {
  await act(async () => {
    Object.assign(latest!, { status: "completed", processed: 1, succeeded: 1, ...extra });
    files.find(f => f.id === latest!.file_id)!.status = latest!.operation === "BUILD" ? "indexed" : "indexing";
    fireEvent.click(screen.getByRole("button", { name: "Check status" }));
  });
}
async function finishFile() {
  const before = posts().length; await finishStage(); await waitFor(() => expect(posts()).toHaveLength(before + 1));
  await finishStage(); await waitFor(() => expect(posts()).toHaveLength(before + 2)); await finishStage();
  await waitFor(() => expect(stored().entries[stored().current - 1]?.result).toBe("ready"));
}

it("keeps ordered unique selection independent from preview, search, filter and refresh, with a five-file limit", async () => {
  render(<KnowledgeLibrary />); await select(3); await select(1);
  const selection = within(screen.getByRole("list", { name: "Selected documents" }));
  expect(selection.getAllByRole("listitem").map(li => li.textContent)).toEqual([expect.stringContaining("Document 3"), expect.stringContaining("Document 1")]);
  await userEvent.click(screen.getByRole("button", { name: /Document 2.txt/ })); expect(screen.getByRole("region", { name: "File inspector" })).toHaveTextContent("Document 2.txt");
  expect(screen.getByText("2 of 5 documents selected")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "Search files" }), { target: { value: "Document 7" } });
  await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(1)); expect(screen.getByText("2 of 5 documents selected")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "Search files" }), { target: { value: "" } });
  await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(7));
  await userEvent.click(screen.getByRole("button", { name: "Ready (0)" })); expect(screen.getByText("2 of 5 documents selected")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "All (7)" })); await userEvent.click(screen.getByRole("button", { name: "Reload file list" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Review 2 documents" })).toBeEnabled());
  await select(2); await select(4); await select(5); expect(screen.getByText(/Five-document limit/, { selector: "p" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Select Document 6.txt for preparation" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Select Document 6.txt for preparation" })).toHaveAccessibleDescription(/Five-document limit/);
  expect(screen.getAllByRole("checkbox").every(box => !box.closest("button"))).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Remove Document 1.txt from selection" })); expect(screen.getByRole("checkbox", { name: "Select Document 6.txt for preparation" })).toBeEnabled(); expect(posts()).toEqual([]);
});
it("review and cancel cause no processing or reservation and preserve the draft", async () => {
  await review(2); expect(values.has(key)).toBe(false); expect(posts()).toEqual([]);
  expect(screen.getByRole("list", { name: "Documents in preparation order" })).toHaveTextContent("Document 1.txt");
  await userEvent.click(screen.getByRole("button", { name: "Cancel review" })); expect(await screen.findByRole("button", { name: "Review 2 documents" })).toBeEnabled(); expect(posts()).toEqual([]); expect(values.has(key)).toBe(false);
});
it.each(["modified", "ineligible", "missing"])("%s metadata after refresh preserves draft identity and blocks review", async change => {
  render(<KnowledgeLibrary />); await select(1);
  if (change === "modified") files[0].modified_at = "2026-02-01"; else if (change === "ineligible") files[0].status = "failed"; else files.splice(0, 1);
  await userEvent.click(screen.getByRole("button", { name: "Reload file list" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("A selected document changed"));
  expect(screen.getByRole("list", { name: "Selected documents" })).toHaveTextContent("Document 1.txt"); expect(screen.getByRole("button", { name: "Review 1 document" })).toBeDisabled(); expect(posts()).toEqual([]);
});
it("metadata changing on the review screen blocks reservation without silently omitting a file", async () => {
  await review(2); files[1].status = "skipped";
  await userEvent.click(screen.getByRole("button", { name: "Check status" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Prepare first document" })).toBeDisabled());
  expect(screen.getByRole("list", { name: "Documents in preparation order" })).toHaveTextContent("Needs attention"); expect(values.has(key)).toBe(false); expect(posts()).toEqual([]);
});
it("one deliberate start freezes the reviewed order and three files require three explicit document confirmations", async () => {
  const start = await review(3); start.focus(); await userEvent.keyboard("{Enter}");
  await waitFor(() => expect(posts()).toHaveLength(1)); expect(stored().entries.map((e: { fileId: string }) => e.fileId)).toEqual(files.slice(0, 3).map(f => f.id));
  await finishFile(); expect(posts()).toHaveLength(3); await userEvent.click(await screen.findByRole("button", { name: "Check status" })); expect(posts()).toHaveLength(3);
  await userEvent.click(await screen.findByRole("button", { name: "Prepare next document" })); await waitFor(() => expect(posts()).toHaveLength(4)); await finishFile(); expect(posts()).toHaveLength(6);
  await userEvent.click(await screen.findByRole("button", { name: "Prepare next document" })); await waitFor(() => expect(posts()).toHaveLength(7)); await finishFile();
  expect(await screen.findByRole("heading", { name: "Documents ready" })).toBeInTheDocument(); expect(posts()).toEqual(files.slice(0, 3).flatMap(f => ["ingest", "chunk", "build"].map(s => `/api/v1/index/${s}?file_id=${f.id}`)));
  expect(screen.getByRole("link", { name: "Start chatting" })).toHaveAttribute("href", "/chat"); expect(screen.getByText(/not only this selection/)).toBeInTheDocument();
});
it("duplicate confirmation cannot duplicate the actual targeted POST", async () => {
  const start = await review(1); fireEvent.click(start); fireEvent.click(start);
  await waitFor(() => expect(posts()).toHaveLength(1)); expect(stored().entries[0].receipts).toHaveLength(1); expect(stored().entries[0].receipts[0].jobId).toBe(latest!.id);
});
it("partial failure preserves ready results and never starts the third document", async () => {
  await userEvent.click(await review(3)); await waitFor(() => expect(posts()).toHaveLength(1)); await finishFile();
  await userEvent.click(await screen.findByRole("button", { name: "Prepare next document" })); await waitFor(() => expect(posts()).toHaveLength(4));
  await finishStage({ status: "failed", failed: 1, succeeded: 0 });
  await waitFor(() => expect(screen.getByRole("button", { name: "End preparation" })).toBeInTheDocument());
  expect(stored().entries.map((e: { result: string }) => e.result)).toEqual(["ready", "failed", "pending"]); expect(screen.queryByRole("heading", { name: "Documents ready" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Prepare next document" })).toBeNull(); expect(screen.getByRole("link", { name: "Start chatting" })).toBeInTheDocument(); expect(posts()).toHaveLength(4);
});
it("unmount during preflight prevents POST; remount observes the saved queue without authorization", async () => {
  const entered = deferred<void>(), response = deferred<Response>(); const start = await review(2);
  intercept = p => p.endsWith("/auth/session") ? (entered.resolve(), response.promise) : undefined;
  fireEvent.click(start); await entered.promise; cleanup(); response.resolve(json({ user_id: owner, csrf_token: "synthetic" }));
  await act(async () => { await response.promise; }); intercept = () => undefined;
  render(<QueuePreparationView owner={owner} />); await screen.findByRole("button", { name: "Prepare first document" }); expect(posts()).toEqual([]); expect(stored().entries[0].receipts).toEqual([]);
});
it("refresh during accepted work observes the exact receipt without advancing after completion", async () => {
  const start = await review(2); await userEvent.click(start); await waitFor(() => expect(posts()).toHaveLength(1)); const job = latest!.id; cleanup();
  render(<PreparationView />); await screen.findByRole("heading", { name: "Document preparation" });
  await finishStage(); await screen.findByRole("button", { name: "Continue preparation" }); expect(posts()).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.some(([p]) => String(p).includes(`job_id=${job}`))).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Continue preparation" })); await waitFor(() => expect(posts()).toHaveLength(2));
});
it("an unknown acknowledgement has no retry/next action and cannot report whole-queue success", async () => {
  const start = await review(2); intercept = (_p, i) => i.method === "POST" ? Promise.reject(new TypeError("Lost response")) : undefined;
  await userEvent.click(start); await waitFor(() => expect(screen.getByText(/Preparation has stopped/)).toBeInTheDocument());
  expect(stored().entries[0].receipts[0].jobId).toBeNull(); expect(screen.queryByRole("button", { name: "Prepare next document" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Check status" })); expect(posts()).toHaveLength(1);
});
it("existing unresolved work blocks new selection and is surfaced through preparation progress", async () => {
  const q = new PreparationQueue(owner); expect(await q.reserve(files.slice(0, 2))).toBe(true); render(<KnowledgeLibrary />);
  expect(await screen.findByRole("checkbox", { name: "Select Document 1.txt for preparation" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "Review existing preparation" })).toHaveAttribute("href", "/prepare"); expect(posts()).toEqual([]);
});
it("owner/session invalidation clears draft and fences delayed private updates", async () => {
  render(<KnowledgeLibrary />); await select(1); const entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p === "/api/v1/files" ? (entered.resolve(), response.promise) : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Reload file list" })); await entered.promise;
  act(() => { setSessionOwner("00000000-0000-0000-0000-000000000066"); invalidateSessionRequests(); });
  response.resolve(json({ files, total: files.length })); await act(async () => { await response.promise; });
  expect(screen.getByText("0 of 5 documents selected")).toBeInTheDocument(); expect(screen.queryByRole("checkbox")).toBeNull(); expect(screen.queryByRole("button", { name: "Review 1 document" })).toBeNull(); expect(posts()).toEqual([]);
});
it("prepare route preserves the legacy single-file review and fails closed on unknown saved versions", async () => {
  fixture.params = new URLSearchParams({ file: files[0].id }); const view = render(<PreparationView />);
  await screen.findByRole("button", { name: "Prepare this document" }); expect(posts()).toEqual([]); view.unmount();
  values.set(key, JSON.stringify({ schemaVersion: 99 })); render(<PreparationView />);
  await screen.findByText(/Queue status could not be verified/); expect(screen.queryByRole("button", { name: "Prepare this document" })).toBeNull(); expect(posts()).toEqual([]);
});
it("HarborDesk keeps its preview-only rows and has no multi-file preparation controls", async () => {
  fixture.demo = true; render(<KnowledgeLibrary />);
  // The normal-mode preparation UI is never mounted, including while demo connection is unavailable.
  expect(screen.queryByRole("checkbox")).toBeNull(); expect(screen.queryByRole("region", { name: "Preparation selection" })).toBeNull(); expect(screen.queryByText(/of 5 documents selected/)).toBeNull(); expect(posts()).toEqual([]);
});

it("hiding the preparation UI during preflight pauses permission before POST", async () => {
  const start = await review(2), entered = deferred<void>(), response = deferred<Response>();
  intercept = p => p.endsWith("/auth/session") ? (entered.resolve(), response.promise) : undefined;
  fireEvent.click(start); await entered.promise;
  Object.defineProperty(document, "hidden", { configurable: true, value: true });
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  response.resolve(json({ user_id: owner, csrf_token: "synthetic" }));
  await waitFor(() => expect(stored().entries[0].receipts).toEqual([]));
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  expect(posts()).toEqual([]);
});
it("accepted acknowledgement arriving after unmount persists its exact receipt for a read-only remount", async () => {
  const start = await review(2), entered = deferred<void>(), release = deferred<void>();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (path, init) => {
    const response = await original(path, init);
    if (init?.method === "POST") { entered.resolve(); await release.promise; }
    return response;
  });
  fireEvent.click(start); await entered.promise; const id = latest!.id; cleanup(); release.resolve();
  await waitFor(() => expect(stored().entries[0].receipts[0].jobId).toBe(id));
  render(<PreparationView />); await screen.findByRole("heading", { name: "Document preparation" });
  await userEvent.click(screen.getByRole("button", { name: "Check status" })); expect(posts()).toHaveLength(1);
  expect(stored().entries[0].receipts[0].jobId).toBe(id);
});
