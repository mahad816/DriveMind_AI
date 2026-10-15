import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { SingleFilePreparationView } from "./single-file-preparation-view";
import { setSessionOwner } from "@/lib/api/session-events";
const fixture = vi.hoisted(() => ({ owner: "00000000-0000-0000-0000-000000000065", id: "00000000-0000-0000-0000-000000000101", demo: false, params: new URLSearchParams(), push: vi.fn() }));
vi.mock("@/lib/demo", () => ({ get DEMO_MODE() { return fixture.demo; } }));
vi.mock("@/components/providers/application-session-provider", () => ({ useApplicationSession: () => ({ userId: fixture.owner }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: fixture.push }), useSearchParams: () => fixture.params }));
let status: string, active: boolean;
const jobId="00000000-0000-0000-0000-000000000201";
const json=(body:unknown,code=200)=>new Response(JSON.stringify(body),{status:code,headers:{"Content-Type":"application/json"}});
beforeEach(()=>{
  fixture.demo=false;fixture.params=new URLSearchParams({file:fixture.id});fixture.push.mockClear();setSessionOwner(fixture.owner);status="discovered";active=false;
  const values=new Map<string,string>();Object.defineProperty(window,"localStorage",{configurable:true,value:{getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>values.set(k,v),removeItem:(k:string)=>values.delete(k)}});
  Object.defineProperty(navigator,"locks",{configurable:true,value:{request:async(_k:string,fn:()=>unknown)=>fn()}});
  vi.stubGlobal("fetch",vi.fn(async(path:string,init:RequestInit={})=>{
    if(path==="/api/v1/files")return json({files:[{id:fixture.id,user_id:fixture.owner,drive_file_id:"synthetic",name:"A long synthetic document with product and architecture decisions.txt",mime_type:"text/plain",status,modified_at:"2026-01-01"}],total:1});
    if(path==="/api/v1/auth/session")return json({user_id:fixture.owner,csrf_token:"synthetic"});
    if(path.startsWith("/api/v1/index/status"))return json({connected:true,job:active?{id:jobId,user_id:fixture.owner,file_id:fixture.id,operation:"INGEST",status:"running",recovery_required:false,total:1,processed:0,failed:0,skipped:0,succeeded:0}:null});
    expect(path).toBe(`/api/v1/index/ingest?file_id=${fixture.id}`);expect(init.method).toBe("POST");active=true;status="indexing";return json({job_id:jobId,status:"queued"},202);
  }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();setSessionOwner(null);});
it("reviews one named document and cancellation is navigation only, with no content requests",async()=>{
  render(<SingleFilePreparationView/>);expect(await screen.findByRole("button",{name:"Prepare this document"})).toBeEnabled();
  expect(screen.getByRole("heading",{name:/A long synthetic/})).toBeInTheDocument();expect(screen.getByText(/configured AI services/)).toBeInTheDocument();
  expect(screen.getByRole("link",{name:"Cancel"})).toHaveAttribute("href","/files");
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>init?.method!=="POST")).toBe(true);
});
it("keyboard confirmation submits only the selected file, announces actual job state and prevents repeat clicks",async()=>{
  render(<SingleFilePreparationView/>);const action=await screen.findByRole("button",{name:"Prepare this document"});action.focus();await userEvent.setup().keyboard("{Enter}");
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("Preparation stage in progress"));
  expect(screen.queryByRole("button",{name:"Prepare this document"})).toBeNull();expect(screen.getByText(/Leaving this page does not cancel/)).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.filter(([,init])=>init?.method==="POST").map(([path])=>path)).toEqual([`/api/v1/index/ingest?file_id=${fixture.id}`]);
});
it.each(["indexed","failed","skipped","indexing"])("%s metadata cannot be confirmed as a fresh preparation",async value=>{
  status=value;render(<SingleFilePreparationView/>);await screen.findByRole("heading",{name:/A long synthetic/});expect(screen.queryByRole("button",{name:"Prepare this document"})).toBeNull();
  expect(screen.queryByRole("link",{name:"Start chatting"})!==null).toBe(value==="indexed");expect(vi.mocked(fetch).mock.calls.every(([,init])=>init?.method!=="POST")).toBe(true);
});
it("does not mount normal preparation or call services in demo mode",()=>{fixture.demo=true;render(<SingleFilePreparationView/>);expect(fetch).not.toHaveBeenCalled();expect(screen.queryByRole("button")).toBeNull();});
it("unknown acceptance never presents the owner's latest job as this document's progress",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(path,init)=>{
    const response=await original(path,init);
    return init?.method==='POST'?json({detail:'Unknown response'},503):response;
  });
  render(<SingleFilePreparationView/>);await userEvent.setup().click(await screen.findByRole('button',{name:'Prepare this document'}));
  await waitFor(()=>expect(screen.getByRole('status')).toHaveTextContent('could not be confirmed'));
  expect(screen.getByRole('list',{name:'Preparation stages'})).toHaveTextContent('Reading document · Needs review');
  expect(screen.getByRole('list',{name:'Preparation stages'})).not.toHaveTextContent('In progress');
  expect(screen.queryByRole('button',{name:'Continue preparation'})).toBeNull();
});
