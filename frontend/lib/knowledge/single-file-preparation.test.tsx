import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { SingleFilePreparation, preparationEligibility, preparationKey } from "./single-file-preparation";
import { setSessionOwner, invalidateSessionRequests, SESSION_INVALID_EVENT } from "@/lib/api/session-events";
import { submitFilePreparationStage } from "@/lib/api/indexing";
import type { DriveFileRead, IndexingJobRead } from "@/lib/api/types";
const mode = vi.hoisted(() => ({ demo: false }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return mode.demo; } }));
const owner = "00000000-0000-0000-0000-000000000065", other = "00000000-0000-0000-0000-000000000066";
const fileId = "00000000-0000-0000-0000-000000000101";
const ids = ["00000000-0000-0000-0000-000000000201", "00000000-0000-0000-0000-000000000202", "00000000-0000-0000-0000-000000000203"];
const key = preparationKey(owner), discovery = `drivemind:discovery:v1:${owner}`;
let file: DriveFileRead, latest: IndexingJobRead | null, jobs: Map<string, IndexingJobRead>, values: Map<string,string>;
let intercept: (path: string, init: RequestInit) => Promise<Response> | undefined;
let connected: boolean;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { resolve, promise }; }
const writes = () => vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
function complete(extra: Partial<IndexingJobRead> = {}) {
  Object.assign(latest!, { status: "completed", processed: 1, succeeded: 1, ...extra });
  file.status = latest!.operation === "BUILD" ? "indexed" : "indexing";
}
async function controller() { const c = new SingleFilePreparation(owner, fileId); await c.check(); return c; }
beforeEach(() => {
  mode.demo = false; setSessionOwner(owner); connected = true; values = new Map(); jobs = new Map(); latest = null; intercept = () => undefined;
  file = { id: fileId, user_id: owner, drive_file_id: "synthetic-drive", name: "Synthetic document.txt", mime_type: "text/plain", status: "discovered", folder_path: null, modified_at: "2026-01-01", indexed_at: null, created_at: "", updated_at: "" };
  Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k,v), removeItem: (k: string) => values.delete(k) } });
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_key: string, fn: () => unknown) => fn() } });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const custom = intercept(url, init); if (custom) return custom;
    const path = new URL(url, "http://localhost");
    if (path.pathname === "/api/v1/files") return json({ files: [file], total: 1 });
    if (path.pathname === "/api/v1/auth/session") return json({ user_id: owner, csrf_token: "synthetic" });
    if (path.pathname === "/api/v1/index/status") return json({ connected, job: path.searchParams.has("job_id") ? jobs.get(path.searchParams.get("job_id")!) : latest });
    const stage = path.pathname.split("/").at(-1)!.toUpperCase();
    if (["INGEST", "CHUNK", "BUILD"].includes(stage)) {
      expect(init.method).toBe("POST"); expect(path.searchParams.get("file_id")).toBe(fileId);
      expect(init.headers).toMatchObject({ "X-CSRF-Token": "synthetic" });
      const id = ids[["INGEST", "CHUNK", "BUILD"].indexOf(stage)];
      latest = { id, operation: stage as IndexingJobRead["operation"], file_id: fileId, user_id: owner, status: "running", recovery_required: false, total: 1, processed: 0, succeeded: 0, skipped: 0, failed: 0, started_at: null, completed_at: null, error: null, created_at: "", updated_at: "" };
      jobs.set(id, latest); file.status = "indexing";
      return json({ job_id: id, status: "queued" }, 202);
    }
    throw new Error("Unexpected API route");
  }));
});
afterEach(() => { vi.unstubAllGlobals(); setSessionOwner(null); });
it("reads metadata only before confirmation, then targets one frozen file sequentially and verifies indexed state", async () => {
  const c = await controller(); expect(c.getSnapshot().phase).toBe("review"); expect(writes()).toHaveLength(0);
  await c.confirm(); expect(c.getSnapshot().phase).toBe("active");
  complete(); await c.check(); expect(latest!.operation).toBe("CHUNK");
  complete(); await c.check(); expect(latest!.operation).toBe("BUILD");
  complete(); await c.check(); expect(c.getSnapshot().phase).toBe("ready");
  expect(writes().map(([url]) => url)).toEqual(["ingest", "chunk", "build"].map(s => `/api/v1/index/${s}?file_id=${fileId}`));
  expect(vi.mocked(fetch).mock.calls.some(([url]) => /content|\/sync/.test(String(url)))).toBe(false);
  expect(await c.finish()).toBe(true); expect(values.has(key)).toBe(false);
});
it.each(["INGEST", "CHUNK", "BUILD"])("refresh during %s observes exact receipts and requires explicit continuation", async stage => {
  const c = await controller(); await c.confirm();
  for (let n=0; n<3 && latest!.operation !== stage; n++) { complete(); await c.check(); }
  expect(latest!.operation, JSON.stringify(c.getSnapshot())).toBe(stage);
  c.dispose(); const count = writes().length;
  const next = new SingleFilePreparation(owner, null); await next.check(); expect(next.getSnapshot().job!.id).toBe(latest!.id);
  complete(); await next.check(); expect(writes()).toHaveLength(count);
  expect(next.getSnapshot().phase).toBe(stage === "BUILD" ? "ready" : "continue");
  if (stage !== "BUILD") { await next.confirm(); expect(writes()).toHaveLength(count+1); }
});
it.each(["navigation", "account switch", "same-owner revalidation"])("delayed accepted receipt survives %s without stale UI", async transition => {
  const response = deferred<Response>(), sent = deferred<void>(); intercept = (_p,i) => i.method === "POST" ? (sent.resolve(), response.promise) : undefined;
  const c = await controller(), listener = vi.fn(); c.subscribe(listener); const pending = c.confirm(); await sent.promise;
  if (transition === "navigation") c.dispose(); else { invalidateSessionRequests(); setSessionOwner(transition === "account switch" ? other : owner); }
  listener.mockClear(); response.resolve(json({ job_id: ids[0], status: "queued" },202)); await pending;
  expect(JSON.parse(values.get(key)!).receipts[0].jobId).toBe(ids[0]); expect(listener).not.toHaveBeenCalled(); expect(values.has(preparationKey(other))).toBe(false); expect(writes()).toHaveLength(1);
});
it.each([new TypeError("reset"), new DOMException("timeout", "TimeoutError"), new DOMException("abort", "AbortError")])("lost acknowledgement remains blocked: %s", async error => {
  intercept = (_p,i) => i.method === "POST" ? Promise.reject(error) : undefined;
  const c = await controller(); await c.confirm(); expect(c.getSnapshot().phase).toBe("unknown");
  const next = await controller(); await next.confirm(); await next.check(); expect(next.getSnapshot().phase).toBe("unknown"); expect(writes()).toHaveLength(1); expect(await next.finish()).toBe(false);
});
it.each([401,403,409])("documented %s rejection clears only its attempt and requires explicit retry", async status => {
  const detail = status === 401 ? "Your application session is invalid or expired." : status === 403 ? "Application session request could not be verified." : "An unresolved indexing job already exists for this account.";
  intercept = (_p,i) => i.method === "POST" ? Promise.resolve(json({ detail },status)) : undefined;
  const c = await controller(); await c.confirm(); expect(c.getSnapshot().phase).toBe(status === 401 ? "submitting" : "blocked"); expect(values.has(key)).toBe(false);
  await c.confirm(); expect(writes()).toHaveLength(1); intercept = () => undefined;
  const retry = status === 401 ? await controller() : c; await retry.check(); await retry.confirm(); expect(writes()).toHaveLength(2);
});
it.each(["session inspection", "missing CSRF"])("%s failure before POST leaves no uncertain marker", async failure => {
  intercept = p => p.endsWith("auth/session") ? failure === "missing CSRF" ? Promise.resolve(json({ user_id: owner })) : Promise.reject(new Error("offline")) : undefined;
  const c = await controller(); await c.confirm(); expect(writes()).toHaveLength(0); expect(values.has(key)).toBe(false); expect(c.getSnapshot().phase).toBe("blocked");
});
it.each([500,503,504])("generic HTTP %s is uncertain", async status => {
  intercept = (_p,i) => i.method === "POST" ? Promise.resolve(json({ detail: "Unavailable" },status)) : undefined;
  const c = await controller(); await c.confirm(); expect(c.getSnapshot().phase).toBe("unknown"); expect(values.has(key)).toBe(true);
});
it.each(["failed", "skipped", "indexed", "indexing"] as const)("does not submit fresh work for %s files", async status => {
  file.status = status; const c = await controller(); await c.confirm(); expect(c.getSnapshot().phase).toBe("ineligible"); expect(writes()).toHaveLength(0); expect(preparationEligibility(file)).not.toBeNull();
});
it("rejects unsupported and foreign-owner metadata", async () => {
  file.mime_type = "application/vnd.google-apps.spreadsheet"; let c = await controller(); await c.confirm(); expect(writes()).toHaveLength(0);
  file.user_id = other; c = await controller(); await c.confirm(); expect(c.getSnapshot().phase).toBe("unknown"); expect(writes()).toHaveLength(0);
});
it.each(["failed", "canceled", "skipped", "recovery", "invalid counters", "wrong target", "wrong operation", "not indexed"])("never advances after %s evidence", async problem => {
  const c = await controller(); await c.confirm(); if (problem === "not indexed") { complete(); await c.check(); complete(); await c.check(); } complete();
  if (problem === "failed" || problem === "canceled") latest!.status = problem;
  if (problem === "skipped") { latest!.skipped=1; latest!.succeeded=0; file.status="skipped"; }
  if (problem === "recovery") latest!.recovery_required=true;
  if (problem === "invalid counters") latest!.succeeded=0;
  if (problem === "wrong target") latest!.file_id=other;
  if (problem === "wrong operation") latest!.operation="SYNC";
  if (problem === "not indexed") file.status="indexing";
  const count=writes().length; await c.check(); await c.confirm(); expect(writes()).toHaveLength(count); expect(["failed","skipped","blocked","unknown"]).toContain(c.getSnapshot().phase);
});
it("active owner work and recovery exclude new preparation", async () => {
  await (await controller()).confirm(); values.clear(); file.status="discovered";
  let c=await controller(); await c.confirm(); expect(c.getSnapshot().phase).toBe("blocked"); expect(writes()).toHaveLength(1);
  latest!.status="failed"; latest!.recovery_required=true; c=await controller(); await c.confirm(); expect(c.getSnapshot().phase).toBe("blocked"); expect(writes()).toHaveLength(1);
});
it("duplicate clicks and overlapping controllers submit at most once", async () => {
  const a=await controller(), b=await controller(); await Promise.all([a.confirm(),a.confirm(),b.confirm()]); expect(writes()).toHaveLength(1);
});
it.each(["accepted", "rejected"])("late %s response never overwrites newer intent", async outcome => {
  const response=deferred<Response>(),sent=deferred<void>(); intercept=(_p,i)=>i.method==="POST"?(sent.resolve(),response.promise):undefined;
  const c=await controller(), pending=c.confirm(); await sent.promise; const newer=JSON.stringify({...JSON.parse(values.get(key)!),runId:other}); values.set(key,newer);
  response.resolve(outcome==="accepted"?json({job_id:ids[0],status:"queued"},202):json({detail:"An unresolved indexing job already exists for this account."},409)); await pending; expect(values.get(key)).toBe(newer);
});
it.each(["storage", "locks"])("%s failure prevents admission", async failure => {
  const c=await controller(); if(failure==="storage") window.localStorage.setItem=()=>{throw Error("denied");}; else Object.defineProperty(navigator,"locks",{configurable:true,value:undefined});
  await c.confirm(); expect(writes()).toHaveLength(0); expect(c.getSnapshot().phase).toBe("blocked");
});
it.each(["storage", "locks"])("202 receipt %s failure preserves unknown work", async failure=>{
  intercept=(_p,i)=>{if(i.method!=="POST")return; if(failure==="storage")window.localStorage.setItem=()=>{throw Error("denied");}; else Object.defineProperty(navigator,"locks",{configurable:true,value:{request:async()=>{throw Error("denied");}}});return Promise.resolve(json({job_id:ids[0],status:"queued"},202));};
  const c=await controller();await c.confirm();expect(c.getSnapshot().phase).toBe("unknown");expect(values.has(key)).toBe(true);await c.confirm();expect(writes()).toHaveLength(1);
});
it("401 invalidates even when receipt cleanup fails", async()=>{
  const invalid=vi.fn();window.addEventListener(SESSION_INVALID_EVENT,invalid);
  try{intercept=(_p,i)=>{if(i.method!=="POST")return;window.localStorage.removeItem=()=>{throw Error("denied");};return Promise.resolve(json({detail:"Your application session is invalid or expired."},401));};const c=await controller();await c.confirm();expect(invalid).toHaveBeenCalledOnce();expect(values.has(key)).toBe(true);}finally{window.removeEventListener(SESSION_INVALID_EVENT,invalid);}
});
it("unknown discovery marker excludes all stage submissions", async()=>{
  values.set(discovery,JSON.stringify({jobId:null}));const c=await controller();await c.confirm();expect(c.getSnapshot().phase).toBe("blocked");expect(writes()).toHaveLength(0);
});
it("intervening work or changed metadata blocks downstream submission", async()=>{
  const c=await controller();await c.confirm();complete();latest={...latest!,id:other};await c.check();expect(c.getSnapshot().phase).toBe("unknown");expect(writes()).toHaveLength(1);
  latest=jobs.get(ids[0])!;file.modified_at="changed";await c.check();expect(c.getSnapshot().phase).toBe("unknown");expect(writes()).toHaveLength(1);
});
it("missing targets and demo mode never submit", async()=>{
  await expect(submitFilePreparationStage("INGEST","",AbortSignal.timeout(100),async()=>{})).rejects.toMatchObject({outcome:"not_submitted"});
  mode.demo=true;const c=await controller();await c.confirm();await expect(submitFilePreparationStage("BUILD",fileId,AbortSignal.timeout(100),async()=>{})).rejects.toMatchObject({outcome:"not_submitted"});expect(writes()).toHaveLength(0);
});
it("a late terminal check cannot release a newer workflow", async()=>{
  const c=await controller();await c.confirm();complete();await c.check();complete();await c.check();complete();await c.check();
  const response=deferred<Response>(),sent=deferred<void>();intercept=(p)=>p==="/api/v1/files"?(sent.resolve(),response.promise):undefined;
  const pending=c.finish();await sent.promise;const newer=JSON.stringify({...JSON.parse(values.get(key)!),runId:other});values.set(key,newer);
  response.resolve(json({files:[file],total:1}));expect(await pending).toBe(false);expect(values.get(key)).toBe(newer);
});
it("proven chunk rejection preserves completed ingest and retries only chunk after explicit checking",async()=>{
  const c=await controller();await c.confirm();complete();intercept=(p,i)=>p.includes('/chunk?')&&i.method==='POST'?Promise.resolve(json({detail:'An unresolved indexing job already exists for this account.'},409)):undefined;
  await c.check();expect(c.getSnapshot().phase).toBe('blocked');expect(JSON.parse(values.get(key)!).receipts).toHaveLength(1);
  intercept=()=>undefined;await c.check();expect(c.getSnapshot().phase).toBe('continue');await c.confirm();expect(writes().map(([p])=>String(p).split('?')[0].split('/').at(-1))).toEqual(['ingest','chunk','chunk']);
});
it("different requested file after remount cannot replace the saved target",async()=>{
  const c=await controller();await c.confirm();c.dispose();const next=new SingleFilePreparation(owner,other);await next.check();expect(next.getSnapshot().file!.id).toBe(fileId);expect(writes()).toHaveLength(1);
});
it("running BUILD recovery protection is observed but never released or retried",async()=>{
  const c=await controller();await c.confirm();complete();await c.check();complete();await c.check();latest!.recovery_required=true;
  await c.check();expect(c.getSnapshot().phase).toBe('active');expect(await c.finish()).toBe(false);await c.confirm();expect(writes()).toHaveLength(3);
  complete({recovery_required:true});await c.check();expect(c.getSnapshot().phase).toBe('blocked');expect(await c.finish()).toBe(false);
});
it("pausing before leaving keeps the accepted stage but requires explicit continuation",async()=>{
  const c=await controller();await c.confirm();c.pause();complete();await c.check();expect(c.getSnapshot().phase).toBe('continue');expect(writes()).toHaveLength(1);
  await c.confirm();expect(writes()).toHaveLength(2);
});
it("a read timeout retains the exact receipt and does not resubmit or advance",async()=>{
  const c=await controller();await c.confirm();intercept=p=>p.includes('index/status?job_id=')?Promise.reject(new DOMException('timeout','TimeoutError')):undefined;
  await c.check();expect(c.getSnapshot().phase).toBe('unknown');expect(JSON.parse(values.get(key)!).receipts[0].jobId).toBe(ids[0]);expect(writes()).toHaveLength(1);
  intercept=()=>undefined;await c.check();expect(c.getSnapshot().phase).toBe('active');expect(writes()).toHaveLength(1);
});
