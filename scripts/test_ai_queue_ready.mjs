// Real handler/DTO, synthetic SQL projections, fake Auth/RPC. No real connections.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import net from 'node:net';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
net.Socket.prototype.connect=()=>{throw Error('network forbidden');};
globalThis.fetch=()=>{throw Error('fetch forbidden');};
const {DatabaseAiQueueStore,aiSnapshot,observeAi}=await import('../app/lib/review/ai-queue.ts');
const {readAiQueue}=await import('../app/lib/review/ai-handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
let input='';for await(const part of process.stdin)input+=part;
const fixture=JSON.parse(input),frozen=structuredClone(fixture);
let checks=0,calls=[];const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const client={async rpc(name,args){calls.push({name,args});eq(name,'admin_review_ai_queue');return {data:args.p_offset===25?fixture.page2:fixture.after,error:null};}};
const deps={authorize:async()=>({userId:'00000000-0000-4000-8000-000000000001'}),store:()=>new DatabaseAiQueueStore(client)};
const watched=fixture.after.observed.map(j=>j.jobId);
const request=offset=>new Request('https://example.test/api/admin/ai-queue?offset='+offset+'&watch='+watched.join(','));
for(const [code,status] of [['signed_out',401],['forbidden',403],['auth_unavailable',503]]){
 const r=await readAiQueue(request(0),{...deps,authorize:async()=>{throw new AdminAccessError(code);}});
 eq(r.status,status);eq(calls.length,0);assert.match(r.headers.get('cache-control'),/private.*no-store/);checks++;
}
const response=await readAiQueue(request(0),deps);eq(response.status,200);
const parsed=aiSnapshot(await response.json());
eq(parsed.items.some(j=>j.jobId===fixture.beforeBlocked),false);
eq(parsed.observed.find(j=>j.jobId===fixture.beforeBlocked).status,'queued');
eq(calls.length,1);eq(calls[0].args,{p_offset:0,p_limit:25,p_watch:watched});
const page=await readAiQueue(new Request('https://example.test/api/admin/ai-queue?offset=25'),{...deps,store:()=>new DatabaseAiQueueStore({async rpc(name,args){eq(name,'admin_review_ai_queue');eq(args.p_offset,25);return {data:{...fixture.page2,observed:[]},error:null};}})});
eq(page.status,200);eq((await page.json()).hasMore,false);
const old=fixture.after.observed[0];
const state={watched:new Map([[old.jobId,old]]),announced:new Set()};
eq(observeAi(state,parsed),''); // Disappearance from eligible list is never completion.
eq(aiSnapshot(fixture.held).held.length,1);
const error=await readAiQueue(request(0),{...deps,store:()=>new DatabaseAiQueueStore({async rpc(){return {data:null,error:{code:'XX000',message:'SECRET_NEVER_ECHO'}};}})});
eq(error.status,503);eq((await error.text()).includes('SECRET_NEVER_ECHO'),false);
const unknown=await readAiQueue(request(0),{...deps,store:()=>new DatabaseAiQueueStore({async rpc(){throw Error('unknown response');}})});
eq(unknown.status,503);eq(calls.length,1);eq(fixture,frozen);
console.log('AI-ready fake Auth/RPC/DTO checks:',checks,'AI/write/retry calls: 0');
