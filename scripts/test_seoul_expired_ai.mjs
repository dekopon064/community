// Fake Auth/RPC and synthetic data only; no DB, keys or network.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {aiReview,aiReviewView,aiRecheckCommand,DatabaseAiReviewStore}=await import('../app/lib/review/ai-review.ts');
const {aiReviewRequest}=await import('../app/lib/review/ai-review-handlers.ts');
const {LocalAiReviewStore}=await import('../app/lib/review/ai-review-fixture.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const fixture=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_program_db.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
const job='10000000-0000-4000-8000-000000000001',sid='20000000-0000-4000-8000-000000000001',actor='30000000-0000-4000-8000-000000000001';
const facts=fixture.fixtures[0].item.program_facts;
const raw={jobId:job,sourceItemId:sid,sourceName:'seoul_reservation',revision:'a'.repeat(64),version:'b'.repeat(64),status:'claimed',canRecheck:false,canExclude:false,recheckPending:false,note:'',expiredCancellation:{attempt:'c'.repeat(64)},
 review:{id:sid,revision:'a'.repeat(64),version:'b'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:1,source:{name:'seoul_reservation',title:'합성 해설',url:facts.official_url,body:'합성 원문'},facts,observedFacts:facts,result:{decision:'in_scope',disposition:'target',reasons:[]},status:'resolved',aiStatus:'claimed',editableFields:[],history:[]},
 workerId:'PRIVATE_CLAIM_ID',secret:'PRIVATE_CREDENTIAL'};
const held={...raw,status:'cancelled',version:'d'.repeat(64),expiredCancellation:null,recheckPending:true,
 review:{...raw.review,version:'d'.repeat(64),status:'open',aiStatus:'cancelled',editableFields:['description'],result:{...raw.review.result,reasons:['ai_recheck_requested']}}};
const command={action:'cancel_expired',revision:raw.revision,version:raw.version,requestId:'40000000-0000-4000-8000-000000000001',attempt:raw.expiredCancellation.attempt,note:''};
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};const ok=v=>{assert.ok(v);checks++;};
const view=aiReview(raw,job);eq(aiReviewView(view,job),view);eq(view.expiredCancellation,raw.expiredCancellation);
ok(!JSON.stringify(view).includes('PRIVATE_'));eq(aiRecheckCommand({...command,note:'   '}).note,'');
for(const bad of [{...command,attempt:'bad'},{...command,attempt:[command.attempt]},{...command,actor},{...command,workerId:'forged'},{...command,note:'x'.repeat(1001)},{...command,claimedAt:'2020-01-01'},{...command,revision:'bad'}]){
 assert.throws(()=>aiRecheckCommand(bad),e=>e.code==='invalid_input');checks++;
}
for(const bad of [{...view,status:'queued'},{...view,sourceName:'myseoul_program'},
 {...view,expiredCancellation:{attempt:'bad'}},{...view,expiredCancellation:{attempt:command.attempt,workerId:'PRIVATE'}},
 {...view,recheckPending:true},{...view,canRecheck:true}]){
 assert.throws(()=>aiReviewView(bad,job),e=>e.code==='unavailable');checks++;
}
eq(aiReview({...raw,expiredCancellation:undefined},job).expiredCancellation,undefined); // rolling server deployment compatibility
let calls=[];const store=new DatabaseAiReviewStore({async rpc(name,args){calls.push({name,args});return {data:name==='admin_ai_queue_review_detail'?raw:held,error:null};}});
const deps={authorize:async()=>({userId:actor}),store:()=>store};
const url=`https://example.test/api/admin/ai-queue/${job}`;
const post=(body,origin='https://example.test')=>new Request(url,{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(body)});
let response=await aiReviewRequest(new Request(url),job,deps);eq(response.status,200);ok(response.headers.get('cache-control').includes('no-store'));eq((await response.json()).item.expiredCancellation,raw.expiredCancellation);
calls=[];const before=JSON.stringify(raw.review);
response=await aiReviewRequest(post(command),job,deps);eq(response.status,200);
const result=(await response.json()).item;eq(result.status,'cancelled');eq(result.recheckPending,true);eq(result.expiredCancellation,undefined);
eq(calls.length,1);eq(calls[0],{name:'admin_seoul_ai_cancel_expired',args:{p_job_id:job,p_revision:command.revision,p_version:command.version,p_request_id:command.requestId,p_note:'',p_attempt:command.attempt,p_actor:actor}});
eq(JSON.stringify(raw.review),before);ok(response.headers.get('cache-control').includes('no-store'));
for(const reason of ['signed_out','forbidden','auth_error']){
 calls=[];const denied={...deps,authorize:async()=>{throw new AdminAccessError(reason);}};
 response=await aiReviewRequest(post(command),job,denied);eq(response.status,reason==='signed_out'?401:reason==='forbidden'?403:503);eq(calls.length,0);
}
for(const request of [post(command,'https://evil.test'),post({...command,actor}),post({...command,attempt:'invalid'})]){
 calls=[];response=await aiReviewRequest(request,job,deps);ok([403,422].includes(response.status));eq(calls.length,0);
}
for(const code of ['PT409','PT422','PT404']){
 let n=0;const rejection=new DatabaseAiReviewStore({async rpc(){n++;return {data:null,error:{code,message:'PRIVATE_CREDENTIAL'}};}});
 response=await aiReviewRequest(post(command),job,{...deps,store:()=>rejection});eq(response.status,code==='PT409'?409:code==='PT422'?422:404);eq(n,1);ok(!(await response.text()).includes('PRIVATE_'));
}
let attempts=0;const ambiguous=new DatabaseAiReviewStore({async rpc(){attempts++;throw Error('PRIVATE_CREDENTIAL');}});
response=await aiReviewRequest(post(command),job,{...deps,store:()=>ambiguous});eq(response.status,503);eq(attempts,1);ok(!(await response.text()).includes('PRIVATE_'));
for(const invalid of [{...held,status:'queued',recheckPending:false},{...held,recheckPending:false},raw]){
 let n=0;const malformed=new DatabaseAiReviewStore({async rpc(){n++;return {data:invalid,error:null};}});
 response=await aiReviewRequest(post(command),job,{...deps,store:()=>malformed});eq(response.status,503);eq(n,1);
}
await assert.rejects(()=>new LocalAiReviewStore().execute(job,command,actor),e=>e.code==='conflict');checks++;
console.log(`Expired Seoul AI API: ${checks} checks passed. Fake Auth/RPC; real DB/network/AI 0.`);
