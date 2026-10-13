import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApplicationSessionProvider, useApplicationSession } from "./application-session-provider";
import { ToastProvider } from "@/components/ui/toast-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ChatInterface } from "@/components/chat/chat-interface";
import { createConversation } from "@/lib/conversations/storage";
import { getConversationMessages, saveConversationMessages } from "@/lib/conversations/messages";
import { setSessionOwner, SESSION_TRANSITION_KEY } from "@/lib/api/session-events";
const A="00000000-0000-0000-0000-000000000065",B="00000000-0000-0000-0000-000000000066";
const params=new URLSearchParams(),router={push:vi.fn(),replace:vi.fn()};
vi.mock("next/navigation",()=>({useSearchParams:()=>params,useRouter:()=>router}));
vi.mock("@/lib/hooks/use-connection-status",()=>({useConnectionStatus:()=>({data:{connected:true},error:null,refetch:vi.fn()})}));
vi.mock("@/lib/hooks/use-knowledge-status",()=>({useKnowledgeStatus:()=>({needsConnect:false,needsPrepare:false})}));
vi.mock("@/lib/hooks/use-chat-shortcuts",()=>({useChatShortcuts:vi.fn()}));
const json=(v:unknown,status=200)=>new Response(JSON.stringify(v),{status,headers:{"Content-Type":"application/json"}});
let data:Record<string,string>,owner:string;
let session:ReturnType<typeof useApplicationSession>;
function Controls(){session=useApplicationSession();return <p>Verified {session.userId}</p>}
function mount(id:string){return render(<ToastProvider><TooltipProvider><ApplicationSessionProvider><Controls/><ChatInterface conversationId={id}/></ApplicationSessionProvider></TooltipProvider></ToastProvider>)}
function seed(){setSessionOwner(A);const c=createConversation('A title');saveConversationMessages(c.id,[{id:'one',question:'A saved question',status:'done',answer:'A saved answer',citations:[],retrievalCount:1,error:null}]);return c.id}
beforeEach(()=>{
 data={};owner=A;vi.clearAllMocks();
 Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:(k:string)=>data[k]??null,setItem:(k:string,v:string)=>{data[k]=v},removeItem:(k:string)=>{delete data[k]}}});
 vi.stubGlobal('fetch',vi.fn((url:string)=>Promise.resolve(url.endsWith('/logout')?new Response(null,{status:204}):json({kind:'GOOGLE_ACCOUNT',user_id:owner,csrf_token:'synthetic'}))));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals()});
