// Synthetic source fixtures, fake Auth/RPC only. No database or provider.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {aiReview,aiReviewView,aiRecheckCommand,DatabaseAiReviewStore}=await import('../app/lib/review/ai-review.ts');
const {aiReviewRequest}=await import('../app/lib/review/ai-review-handlers.ts');
const {LocalAiReviewStore}=await import('../app/lib/review/ai-review-fixture.ts');
const {aiSnapshot}=await import('../app/lib/review/ai-queue.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {ReviewFailure}=await import('../app/lib/review/contracts.ts');
const {fixtureFacts}=await import('../app/lib/review/local-fixture.ts');
const {emptyContentFilters,contentFilterSchema}=await import('../app/lib/contentFilters.ts');
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};const ok=x=>{assert.ok(x);checks++;};
const fixtures=name=>JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8',name,'--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
const id='10000000-0000-4000-8000-000000000001',sid='20000000-0000-4000-8000-000000000001',actor='30000000-0000-4000-8000-000000000001',requestId='40000000-0000-4000-8000-000000000001';
const p=fixtures('test_program_db.py').fixtures[0].item.program_facts;
let raw={jobId:id,sourceItemId:sid,sourceName:'seoul_reservation',revision:'a'.repeat(64),version:'b'.repeat(64),status:'queued',canRecheck:true,recheckPending:false,note:'',review:{id:sid,revision:'a'.repeat(64),version:'b'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:1,source:{name:'seoul_reservation',title:'합성',url:p.official_url,body:'합성 원문\n보호자 동반 필요'},facts:p,observedFacts:p,result:{decision:'in_scope',disposition:'target',reasons:[]},status:'resolved',aiStatus:'queued',editableFields:[],history:[],secret:'DO_NOT_ECHO'}};
let view=aiReview(raw,id);ok(view.values.some(r=>r.label==='신청 시작'));eq(view.source.body,'합성 원문\n보호자 동반 필요');ok(!JSON.stringify(view).includes('DO_NOT_ECHO'));
eq(aiReviewView(view,id),view);
for(const bad of [null,[],{...view,sourceName:'fake'},{...view,status:'claimed',canRecheck:true},{...view,recheckPending:true},{...view,values:Array(61).fill({label:'x',value:'x'})}]){assert.throws(()=>aiReviewView(bad,id));checks++;}
for(const bad of [null,[],{}, {action:'request_recheck',revision:raw.revision,version:raw.version,requestId,note:' ',actor}]){assert.throws(()=>aiRecheckCommand(bad),e=>e.code==='invalid_input');checks++;}
const my=fixtures('test_myseoul_db.py').fixtures.find(v=>v.name==='two_conflicts');
const myRaw={...raw,sourceName:'myseoul_program',revision:my.item.myseoul_facts.source_revision,review:{...raw.review,revision:my.item.myseoul_facts.source_revision,schema:'myseoul-program-facts-v1-local',profile:'myseoul-program-v1-local',source:{name:'myseoul_program',title:'합성 마이서울',url:my.item.myseoul_facts.official_url,body:my.item.myseoul_facts.description},facts:my.item.myseoul_facts,observedFacts:my.item.myseoul_facts,result:my.expected}};
eq(aiReview(myRaw,id).sourceName,'myseoul_program');ok(aiReview(myRaw,id).values.length>10);
const generic={...raw,sourceName:'youthcenter_policy',review:{kind:'facts',id:sid,revision:raw.revision,version:raw.version,status:'resolved',source:{name:'youthcenter_policy',title:'합성 정책',url:'https://example.test/',body:'합성 정책 원문'},facts:fixtureFacts(),reasons:[],editableFields:[],excludeAllowed:false,aiStatus:'queued',history:[]}};
eq(aiReview(generic,id).sourceName,'youthcenter_policy');ok(aiReview(generic,id).values.some(v=>v.value==='정책'));
const filters=emptyContentFilters('program');filters.delivery={status:'known',value:'online'};filters.location={status:'not_applicable',value:null};
const filtered=aiReview({...raw,review:{...raw.review,filterInfo:{schema:contentFilterSchema,revision:raw.revision,filterVersion:1,data:filters,missing:['topic','audience','application'],origins:{delivery:'operator',location:'operator'}}}},id);
ok(filtered.values.some(v=>v.label==='공개 필터 · 진행 방식'&&v.value==='온라인'));
ok(filtered.values.some(v=>v.value==='저장된 값 없음'));ok(filtered.values.some(v=>v.value==='해당 없음'));
const classified={id:sid,revision:raw.revision,version:'e'.repeat(64),classificationVersion:1,active:true,category:'program',facts:{...fixtureFacts(),category:'program',productType:'event_program',delivery:'online'},filters,note:'합성 분류 확인',editable:true,ready:true,reasons:[],sourceReasons:[]};
const classifiedView=aiReview({...raw,classification:classified},id);
ok(classifiedView.values.some(v=>v.label==='현재 분류 확인값 · 공개 카테고리'&&v.value==='프로그램'));
ok(classifiedView.values.some(v=>v.label.startsWith('수집원 확인값 ·')));
ok(classifiedView.values.some(v=>v.label.startsWith('현재 분류 필터 ·')&&v.value==='온라인'));
assert.throws(()=>aiReview({...raw,classification:{...classified,revision:'f'.repeat(64)}},id));checks++;

