import { beforeEach, expect, it, vi } from "vitest";
import { invalidateSessionRequests, setSessionOwner, SESSION_TRANSITION_KEY } from "@/lib/api/session-events";
import { captureConversationScope } from "./scope";
import { createConversation, listConversations, getConversation, deleteConversation } from "./storage";
import { saveConversationMessages, getConversationMessages, updateConversationMessageById, buildChatRequestForConversation, type StoredChatMessage } from "./messages";
const A = "00000000-0000-0000-0000-000000000065", B = "00000000-0000-0000-0000-000000000066";
let data: Record<string, string>;
const turn: StoredChatMessage = { id: "turn", question: "A question", answer: "A answer", status: "done", citations: [{chunk_id:"chunk",drive_file_id:"provider",filename:"A file",snippet:"A snippet",score:1}], retrievalCount:1,error:null };
beforeEach(() => {
 data = {};
 vi.stubGlobal("window", {localStorage:{getItem:(k:string)=>data[k]??null,setItem:(k:string,v:string)=>{data[k]=v;},removeItem:(k:string)=>{delete data[k];}}});
 invalidateSessionRequests();setSessionOwner(A);
});
it("reloads A metadata, citations and history without exposing or deleting them under B",()=>{
 const c=createConversation("A title");saveConversationMessages(c.id,[turn]);const before={...data};
 invalidateSessionRequests();setSessionOwner(B);expect(listConversations()).toEqual([]);expect(getConversation(c.id)).toBeNull();expect(getConversationMessages(c.id)).toEqual([]);
 createConversation("B title");deleteConversation(c.id);
 for(const [key,value] of Object.entries(before)) expect(data[key]).toBe(value);
 invalidateSessionRequests();setSessionOwner(A);expect(listConversations()[0].title).toBe("A title");expect(getConversationMessages(c.id)).toEqual([turn]);
 expect(buildChatRequestForConversation(c.id,"follow-up").history).toEqual([{role:"user",text:"A question"},{role:"assistant",text:"A answer"}]);
});
it("never reads or modifies legacy unowned metadata or messages",()=>{
 data['drivemind:conversations']=JSON.stringify([{id:'legacy',title:'legacy private',createdAt:'x',updatedAt:'x'}]);data['drivemind:conversation-messages:legacy']=JSON.stringify([turn]);const before={...data};
 expect(listConversations()).toEqual([]);expect(getConversationMessages('legacy')).toEqual([]);expect(data).toEqual(before);
});
it("requires verification before any normal read or write",()=>{
 const c=createConversation("A title");setSessionOwner(null);expect(getConversation(c.id)).toBeNull();expect(()=>createConversation("unverified")).toThrow(/storage is unavailable/);
});
it("rejects delayed A writes even if a B conversation has the same opaque ID",()=>{
 const c=createConversation();saveConversationMessages(c.id,[turn]);const old=captureConversationScope();
 invalidateSessionRequests();setSessionOwner(B);saveConversationMessages(c.id,[{...turn,answer:"B answer"}]);const before={...data};
 expect(updateConversationMessageById(c.id,turn.id,t=>({...t,answer:"late A"}),old)).toBe(false);expect(data).toEqual(before);
});
it("blocks writes on a cross-tab notice even before its event handler runs",()=>{
 const c=createConversation();const old=captureConversationScope();data[SESSION_TRANSITION_KEY]='other-tab';
 expect(()=>saveConversationMessages(c.id,[turn],old)).toThrow(/storage is unavailable/);expect(getConversation(c.id,old)).toBeNull();
});
it.each(['invalid-json','invalid-shape'])('rejects %s without touching stored bytes',bad=>{
 const c=createConversation();const key=Object.keys(data)[0];data[key]=bad==='invalid-json'?'[':JSON.stringify([{id:c.id,title:123}]);const before={...data};
 expect(listConversations()).toEqual([]);expect(data).toEqual(before);
});
it("rejects malformed message/citation shapes before constructing supplied history",()=>{
 const c=createConversation();data[`drivemind:v1:normal:${A}:conversation-messages:${c.id}`]=JSON.stringify([{...turn,citations:[{filename:"bad"}]}]);
 expect(getConversationMessages(c.id)).toEqual([]);expect(buildChatRequestForConversation(c.id,"follow-up").history).toEqual([]);
});
it("handles unavailable/quota-failing storage with a safe error",()=>{
 window.localStorage.setItem=()=>{throw new Error('PRIVATE_CONTENT_QUOTA_ERROR')};expect(()=>createConversation()).toThrow(/storage is unavailable/);
 window.localStorage.getItem=()=>{throw new Error('PRIVATE_CONTENT_READ_ERROR')};expect(listConversations()).toEqual([]);
});
it('cannot flush pending data after same-owner logout and re-verification',()=>{
 const c=createConversation();const old=captureConversationScope();invalidateSessionRequests();setSessionOwner(A);
 expect(()=>saveConversationMessages(c.id,[turn],old)).toThrow(/storage is unavailable/);expect(getConversationMessages(c.id)).toEqual([]);
});
it('does not prune a newly created draft on a second hook mount in the same generation',async()=>{
 const {pruneEmptyDraftConversationsOnce}=await import('./storage');pruneEmptyDraftConversationsOnce();const c=createConversation();pruneEmptyDraftConversationsOnce();expect(getConversation(c.id)).not.toBeNull();
});
it('does not prune unreadable history as though it were an empty draft',async()=>{
 const c=createConversation();data[`drivemind:v1:normal:${A}:conversation-messages:${c.id}`]='[';
 const {pruneEmptyDraftConversationsOnce}=await import('./storage');pruneEmptyDraftConversationsOnce();expect(getConversation(c.id)).not.toBeNull();expect(data[`drivemind:v1:normal:${A}:conversation-messages:${c.id}`]).toBe('[');
});
it('oversized writes fail without replacing existing records',()=>{
 const c=createConversation();saveConversationMessages(c.id,[turn]);const before={...data};expect(()=>saveConversationMessages(c.id,[{...turn,answer:'x'.repeat(2_000_001)}])).toThrow(/storage is unavailable/);expect(data).toEqual(before);
});
