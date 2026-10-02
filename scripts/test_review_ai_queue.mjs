import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {DatabaseAiQueueStore,aiSnapshot,observeAi,aiStateText,aiFailureText}=await import('../app/lib/review/ai-queue.ts');
const {readAiQueue}=await import('../app/lib/review/ai-handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {visibleFactFields,fieldsForReason}=await import('../app/lib/review/facts-guidance.ts');
const {fixtureFacts}=await import('../app/lib/review/local-fixture.ts');
const id='00000000-0000-4000-8000-000000000001',sid='00000000-0000-4000-8000-000000000002',when='2026-10-02T00:00:00Z';
const row={jobId:id,sourceItemId:sid,revision:'a'.repeat(64),currentRevision:true,status:'queued',title:'가상 정책',sourceName:'youthcenter_policy',completedAt:null,retryCount:0,nextRetryAt:null,leaseState:'none',errorCode:null,resultState:null,secret:'MUST_NOT_ECHO'};
const snap=(items=[],observed=[])=>({checkedAt:when,items,observed,hasMore:false});
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
eq(aiStateText(row),'AI 작업 대기');eq(aiStateText({...row,retryCount:1}),'재시도 대기');eq(aiStateText({...row,status:'claimed',leaseState:'expired'}),'처리 상태 확인 필요');
eq(aiFailureText({...row,errorCode:'RAW_SECRET'}),'실패 이유를 확인할 수 없습니다.');
eq(JSON.stringify(aiSnapshot(snap([row]))).includes('MUST_NOT_ECHO'),false);
for(const bad of [snap([{...row,status:'completed',completedAt:when}]),snap([{...row,sourceItemId:'bad'}]),snap([{...row,nextRetryAt:'not-time'}]),snap([],Array(101).fill(row))]){
 assert.throws(()=>aiSnapshot(bad));checks++;
}
const state={watched:new Map(),announced:new Set()};
eq(observeAi(state,aiSnapshot(snap([row]))),'');
eq(observeAi(state,aiSnapshot(snap([]))),''); // Vanishing from a page is not completion.
const complete={...row,status:'completed',completedAt:when,resultState:'ready',errorCode:'ai_network'};
assert.match(observeAi(state,aiSnapshot(snap([],[complete]))),/AI 결과 후보 검토/);checks++;
eq(observeAi(state,aiSnapshot(snap([],[complete]))),'');
const second={...row,jobId:'00000000-0000-4000-8000-000000000003',sourceItemId:'00000000-0000-4000-8000-000000000004'};
const batch={watched:new Map([[id,row],[second.jobId,second]]),announced:new Set()};
assert.match(observeAi(batch,aiSnapshot(snap([],[complete,{...second,status:'completed',completedAt:when,resultState:'ready'}]))),/AI 작업 2건이 완료/);checks++;
eq(observeAi(batch,aiSnapshot(snap([],[complete,{...second,status:'completed',completedAt:when,resultState:'ready'}]))),'');
const bounded={watched:new Map(),announced:new Set()};
for(let page=0;page<5;page++)observeAi(bounded,aiSnapshot(snap(Array.from({length:25},(_,n)=>({...row,jobId:'00000000-0000-4000-8000-'+String(page*25+n+1).padStart(12,'0')})))));
eq(bounded.watched.size,100);
for(const resultState of ['missing','processed','input_changed','source_changed','unavailable']){
 const st={watched:new Map([[id,row]]),announced:new Set()};
 assert.ok(!observeAi(st,aiSnapshot(snap([],[{...complete,resultState,currentRevision:resultState!=='source_changed'}]))).includes('AI 결과 후보 검토'));checks++;
}
const st={watched:new Map([[id,row]]),announced:new Set()};
assert.match(observeAi(st,aiSnapshot(snap([],[{jobId:id,status:'missing'}]))),/달라졌습니다/);checks++;
let calls=0;const client={async rpc(name,args){calls++;eq(name,'admin_review_ai_queue');eq(args,{p_offset:0,p_limit:25,p_watch:[]});return {data:snap([row]),error:null};}};
const store=new DatabaseAiQueueStore(client),deps={authorize:async()=>({userId:sid}),store:()=>store};
for(const [denial,status] of [['signed_out',401],['forbidden',403],['auth_unavailable',503],['configuration_error',503]]){
 const response=await readAiQueue(new Request('https://example.test/api/admin/ai-queue'),{...deps,authorize:async()=>{throw new AdminAccessError(denial)}});
 eq(response.status,status);eq(calls,0);assert.match(response.headers.get('cache-control'),/private.*no-store/);checks++;
}
for(const query of ['offset=-1','offset=100001','watch=bad','extra=yes','offset=1&offset=2','watch='+Array(101).fill(id).join(',')]){
 const response=await readAiQueue(new Request('https://example.test/api/admin/ai-queue?'+query),deps);eq(response.status,422);eq(calls,0);
}
let response=await readAiQueue(new Request('https://example.test/api/admin/ai-queue'),deps);eq(response.status,200);assert.match(response.headers.get('cache-control'),/private.*no-store/);checks++;eq((await response.text()).includes('MUST_NOT_ECHO'),false);
response=await readAiQueue(new Request('https://example.test/api/admin/ai-queue'),{...deps,store:()=>{throw Error('TOKEN_SECRET')}});eq(response.status,503);eq((await response.text()).includes('TOKEN_SECRET'),false);
const f=fixtureFacts();eq(fieldsForReason('region_scope_unknown',f,['scope','evidence']),['scope','evidence']);
eq(fieldsForReason('unknown_code',f,['scope']),[]);eq(fieldsForReason('event_period_unknown',f,[]),[]);
eq(visibleFactFields({...f,productType:'living_guide',category:'living'}).includes('scope'),false);
eq(fieldsForReason('application_deadline_unknown',{...f,deadlineKind:'fixed'},['deadlineKind','deadlineOn']),['deadlineKind','deadlineOn']);
console.log('AI queue handler/DTO/observation and facts guidance checks:',checks,'No real auth/network/AI.');