// Model the transaction boundary, receipts and fresh-gate result in a fake RPC.
// This does not prove actual SQL lock/trigger behavior.
let calls=[],claimed=false,candidate=false,unresolved=false,receipt=new Map(),events=[];
const baseline=JSON.stringify(raw.review);
const store=new DatabaseAiReviewStore({async rpc(name,args){
 calls.push({name,args});
 if(name==='admin_ai_queue_review_detail')return {data:structuredClone(raw),error:null};
 const action=name==='admin_ai_queue_request_recheck'?'request_recheck':'complete_recheck';
 const prior=receipt.get(args.p_request_id),binding=JSON.stringify({name,args});
 if(prior)return prior.binding===binding?{data:prior.data,error:null}:{data:null,error:{code:'PT409'}};
 if(claimed||candidate||args.p_revision!==raw.revision||args.p_version!==raw.version||action==='request_recheck'&&!raw.canRecheck||action==='complete_recheck'&&!raw.recheckPending)return {data:null,error:{code:'PT409'}};
 raw={...raw,version:action==='request_recheck'?'c'.repeat(64):'d'.repeat(64),status:action==='request_recheck'||unresolved?'cancelled':'queued',canRecheck:action==='complete_recheck'&&!unresolved,recheckPending:action==='request_recheck',note:args.p_note};
 events.push(action);receipt.set(args.p_request_id,{binding,data:structuredClone(raw)});return {data:raw,error:null};
}});
const url=`https://example.test/api/admin/ai-queue/${id}`,deps={authorize:async()=>({userId:actor}),store:()=>store};
const c={action:'request_recheck',revision:raw.revision,version:raw.version,requestId,note:'대상 조건을 원문과 다시 대조'};
const post=(body,origin='https://example.test')=>new Request(url,{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(body)});
for(const [denial,status] of [['signed_out',401],['forbidden',403],['auth_unavailable',503]]){
 const r=await aiReviewRequest(post(c),id,{...deps,authorize:async()=>{throw new AdminAccessError(denial)}});eq(r.status,status);eq(calls.length,0);ok(r.headers.get('cache-control').includes('no-store'));
}
eq((await aiReviewRequest(post(c,'https://evil.test'),id,deps)).status,403);eq(calls.length,0);
for(const bad of [{...c,actor},{...c,extra:true},{...c,requestId:'bad'},{...c,note:'x'.repeat(9000)},null])eq((await aiReviewRequest(post(bad),id,deps)).status,422);
eq(calls.length,0);
eq((await aiReviewRequest(new Request(url+'?extra=1'),id,deps)).status,422);
let r=await aiReviewRequest(new Request(url),id,deps);eq(r.status,200);ok(!(await r.text()).includes('DO_NOT_ECHO'));
for(const scenario of ['claim','candidate','version','revision']){
 claimed=scenario==='claim';candidate=scenario==='candidate';
 r=await aiReviewRequest(post({...c,...(scenario==='version'?{version:'f'.repeat(64)}:scenario==='revision'?{revision:'f'.repeat(64)}:{})}),id,deps);eq(r.status,409);eq(events.length,0);eq(JSON.stringify(raw.review),baseline);
}
claimed=false;candidate=false;
r=await aiReviewRequest(post(c),id,deps);eq(r.status,200);view=(await r.json()).item;eq(view.recheckPending,true);eq(view.status,'cancelled');eq(calls.at(-1).args.p_actor,actor);eq(JSON.stringify(raw.review),baseline);eq(events,['request_recheck']);
eq((await aiReviewRequest(post(c),id,deps)).status,200);eq(events.length,1); // bound receipt replay
eq((await aiReviewRequest(post({...c,note:'다른 요청'}),id,deps)).status,409);
eq((await aiReviewRequest(post({...c,requestId:'40000000-0000-4000-8000-000000000002'}),id,deps)).status,409);
unresolved=true;
const complete={...c,action:'complete_recheck',version:view.version,requestId:'40000000-0000-4000-8000-000000000003',note:'원문·최신 확인값 재검토 완료'};
r=await aiReviewRequest(post(complete),id,deps);eq(r.status,200);view=(await r.json()).item;eq(view.recheckPending,false);eq(view.status,'cancelled');eq(view.canRecheck,false);eq(JSON.stringify(raw.review),baseline);
// Release can re-register a ready queue, but never invokes a worker/provider.
unresolved=false;raw={...raw,status:'queued',canRecheck:true,version:'e'.repeat(64)};
r=await aiReviewRequest(post({...c,version:raw.version,requestId:'40000000-0000-4000-8000-000000000005'}),id,deps);eq(r.status,200);view=(await r.json()).item;
r=await aiReviewRequest(post({...complete,version:view.version,requestId:'40000000-0000-4000-8000-000000000006'}),id,deps);eq(r.status,200);view=(await r.json()).item;eq(view.status,'queued');eq(view.recheckPending,false);eq(JSON.stringify(raw.review),baseline);
const failing=new DatabaseAiReviewStore({async rpc(){throw Error('TOKEN_SECRET');}});
let before=calls.length;r=await aiReviewRequest(post(c),id,{...deps,store:()=>failing});eq(r.status,503);ok(!(await r.text()).includes('TOKEN_SECRET'));eq(calls.length,before);
const absent=new DatabaseAiReviewStore({async rpc(){return {data:null,error:{code:'PGRST202',message:'missing RPC'}};}});
eq((await aiReviewRequest(new Request(url),id,{...deps,store:()=>absent})).status,503);
const fixture=new LocalAiReviewStore(),first=await fixture.get(id),saved=JSON.stringify(first.values);
await fixture.execute(id,{...c,version:first.version},actor);
const snap=aiSnapshot(await fixture.read(0,[id]));eq(snap.items.length,2);eq(snap.held.length,1);eq(snap.held[0].jobId,id);eq((await fixture.get(id)).values,JSON.parse(saved));
assert.throws(()=>aiSnapshot({...snap,held:[snap.items[0]]}));checks++;
assert.throws(()=>aiSnapshot({...snap,held:Array(26).fill(snap.held[0])}));checks++;
const h=await fixture.get(id);await fixture.execute(id,{...complete,version:h.version},actor);eq((await fixture.read()).held.length,0);eq((await fixture.get(id)).status,'cancelled');
await assert.rejects(()=>fixture.execute('10000000-0000-4000-8000-000000000003',c,actor),e=>e instanceof ReviewFailure&&e.code==='conflict');checks++;
console.log(`AI queue detail/recheck: ${checks} checks passed. Fake Auth/RPC; DB/network/provider calls 0. SQL execution not tested.`);
