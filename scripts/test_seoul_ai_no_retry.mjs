// Fake administrator Auth/RPC only. No DB, credentials or external network.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {aiReview,aiReviewView,DatabaseAiReviewStore}=await import('../app/lib/review/ai-review.ts');
const {aiReviewRequest}=await import('../app/lib/review/ai-review-handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const fixture=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_program_db.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
const facts=fixture.fixtures[0].item.program_facts;
const job='10000000-0000-4000-8000-000000000001',sid='20000000-0000-4000-8000-000000000001',actor='30000000-0000-4000-8000-000000000001';
const raw={jobId:job,sourceItemId:sid,sourceName:'seoul_reservation',revision:'a'.repeat(64),version:'b'.repeat(64),status:'failed',canRecheck:true,canExclude:false,recheckPending:false,note:'',expiredCancellation:null,
 review:{id:sid,revision:'a'.repeat(64),version:'b'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:1,source:{name:'seoul_reservation',title:'합성 실패 작업',url:facts.official_url,body:'합성 원문'},facts,observedFacts:facts,result:{decision:'in_scope',disposition:'target',reasons:[]},status:'resolved',aiStatus:'failed',editableFields:[],history:[]},privateAttempt:'PRIVATE_SENTINEL'};
const held={...raw,status:'cancelled',canRecheck:false,recheckPending:true,version:'c'.repeat(64),review:{...raw.review,status:'open',aiStatus:'cancelled',editableFields:['description'],result:{...raw.review.result,reasons:['ai_recheck_requested']}}};
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const view=aiReview(raw,job);eq(aiReviewView(view,job),view);eq(JSON.stringify(view).includes('PRIVATE_SENTINEL'),false);
eq(aiReview({...raw,canRecheck:false},job).canRecheck,false);
for(const bad of [{...view,status:'completed'},{...view,status:'claimed'},{...view,recheckPending:true},{...view,canExclude:true},{...view,sourceName:'myseoul_program'}]){assert.throws(()=>aiReviewView(bad,job),e=>e.code==='unavailable');checks++;}
const command={action:'request_recheck',revision:raw.revision,version:raw.version,requestId:'40000000-0000-4000-8000-000000000001',note:''};
const url=`https://example.test/api/admin/ai-queue/${job}`;
const post=(body=command,origin='https://example.test')=>new Request(url,{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(body)});
let calls=[];const store=new DatabaseAiReviewStore({async rpc(name,args){calls.push({name,args});return {data:name==='admin_ai_queue_review_detail'?raw:held,error:null};}});
const deps={authorize:async()=>({userId:actor}),store:()=>store};
let response=await aiReviewRequest(new Request(url),job,deps);eq(response.status,200);eq((await response.json()).item.status,'failed');
calls=[];response=await aiReviewRequest(post(),job,deps);eq(response.status,200);eq((await response.json()).item.recheckPending,true);eq(calls.length,1);
eq(calls[0].name,'admin_ai_queue_request_recheck');eq(calls[0].args.p_actor,actor);eq(calls[0].args.p_version,raw.version);
for(const reason of ['signed_out','forbidden','auth_error']){calls=[];response=await aiReviewRequest(post(),job,{...deps,authorize:async()=>{throw new AdminAccessError(reason);}});eq(response.status,reason==='signed_out'?401:reason==='forbidden'?403:503);eq(calls.length,0);}
calls=[];response=await aiReviewRequest(post(command,'https://evil.test'),job,deps);eq(response.status,403);eq(calls.length,0);
let writes=0;const unknown=new DatabaseAiReviewStore({async rpc(){writes++;throw Error('PRIVATE_SENTINEL');}});
response=await aiReviewRequest(post(),job,{...deps,store:()=>unknown});eq(response.status,503);eq(writes,1);eq((await response.text()).includes('PRIVATE_SENTINEL'),false);
console.log(`No-retry failed Seoul recheck API: ${checks} checks passed. Fake Auth/RPC only.`);
