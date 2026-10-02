// Synthetic UI/transport tests only. No real Auth, DB, API, evaluator, or AI.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:http';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(`${s}.ts`,c);throw e;}}});
const {buildProgramSave,programPatch,reviewDetailPath,displayProgramValue,programOutcome,reasonPatchFields}=await import('../app/lib/review/program-ui.ts');
const {programItem}=await import('../app/lib/review/program-store.ts');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {programRequest}=await import('../app/lib/review/program-handlers.ts');
const fixture=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_program_db.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
const actor='00000000-0000-4000-8000-000000000001';
const ids=[1,2,3].map(n=>`30000000-0000-4000-8000-${String(n).padStart(12,'0')}`);
const base=structuredClone(fixture.fixtures[0].item.program_facts);
Object.assign(base,{activity_region:'unknown',activity_evidence:[],delivery_mode:'offline',source_status:'open',fee_kind:'paid',fee_amounts:['1인 5,000원'],conditions:['어린이는 보호자 동반'],conflicts:[],missing:['activity_location_unknown'],editorial_pending:[]});
base.periods={RCPTBGNDT:{raw:'2026-10-01',value:'2026-10-01',status:'ok',precision:'day'},RCPTENDDT:{raw:'2026-10-31',value:'2026-10-31',status:'ok',precision:'day'},SVCOPNBGNDT:{raw:'2026-11-01',value:'2026-11-01',status:'ok',precision:'day'},SVCOPNENDDT:{raw:'2026-11-30',value:'2026-11-30',status:'ok',precision:'day'}};
function makeItem(id,n){const facts=structuredClone(base);if(n===1)facts.conflicts=['date_weekday_conflict'];if(n===2){facts.missing.push('unsupported_test_reason','missing_source_url');facts.conflicts.push('source_status_conflict');facts.official_url='';}
 return programItem({id,revision:'a'.repeat(64),version:'b'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:1,
 source:{name:'seoul_reservation',title:['개최지 확인 문화 체험 (합성 시험 자료)','신청·운영 기간 확인 (합성 시험 자료)','미지원 사유·제외 확인 (합성 시험 자료)'][n],url:facts.official_url||null,body:'서울 개최 여부를 확인하는 합성 원문입니다.\n어린이는 보호자 동반, 유료 5,000원.\n<script>window.__unsafeExecuted = true</script>'},
 facts,observedFacts:structuredClone(facts),result:{decision:'review_required',disposition:'observe_only',reasons:[...facts.missing,...facts.conflicts]},status:'open',aiStatus:'blocked',editableFields:['delivery_mode','activity_region','activity_evidence',...(n===1?['periods','period_evidence']:[]),...(n===2?['source_status','official_url']:[])],history:[]},id);}
