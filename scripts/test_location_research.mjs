// Real panel -> authenticated handler -> existing filter store, synthetic only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
http.request=https.request=net.connect=net.createConnection=()=>{throw Error('external network forbidden');};
globalThis.fetch=async()=>{throw Error('external network forbidden');};
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const root=fileURLToPath(new URL('../',import.meta.url)),cache=new Map();
let states=[],refs=[],cursor=0,refCursor=0;
const fakeReact={...React,useState(initial){const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return [states[i],v=>{states[i]=typeof v==='function'?v(states[i]):v;}];},useRef(initial){return refs[refCursor++]??={current:initial};},useEffect(){}};
function load(name){const file=path.resolve(root,name);if(cache.has(file))return cache.get(file);const exports={};cache.set(file,exports);
 const code=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('require','exports',code)(s=>{if(s==='react')return fakeReact;
  if(s.startsWith('@/')||s.startsWith('.')){const p=s.startsWith('@/')?path.join(root,s.slice(2)):path.resolve(path.dirname(file),s);for(const x of ['.ts','.tsx',''])if(fs.existsSync(p+x))return load(path.relative(root,p+x));}return require(s);},exports);return exports;}
const core=load('app/lib/review/location-research.ts'),worker=load('app/lib/review/location-research-worker.ts');
const {locationResearchRequest}=load('app/lib/review/location-research-handler.ts');
const {ContentFilterStore}=load('app/lib/review/content-filter-store.ts');
const {ProgramReviewStore}=load('app/lib/review/program-store.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const {ReviewFailure}=load('app/lib/review/contracts.ts');
const {default:Panel}=load('app/components/admin/LocationResearchPanel.tsx');
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=v=>{assert.ok(v);checks++;};
const seed=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','-c','import json;from test_seoul_review_connections import ui_detail;print(json.dumps(ui_detail(),ensure_ascii=False))'],{cwd:path.join(root,'scripts'),encoding:'utf8'}));
const actor='00000000-0000-4000-8000-000000000001',batchId='00000000-0000-4000-8000-000000000002';
const ids=[1,2,3].map(x=>`30000000-0000-4000-8000-00000000000${x}`);
let rows,filterRows,calls,readCalls,authError,failAt,beforeSave,saved,requests;
function reset(){
 rows=new Map(ids.map((id,i)=>{const d=structuredClone(seed);d.id=id;d.source.title=`합성 지역 확인 ${i+1}`;d.facts.description='만나는 장소 : 합성물빛공원 교육장 앞\n활동 장소 : 합성산\n안전 안내와 참가 조건을 지켜 주세요.';d.filterInfo.data.location={status:'unknown',value:null};return [id,d];}));
 filterRows=new Map([...rows].map(([id,d])=>[id,{...structuredClone(d.filterInfo),id,editable:true,version:d.version}]));
 calls=[];readCalls=[];authError=null;failAt=null;beforeSave=null;saved=0;states=[];refs=[];requests=[];
}
function rpc(){return {async rpc(name,args){
 if(name==='admin_program_detail'){readCalls.push(args.p_id);return {data:structuredClone(rows.get(args.p_id)),error:null};}
 if(name==='admin_content_filter_detail')return {data:structuredClone(filterRows.get(args.p_id)),error:null};
 eq(name,'admin_content_filter_save');eq(args.p_actor,actor);eq(Object.keys(args.p_patch),['location']);
 calls.push(structuredClone(args));
 if(beforeSave)beforeSave(args);
 if(failAt===args.p_id)throw Error('transport unknown');
 const f=filterRows.get(args.p_id),d=rows.get(args.p_id);
 if(args.p_revision!==f.revision||args.p_version!==d.version||args.p_filter_version!==f.filterVersion)return {data:null,error:{code:'PT409'}};
 const next={...f,version:'f'.repeat(64),filterVersion:f.filterVersion+1,data:{...f.data,...args.p_patch},origins:{...f.origins,location:'operator'},missing:f.missing.filter(k=>k!=='location')};
 filterRows.set(args.p_id,next);d.version=next.version;d.filterInfo=next;
 d.history.push({action:'save_filters',actor,at:'2026-01-01T00:00:00Z',note:'',fields:['location']});
 return {data:structuredClone(next),error:null};
 }};}
const deps=()=>({authorize:async()=>{if(authError)throw new AdminAccessError(authError);return {userId:actor};},
 review:async(id,source)=>{const d=await new ProgramReviewStore(rpc()).get(id);if(d.source.name!==source)throw new ReviewFailure('invalid_input');return {...d,factsVersion:Number(d.factsVersion)};},filters:()=>new ContentFilterStore(rpc()),allowSynthetic:true,now:()=>new Date('2026-01-01T00:00:00Z')});
const post=(body,options={})=>new Request('https://example.test/api/admin/location-research',{method:'POST',headers:{origin:'https://example.test','content-type':'application/json',...options.headers},body:JSON.stringify(body)});
async function prepare(){const r=await locationResearchRequest(post({action:'prepare',source:'seoul_reservation',ids}),deps());eq(r.status,200);ok(r.headers.get('cache-control').includes('no-store'));return r.json();}
const evidence={place:'합성물빛공원 교육장 앞',url:'https://parks.seoul.go.kr/synthetic-location',excerpt:'합성물빛공원 교육장 앞 위치: 서울특별시 강동구 합성길',province:'11',district:'강동구'};
async function report(){const prepared=await prepare();return worker.researchLocations(prepared,{ready:async()=>{},investigate:async()=>({status:'suggested',evidence})},{batchId,createdAt:'2026-01-01T00:00:00Z',mode:'synthetic',maxCalls:3});}
const apply=(r,selected=ids,extra={})=>locationResearchRequest(post({action:'apply',report:r,ids:selected}),{...deps(),...extra});

reset();const original=structuredClone([...rows]);const r=await report();eq(calls.length,0);eq([...rows],original);eq(r.items.length,3);
eq((await apply(r,[ids[0]])).status,200);eq(calls.length,1);eq(filterRows.get(ids[0]).data.location.value.venues[0].address,'');
eq(rows.get(ids[0]).facts,original[0][1].facts);eq(rows.get(ids[0]).observedFacts,original[0][1].observedFacts);eq(rows.get(ids[0]).source,original[0][1].source);eq(rows.get(ids[0]).history.slice(0,-1),original[0][1].history);eq(filterRows.get(ids[1]).data.location.status,'unknown');
eq((await (await apply(r,[ids[0]])).json()).results[0].status,'skipped');eq(calls.length,1);

// Selected current values only; operator decisions and post-research edits survive.
for(const change of [()=>{rows.get(ids[0]).facts.description+='\n운영자 추가';},()=>{rows.get(ids[0]).factsVersion++;},()=>{rows.get(ids[0]).version='c'.repeat(64);},()=>{filterRows.get(ids[0]).filterVersion++;},()=>{filterRows.get(ids[0]).origins.location='operator';},()=>{filterRows.get(ids[0]).editable=false;},()=>{rows.get(ids[0]).aiStatus='claimed';},()=>{rows.get(ids[0]).aiStatus='completed';},()=>{rows.get(ids[0]).status='excluded';},()=>{filterRows.get(ids[0]).data.location=core.proposedLocation(evidence);}]){
 reset();const p=await report();change();const out=await (await apply(p,[ids[0]])).json();eq(out.results[0].status,'skipped');eq(calls.length,0);
}
reset();const race=await report();beforeSave=()=>{rows.get(ids[0]).version='c'.repeat(64);};eq((await (await apply(race,[ids[0]])).json()).results[0].status,'skipped');eq(filterRows.get(ids[0]).data.location.status,'unknown');
reset();const unknown=await report();failAt=ids[1];let out=await (await apply(unknown)).json();eq(out.results.map(x=>x.status),['saved','unknown','unprocessed']);eq(out.stopped,true);eq(calls.length,2);
reset();const noLive=await report();eq((await apply(noLive,ids,{allowSynthetic:false})).status,422);eq(calls.length,0);
reset();authError='signed_out';eq((await locationResearchRequest(post({action:'prepare',source:'seoul_reservation',ids}),deps())).status,401);eq(readCalls.length,0);
authError='forbidden';eq((await locationResearchRequest(post({action:'prepare',source:'seoul_reservation',ids}),deps())).status,403);eq(readCalls.length,0);
authError=null;eq((await locationResearchRequest(post({action:'prepare',source:'seoul_reservation',ids},{headers:{origin:'https://evil.test'}}),deps())).status,403);eq(readCalls.length,0);
for(const bad of [[],[...ids,ids[0]],Array.from({length:26},(_,i)=>`30000000-0000-4000-8000-${String(i).padStart(12,'0')}`),['not-an-id']])eq((await locationResearchRequest(post({action:'prepare',source:'seoul_reservation',ids:bad}),deps())).status,422);
reset();const valid=await report();
for(const mutate of [x=>x.items[0].evidence.url='https://seoul.go.kr.evil.test/x',x=>x.items[0].evidence.url='javascript:alert(1)',x=>x.items[0].evidence.url='http://127.0.0.1/',x=>x.items[0].evidence.url='https://parks.seoul.go.kr/?token=secret',x=>x.items[0].evidence.district='없는구',x=>x.items[0].evidence.excerpt='공원 위치를 찾지 못함',x=>x.items[0].evidence.place='합성산',x=>x.items[0].snapshot.description+='\n집결지: 또다른공원',x=>x.items.push(x.items[0])]){
 const bad=structuredClone(valid);mutate(bad);assert.throws(()=>core.locationReport(bad));checks++;
}
assert.throws(()=>core.locationReport({...valid,secret:'token'}));checks++;
// Frozen order and per-item failures, versus common/unknown stopping all calls.
reset();const packet=await prepare();let ready=0,n=0;
const mixed=await worker.researchLocations(packet,{ready:async()=>{ready++;},investigate:async()=>{n++;return n===1?{status:'suggested',evidence:{...evidence,province:'wrong'}}:{status:'no_evidence',evidence:null};}},{batchId,createdAt:valid.createdAt,mode:'synthetic',maxCalls:3});
eq(ready,1);eq(n,3);eq(mixed.items.map(x=>x.status),['error','no_evidence','no_evidence']);
n=0;await assert.rejects(worker.researchLocations(packet,{ready:async()=>{},investigate:async()=>{n++;if(n===2)throw Error('private provider error');return {status:'no_evidence',evidence:null};}},{batchId,createdAt:valid.createdAt,mode:'synthetic',maxCalls:3}),e=>{eq(e.partial.items.length,1);eq(e.message,'research_response_unknown');return true;});eq(n,2);
n=0;await assert.rejects(worker.researchLocations(packet,{ready:async()=>{throw Error('auth');},investigate:async()=>{n++;}},{batchId,createdAt:valid.createdAt,mode:'synthetic',maxCalls:3}));eq(n,0);
await assert.rejects(worker.researchLocations(packet,{ready:async()=>{n++;},investigate:async()=>{}},{batchId,createdAt:valid.createdAt,mode:'synthetic',maxCalls:2}));eq(n,0);
// Shared worker has no source-specific branch; a future source reuses the same contract.
const future=structuredClone(packet);future.items[0].source='synthetic_future_source';
eq((await worker.researchLocations(future,{ready:async()=>{},investigate:async()=>({status:'no_evidence',evidence:null})},{batchId,createdAt:valid.createdAt,mode:'synthetic',maxCalls:3})).items[0].snapshot.source,'synthetic_future_source');
// Explicit meeting takes precedence; a venue is usable when no meeting is given.
const venue=structuredClone(valid);venue.items[0].snapshot.description='개최 장소: 합성물빛공원 교육장 앞';
eq(core.locationReport(venue).items[0].evidence.place,evidence.place);
const meetingBold=structuredClone(valid);meetingBold.items[0].snapshot.description='**만나는 장소**: 합성물빛공원 교육장 앞\n활동 장소: 합성산';
eq(core.locationReport(meetingBold).items[0].evidence.place,evidence.place);
for(const description of ['기관 주소: 합성물빛공원 교육장 앞','문의처: 합성물빛공원 교육장 앞','만나는 장소는 별도 안내\n활동 장소: 합성물빛공원 교육장 앞']){
 const bad=structuredClone(valid);bad.items[0].snapshot.description=description;assert.throws(()=>core.locationReport(bad));checks++;
}
const negative=structuredClone(valid);negative.items[0]={snapshot:negative.items[0].snapshot,status:'ambiguous',evidence:null};
eq((await apply(negative,[ids[0]])).status,422);eq(calls.length,0);
eq((await locationResearchRequest(post({action:'apply',report:valid,ids:[ids[0]],patch:{description:'wrong'}}),deps())).status,422);
eq((await locationResearchRequest(new Request('https://example.test/api/admin/location-research',{method:'GET'}),deps())).status,422);
eq((await locationResearchRequest(post({action:'prepare',source:'seoul_reservation',ids},{headers:{'content-length':String(3*1024*1024)}}),deps())).status,422);

// Real separate launcher, with a trusted synthetic investigator; no provider SDK.
const temp=fs.mkdtempSync(path.join(root,'scripts','__pycache__','location-research-cli-'));
const inputFile=path.join(temp,'input.json'),outputFile=path.join(temp,'output.json'),providerFile=path.join(temp,'investigator.mjs');
fs.writeFileSync(inputFile,JSON.stringify(packet));
fs.writeFileSync(providerFile,"export const mode='synthetic';export const investigator={ready:async()=>{},investigate:async()=>({status:'no_evidence',evidence:null})};");
const args=['scripts/run_location_research.mjs','--input',inputFile,'--output',outputFile,'--investigator',providerFile,'--max-calls','3'];
const cli=JSON.parse(execFileSync(process.execPath,args,{cwd:root,encoding:'utf8'}));eq(cli.items,3);eq(cli.reviewWrites,0);eq(cli.mode,'synthetic');
eq(core.locationReport(JSON.parse(fs.readFileSync(outputFile,'utf8'))).items.length,3);
const bytesBefore=fs.readFileSync(outputFile);
assert.throws(()=>execFileSync(process.execPath,args,{cwd:root,stdio:'pipe'}));checks++;eq(fs.readFileSync(outputFile),bytesBefore);

// Actual --provider path -> subprocess -> common Pro Auth -> fake search/GPT
// -> independent fake official-page read -> strict report -> normal fake save.
const {main:launchResearch}=await import('./run_location_research.mjs');
const {createPlanInvestigator}=await import('./location_plan_bridge.mjs');
const fakeWorker=path.join(temp,'fake-plan-worker.py'),planOutput=path.join(temp,'plan-output.json');
fs.writeFileSync(fakeWorker,`import sys\nsys.path.insert(0,${JSON.stringify(path.join(root,'scripts'))})\nimport test_location_plan_research as f\nfrom ingest.ai_provider import create_location_research_adapter\nfrom location_research_worker import serve\nt=f.LocationResearchTests('test_pipe_path_uses_common_auth_and_emits_only_safe_proposals')\nt.setUp()\ndef factory(provider,**options):\n    client=f.FakeClient([f.events(f.completed()),f.events(f.completed({'status':'ambiguous','evidence':None})),f.events(f.completed({'status':'no_evidence','evidence':None}))])\n    return create_location_research_adapter(provider,**options,manager=t.owner.manager(),client=client,fetch_page=lambda url:f.EVIDENCE['excerpt'])\ntry:\n    serve(sys.stdin,sys.stdout,factory=factory)\nfinally:\n    t.doCleanups()\n`);
const planArgs=['--input',inputFile,'--output',planOutput,'--provider','chatgpt_plan','--python',process.env.MACHIMOA_TEST_PYTHON,'--max-calls','3'];
const consoleBefore=console.log,logs=[];console.log=value=>logs.push(JSON.parse(value));
try{
 await launchResearch(planArgs,{makePlanInvestigator(){throw Error('auth without execute');}});
 eq(logs.at(-1).mode,'validation-only');eq(fs.existsSync(planOutput),false);
 await launchResearch([...planArgs,'--execute'],{makePlanInvestigator(options){const bridge=createPlanInvestigator({...options,workerPath:fakeWorker});bridge.mode='synthetic';return bridge;}});
}finally{console.log=consoleBefore;}
eq(logs.at(-1).stats.requests,3);eq(logs.at(-1).stats.officialReads,1);eq(logs.at(-1).stats.usageUnknownCount,0);
const planReport=core.locationReport(JSON.parse(fs.readFileSync(planOutput,'utf8')));
eq(planReport.mode,'synthetic');eq(planReport.items.map(x=>x.status),['suggested','ambiguous','no_evidence']);
reset();eq((await (await apply(planReport,[ids[0]])).json()).results[0].status,'saved');eq(calls.length,1);
eq(rows.get(ids[0]).facts,original[0][1].facts);eq(rows.get(ids[0]).observedFacts,original[0][1].observedFacts);
const stopWorker=path.join(temp,'fake-plan-stop-worker.py'),stopOutput=path.join(temp,'stopped-output.json');
fs.writeFileSync(stopWorker,fs.readFileSync(fakeWorker,'utf8').replace("f.events(f.completed({'status':'ambiguous','evidence':None}))","[{'type':'error','code':'subscription_sharing_unsupported_capability'}]"));
const stoppedArgs=planArgs.map(x=>x===planOutput?stopOutput:x);
await assert.rejects(launchResearch([...stoppedArgs,'--execute'],{makePlanInvestigator(options){const bridge=createPlanInvestigator({...options,workerPath:stopWorker});bridge.mode='synthetic';return bridge;}}));checks++;
const stoppedReport=JSON.parse(fs.readFileSync(stopOutput,'utf8'));
eq(stoppedReport.stopped,true);eq(stoppedReport.code,'subscription_sharing_unsupported_capability');
eq(stoppedReport.partial.items.length,1);eq(stoppedReport.stats.requests,2);eq(stoppedReport.stats.usageUnknownCount,1);
eq(calls.length,1); // The research launcher never invokes the review save RPC.
assert.throws(()=>core.locationReport(stoppedReport));checks++;

// Title-supplied venue and parent-facility quotation still use the very same
// authorized save path; no source/fact/history rewriting or new RPC is needed.
reset();rows.get(ids[0]).source.title='[합성물빛공원] 지역 체험';rows.get(ids[0]).facts.description='프로그램 신청과 안전 안내';
const linkedBefore=structuredClone(rows.get(ids[0]));
const parentEvidence={...evidence,place:'합성물빛공원',excerpt:'합성물빛공원\n서울특별시 강동구 합성길'};
const linkedReport=await worker.researchLocations(await prepare(),{ready:async()=>{},investigate:async()=>({status:'suggested',evidence:parentEvidence})},{batchId,createdAt:valid.createdAt,mode:'synthetic',maxCalls:3});
eq(calls.length,0);eq((await (await apply(linkedReport,[ids[0]])).json()).results[0].status,'saved');eq(calls.length,1);
eq(rows.get(ids[0]).facts,linkedBefore.facts);eq(rows.get(ids[0]).observedFacts,linkedBefore.observedFacts);eq(rows.get(ids[0]).source,linkedBefore.source);eq(rows.get(ids[0]).history.slice(0,-1),linkedBefore.history);
eq(filterRows.get(ids[1]).data.location.status,'unknown');

// Actual React panel import -> select -> one handler -> fake authenticated RPC.
const nodes=t=>[t,...React.Children.toArray(t?.props?.children).flatMap(c=>typeof c==='object'?nodes(c):[])];
const labelText=t=>[typeof t==='string'?t:'',...React.Children.toArray(t?.props?.children).flatMap(labelText)].join('');
let disabled=false;
function render(){cursor=0;refCursor=0;return Panel({items:[...rows].map(([id,d])=>({id,title:d.source.title,sourceName:d.source.name,status:'open',reasons:[]})),disabled,onBusy(){},onSaved(){saved++;}});}
const fileInput=()=>nodes(render()).find(x=>x?.type==='input'&&x.props.type==='file');
const importReport=async p=>{await fileInput().props.onChange({target:{files:[{size:JSON.stringify(p).length,text:async()=>JSON.stringify(p)}]},currentTarget:{value:'x'}});await new Promise(r=>setTimeout(r,0));};
const applyButton=()=>nodes(render()).find(x=>x?.type==='button'&&labelText(x).includes('개최지역 저장'));
const proposalBoxes=()=>nodes(render()).filter(x=>x?.type==='label'&&labelText(x).includes('제안 반영')).map(x=>nodes(x).find(y=>y?.type==='input'));
globalThis.fetch=async(url,opts)=>{eq(url,'/api/admin/location-research');eq(opts.cache,'no-store');eq(opts.credentials,'same-origin');requests.push(JSON.parse(opts.body));return locationResearchRequest(post(JSON.parse(opts.body)),deps());};
reset();const uiReport=await report();await importReport(uiReport);eq(proposalBoxes().length,3);eq(applyButton().props.disabled,true);eq(calls.length,0);
proposalBoxes()[0].props.onChange({target:{checked:true}});eq(applyButton().props.disabled,false);
await Promise.all([applyButton().props.onClick(),applyButton().props.onClick()]);await new Promise(r=>setTimeout(r,0));eq(requests.length,1);eq(calls.length,1);eq(saved,1);eq(requests[0].ids,[ids[0]]);eq(applyButton().props.disabled,true);
eq(proposalBoxes()[0].props.disabled,true);eq(proposalBoxes()[1].props.disabled,false);
proposalBoxes()[1].props.onChange({target:{checked:true}});await applyButton().props.onClick();await new Promise(r=>setTimeout(r,0));eq(requests.length,2);eq(calls.length,2);eq(requests[1].ids,[ids[1]]);
reset();const p2=await report();await importReport(p2);disabled=true;eq(applyButton().props.disabled,true);await applyButton().props.onClick();eq(calls.length,0);disabled=false;
reset();await importReport(await report());proposalBoxes()[0].props.onChange({target:{checked:true}});globalThis.fetch=async()=>{throw Error('response unknown');};await applyButton().props.onClick();await new Promise(r=>setTimeout(r,0));eq(applyButton().props.disabled,true);eq(calls.length,0);
console.log(JSON.stringify({checks,result:'passed',fakeResearchAuthRpc:true,actualPanel:true,actualAi:0,operatingDb:0,approval:0,publication:0}));