it('reloads A history; logout/B login and A URL remain isolated; A can reopen later',async()=>{
 const id=seed();data['drivemind:conversations']='[{"title":"LEGACY_SECRET"}]';mount(id);await screen.findByText('A saved answer');
 await act(()=>session.logout());expect(screen.queryByText('A saved answer')).toBeNull();owner=B;fireEvent(window,new Event('focus'));await screen.findByText(`Verified ${B}`);
 expect(screen.queryByText(/A title|A saved answer|LEGACY_SECRET/)).toBeNull();expect(router.replace).toHaveBeenCalledWith('/chat');
 owner=A;fireEvent(window,new Event('focus'));await screen.findByText('A saved answer');expect(data['drivemind:conversations']).toContain('LEGACY_SECRET');
 cleanup();mount(id);await screen.findByText('A saved answer');
});
it.each([200,401])('late A chat %s cannot persist or invalidate B',async status=>{
 const id=seed();let finish!:(r:Response)=>void;
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/chat')?new Promise<Response>(r=>{finish=r}):Promise.resolve(json({kind:'GOOGLE_ACCOUNT',user_id:owner,csrf_token:'synthetic'}))));
 mount(id);await screen.findByText('A saved answer');fireEvent.change(screen.getByRole('textbox',{name:'Message'}),{target:{value:'A new question'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));await waitFor(()=>expect(finish).toBeDefined());
 const before=Object.fromEntries(Object.entries(data).filter(([key])=>key.includes(':normal:')));owner=B;fireEvent(window,new Event('focus'));await screen.findByText(`Verified ${B}`);
 await act(async()=>{finish(json({user_id:A,query_id:'q',answer:'LATE_A_SECRET',citations:[],retrieval_count:1,message:'answer'},status));await Promise.resolve()});
 expect(screen.getByText(`Verified ${B}`)).toBeInTheDocument();expect(screen.queryByText(/A new question|LATE_A_SECRET/)).toBeNull();expect(Object.fromEntries(Object.entries(data).filter(([key])=>key.includes(':normal:')))).toEqual(before);
});
it('a cross-tab notice hides content immediately and only server inspection can choose B',async()=>{
 const id=seed();mount(id);await screen.findByText('A saved answer');let finish!:(r:Response)=>void;
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>{finish=r})));
 data[SESSION_TRANSITION_KEY]='synthetic-other-tab';fireEvent(window,new StorageEvent('storage',{key:SESSION_TRANSITION_KEY,newValue:'synthetic-other-tab'}));
 expect(screen.queryByText('A saved answer')).toBeNull();await waitFor(()=>expect(finish).toBeDefined());await act(async()=>finish(json({kind:'GOOGLE_ACCOUNT',user_id:B,csrf_token:'synthetic'})));
 await screen.findByText(`Verified ${B}`);expect(screen.queryByText(/A saved answer|A title/)).toBeNull();expect(getConversationMessages(id)).toEqual([]);
});
it('quota failure reports a safe error and submits no chat request',async()=>{
 const id=seed();const fetch=vi.mocked(globalThis.fetch);mount(id);await screen.findByText('A saved answer');window.localStorage.setItem=()=>{throw new Error('SECRET_QUOTA_ERROR')};
 fireEvent.change(screen.getByRole('textbox',{name:'Message'}),{target:{value:'new'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));
 expect(await screen.findByText(/Conversation storage is unavailable/)).toBeInTheDocument();expect(fetch.mock.calls.some(([url])=>String(url).endsWith('/chat'))).toBe(false);expect(screen.queryByText('SECRET_QUOTA_ERROR')).toBeNull();
});
it('actual answered requests persist citations and owner-specific history through reload',async()=>{
 const id=seed();const citation={chunk_id:'owned-chunk',drive_file_id:'owned-provider',filename:'A source',snippet:'A snippet',score:1};
 const fetch=vi.fn((url:string, _options?: RequestInit)=>Promise.resolve(url.endsWith('/chat') && _options?.method === 'POST'?json({user_id:A,query_id:'q',answer:'A fresh answer',citations:[citation],retrieval_count:1,message:'answer'}):json({kind:'GOOGLE_ACCOUNT',user_id:A,csrf_token:'synthetic'})));
 vi.stubGlobal('fetch',fetch);mount(id);await screen.findByText('A saved answer');fireEvent.change(screen.getByRole('textbox',{name:'Message'}),{target:{value:'follow up'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByText('A fresh answer');
 const request=JSON.parse(String(fetch.mock.calls.find(([url])=>url.endsWith('/chat'))?.[1]?.body));
 expect(request.conversation_id).toBe(id);expect(request.history).toEqual([{role:'user',text:'A saved question'},{role:'assistant',text:'A saved answer'}]);expect(getConversationMessages(id)[1].citations).toEqual([citation]);
 cleanup();mount(id);await screen.findByText('A fresh answer');expect(getConversationMessages(id)[1].citations).toEqual([citation]);
});
it('a forged cross-tab identity hint cannot replace the server-verified owner',async()=>{
 const id=seed();mount(id);await screen.findByText('A saved answer');data[SESSION_TRANSITION_KEY]='user_id=B';
 fireEvent(window,new StorageEvent('storage',{key:SESSION_TRANSITION_KEY,newValue:'user_id=B'}));await screen.findByText(`Verified ${A}`);await screen.findByText('A saved answer');expect(getConversationMessages(id)[0].answer).toBe('A saved answer');
});
it('expiry during an actual chat submission removes mounted history and leaves no false answer',async()=>{
 const id=seed();vi.stubGlobal('fetch',vi.fn((url:string)=>Promise.resolve(url.endsWith('/chat')?json({detail:'Expired'},401):json({kind:'GOOGLE_ACCOUNT',user_id:A,csrf_token:'synthetic'}))));
 mount(id);await screen.findByText('A saved answer');fireEvent.change(screen.getByRole('textbox',{name:'Message'}),{target:{value:'pending question'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByRole('button',{name:'Sign in with Google'});expect(screen.queryByText(/A saved answer|pending question/)).toBeNull();expect(getConversationMessages(id)).toEqual([]);
});
it('fresh session inspection prevents supplying A history under an unnoticed B cookie',async()=>{
 const id=seed();const fetch=vi.mocked(globalThis.fetch);mount(id);await screen.findByText('A saved answer');owner=B;
 fireEvent.change(screen.getByRole('textbox',{name:'Message'}),{target:{value:'private follow-up'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));
 await screen.findByRole('button',{name:'Sign in with Google'});expect(fetch.mock.calls.some(([url])=>String(url).endsWith('/chat'))).toBe(false);expect(screen.queryByText('A saved answer')).toBeNull();
});
it('logout sends a final cross-tab invalidation after actual revocation completes',async()=>{
 const notices:string[]=[];
 class Channel { onmessage=null; postMessage(value:string){notices.push(value)} close(){} }
 vi.stubGlobal('BroadcastChannel',Channel);const id=seed();let finish!:(r:Response)=>void;
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/logout')?new Promise<Response>(r=>{finish=r}):Promise.resolve(json({kind:'GOOGLE_ACCOUNT',user_id:A,csrf_token:'synthetic'}))));
 mount(id);await screen.findByText('A saved answer');const before=notices.length;
 let done!:Promise<void>;act(()=>{done=session.logout()});await waitFor(()=>expect(finish).toBeDefined());expect(notices).toHaveLength(before+1);
 await act(async()=>{finish(new Response(null,{status:204}));await done});expect(notices).toHaveLength(before+2);expect(new Set(notices).size).toBe(notices.length);
});
it('received expiry notices cannot create a cross-tab invalidation feedback loop',async()=>{
 const notices:string[]=[];const channels:Channel[]=[];
 class Channel { onmessage:((event:MessageEvent<string>)=>void)|null=null; constructor(){channels.push(this)} postMessage(value:string){notices.push(value)} close(){} }
 vi.stubGlobal('BroadcastChannel',Channel);const id=seed();mount(id);await screen.findByText('A saved answer');const before=notices.length;
 vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve(json({detail:'Expired'},401))));
 await act(async()=>{channels[0].onmessage?.(new MessageEvent('message',{data:'external-notice'}));await Promise.resolve()});await screen.findByRole('button',{name:'Sign in with Google'});expect(notices).toHaveLength(before);
});
it('quota failure after a provider response stops loading and reports unsaved changes',async()=>{
 const id=seed();let finish!:(r:Response)=>void;
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/chat')?new Promise<Response>(r=>{finish=r}):Promise.resolve(json({kind:'GOOGLE_ACCOUNT',user_id:A,csrf_token:'synthetic'}))));
 mount(id);await screen.findByText('A saved answer');fireEvent.change(screen.getByRole('textbox',{name:'Message'}),{target:{value:'new'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));await waitFor(()=>expect(finish).toBeDefined());
 window.localStorage.setItem=()=>{throw new Error('SECRET_QUOTA_ERROR')};await act(async()=>finish(json({user_id:A,answer:'unsaved',citations:[],retrieval_count:0,query_id:'q',message:'answer'})));
 fireEvent.change(screen.getByRole('textbox',{name:'Message'}),{target:{value:'next'}});await waitFor(()=>expect(screen.getByRole('button',{name:'Send message'})).toBeEnabled());expect(screen.getAllByText(/These changes could not be saved/).length).toBeGreaterThan(0);expect(screen.queryByText('SECRET_QUOTA_ERROR')).toBeNull();
});