let checks=0;function check(fn){fn();checks++;}
const original=makeItem(ids[0],0),draft=structuredClone(original.facts);
Object.assign(draft,{activity_region:'capital',activity_evidence:[' 서울 종로구 개최 ',''],conditions:['FORGED READONLY'],missing:[],conflicts:[]});
check(()=>assert.equal(reviewDetailPath('facts',ids[0],'seoul_reservation'),`/api/admin/program-review/${ids[0]}`));
for(const [kind,source] of [['facts','youthcenter_policy'],['facts','youthcenter_content'],['candidates','seoul_reservation']])check(()=>assert.equal(reviewDetailPath(kind,ids[0],source),`/api/admin/review/${kind}/${ids[0]}`));
const cmd=buildProgramSave(original,draft,' 공식 개최지 확인 ',['activity_location_unknown']);
check(()=>assert.deepEqual(Object.keys(cmd.patch).sort(),['activity_evidence','activity_region']));
check(()=>assert.deepEqual(cmd.patch.activity_evidence,['서울 종로구 개최']));
check(()=>assert.equal(cmd.note,'공식 개최지 확인'));
check(()=>assert.equal(cmd.revision,original.revision));check(()=>assert.equal(cmd.version,original.version));
for(const [changed,note,resolve] of [[original.facts,'근거',[]],[draft,'',[]],[draft,'근거',['date_weekday_conflict']],[draft,'근거',['unsupported_test_reason']]])check(()=>assert.throws(()=>buildProgramSave(original,changed,note,resolve),e=>e.code==='invalid_input'));
check(()=>assert.deepEqual(programPatch(original.facts,draft,[]),{}));
check(()=>assert.equal(displayProgramValue('application_methods',['onsite','internet']),'현장 접수\n인터넷 예약'));
check(()=>assert.equal(displayProgramValue('fee_kind','paid'),'유료'));check(()=>assert.match(programOutcome('not_currently_available'),/신청 불가/));
const periods=makeItem(ids[1],1),dates=structuredClone(periods.facts);dates.periods.RCPTENDDT.value='2026-10-30';dates.periods.RCPTENDDT.raw='2026-10-30';dates.period_evidence=['공식 신청 종료 날짜 확인'];
const dateCmd=buildProgramSave(periods,dates,'요일 충돌 확인',['date_weekday_conflict']);
check(()=>assert.equal(dateCmd.patch.periods.RCPTENDDT.precision,'day'));check(()=>assert.equal(dateCmd.patch.periods.RCPTENDDT.value,'2026-10-30'));check(()=>assert.equal(dateCmd.patch.periods.SVCOPNENDDT.value,'2026-11-30'));
check(()=>assert.equal(Object.hasOwn(reasonPatchFields,'unsupported_test_reason'),false));
const items=new Map(ids.map((id,n)=>[id,makeItem(id,n)]));let mutations=0;
function execute(name,args){const item=items.get(args.p_id);if(!item)return {code:'PT404',message:'not_found'};
 if(name==='admin_program_detail')return structuredClone(item);
 if(args.p_actor!==actor)throw new Error('Unexpected test actor');
 if(args.p_note==='충돌 시험')return {code:'PT409',message:'review_conflict'};
 if(args.p_note==='실패 시험')return {code:'XX000',message:'DO_NOT_ECHO_SECRET'};
 if(args.p_revision!==item.revision||args.p_version!==item.version||item.status!=='open')return {code:'PT409',message:'review_conflict'};
 const next=structuredClone(item);mutations++;
 if(name==='admin_program_exclude'){next.status='excluded';next.aiStatus='cancelled';next.result={decision:'out_of_scope',disposition:'non_target',reasons:['manual_service_exclusion']};next.editableFields=[];}
 else {Object.assign(next.facts,args.p_patch);for(const key of ['missing','conflicts'])next.facts[key]=next.facts[key].filter(c=>!args.p_resolve.includes(c));next.result.reasons=[...next.facts.missing,...next.facts.conflicts];next.editableFields=[...new Set(next.result.reasons.flatMap(c=>reasonPatchFields[c]??[]))];if(!next.result.reasons.length){next.result.decision='in_scope';next.result.disposition='target';next.status='resolved';next.aiStatus='queued';next.editableFields=[];}}
 next.version=String(mutations).padStart(64,'0');next.factsVersion++;next.history.unshift({action:name==='admin_program_exclude'?'exclude':'save_facts',actor:args.p_actor,at:new Date().toISOString(),note:args.p_note,fields:Object.keys(args.p_patch??{})});items.set(item.id,next);return next;
}
if(!process.argv.includes('--serve')){
 const calls=[];const deps={authorize:async()=>({userId:actor}),store:()=>({get:async id=>items.get(id),execute:async(id,command,uuid)=>{calls.push({id,command,uuid});return original;}})};
 const post=(body)=>new Request(`http://localhost/api/admin/program-review/${ids[0]}`,{method:'POST',headers:{origin:'http://localhost','content-type':'application/json'},body:JSON.stringify(body)});
 const response=await programRequest(post(cmd),ids[0],deps);check(()=>assert.equal(response.status,200));check(()=>assert.equal(calls[0].uuid,actor));check(()=>assert.match(response.headers.get('cache-control'),/no-store/));
 const denied=await programRequest(post({...cmd,actor:'forged'}),ids[0],deps);check(()=>assert.equal(denied.status,422));check(()=>assert.equal(calls.length,1));
 console.log(`PASS: ${checks} program UI patch/routing/date/resolve/transport checks (synthetic only).`);
}else{
 const legacy=new LocalReviewStore();
 const server=createServer(async(req,res)=>{try{
 const chunks=[];for await(const c of req)chunks.push(c);const body=Buffer.concat(chunks);
 if(!req.url.startsWith('/rest/v1/rpc/admin_')){const upstream=await fetch(`http://127.0.0.1:54329${req.url}`,{redirect:'manual',method:req.method,headers:{'content-type':req.headers['content-type']??'application/json',authorization:req.headers.authorization??''},...(req.method==='GET'?{}:{body})});res.writeHead(upstream.status,Object.fromEntries(upstream.headers));res.end(Buffer.from(await upstream.arrayBuffer()));return;}
 const args=JSON.parse(body.toString()),name=req.url.split('/').at(-1);let data;
 if(name==='admin_review_list'){data=await legacy.list(args.p_kind,args.p_offset);if(args.p_kind==='facts'&&args.p_offset===0)data=[...items.values()].filter(i=>i.status==='open').map(i=>({id:i.id,title:i.source.title,sourceName:i.source.name,status:i.status,reasons:i.result.reasons})).concat(data);}
 else if(name==='admin_review_detail'){data=await legacy.get(args.p_kind,args.p_id);data.version='c'.repeat(64);data.editableFields=data.kind==='facts'?['scope','regions','evidence']:undefined;data.excludeAllowed=false;}
 else if(name.startsWith('admin_program_'))data=execute(name,args);
 else data={code:'PT422',message:'unsupported_test_mutation'};
 res.setHeader('content-type','application/json');res.setHeader('cache-control','no-store');if(data.code)res.statusCode=data.code==='PT409'?409:data.code==='PT404'?404:503;res.end(JSON.stringify(data));
 }catch{res.writeHead(500,{'content-type':'application/json'});res.end('{"code":"XX000","message":"local_test_failure"}');}});
 await new Promise(r=>server.listen(54330,'127.0.0.1',r));console.log('Synthetic program/legacy RPC UI server on 127.0.0.1:54330. NO SQL/DB/AI. Notes 충돌 시험 / 실패 시험 inject local errors only.');
}
