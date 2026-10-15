// Preserved public URL values; synthetic Auth, facts, RPC and edit history only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {registerHooks} from 'node:module';
import http from 'node:http';
import https from 'node:https';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(`${s}.ts`,c);throw e;}}});
globalThis.fetch=()=>{throw Error('external_network_forbidden');};
http.request=https.request=()=>{throw Error('external_network_forbidden');};
const {ProgramReviewStore,programItem}=await import('../app/lib/review/program-store.ts');
const {programRequest}=await import('../app/lib/review/program-handlers.ts');
const {programCommand,programFacts}=await import('../app/lib/review/program-contract.ts');
const {buildProgramSave,programPatch}=await import('../app/lib/review/program-ui.ts');
const {emptyContentFilters,missingContentFilters}=await import('../app/lib/contentFilters.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const fixture=JSON.parse(fs.readFileSync(new URL('./fixtures/seoul_admin_external_links.json',import.meta.url),'utf8'));
assert.equal(fixture.links.length,16);
const revision='a'.repeat(64),version='b'.repeat(64),actor='00000000-0000-4000-8000-000000000001';
const base={schema_version:'program-scope-v1-local',content_kind:'unknown',application_actor:'individual',delivery_mode:'unknown',activity_region:'unknown',activity_evidence:[],residence_scope:'not_stated',residence_evidence:[],target_raw:'성인',conditions:['합성 참가 제한 유지'],application_methods:[],fee_kind:'free',fee_amounts:[],source_status:'open',conflicts:[],missing:['program_description_missing'],editorial_pending:[],period_evidence:[],description:'',official_url:'',periods:Object.fromEntries(['RCPTBGNDT','RCPTENDDT','SVCOPNBGNDT','SVCOPNENDDT'].map((k,i)=>[k,{raw:`2099-${i<2?'10':'11'}-${i%2?'30':'01'}`,value:`2099-${i<2?'10':'11'}-${i%2?'30':'01'}`,status:'ok',precision:'day'}]))};
function item(link,n){const id=`30000000-0000-4000-8000-${String(n+1).padStart(12,'0')}`,facts={...structuredClone(base),official_url:link.url};const filters=emptyContentFilters('program');return {id,revision,version,schema:base.schema_version,profile:'program_capital_v1_local',factsVersion:1,source:{name:'seoul_reservation',title:`외부 링크 합성 ${n+1}`,url:link.url,body:'보존하는 합성 원문'},facts,observedFacts:structuredClone(facts),status:'open',aiStatus:'blocked',result:{decision:'review_required',disposition:'observe_only',reasons:['program_description_missing']},editableFields:['description'],history:[{action:'save_facts',actor,at:'2026-01-01T00:00:00Z',note:'기존 합성 이력',fields:['target_raw']}],filterInfo:{schema:'content-filters-v1',revision,filterVersion:3,data:filters,missing:missingContentFilters(filters),origins:{}},originalSourceUrl:link.original};}
const rows=fixture.links.map(item),db=new Map(rows.map(x=>[x.id,structuredClone(x)]));
let checks=0,calls=[],error=null;const ok=v=>{assert.ok(v);checks++;};const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const store=new ProgramReviewStore({async rpc(name,args){calls.push({name,args:structuredClone(args)});if(error)return {data:null,error};const saved=db.get(args.p_id);if(name==='admin_program_detail')return {data:structuredClone(saved),error:null};assert.equal(name,'admin_program_save');if(args.p_revision!==saved.revision||args.p_version!==saved.version)return {data:null,error:{code:'PT409'}};if(Object.keys(args.p_patch).some(k=>!saved.editableFields.includes(k)))return {data:null,error:{code:'PT422'}};const next={...saved,facts:{...saved.facts,...args.p_patch},factsVersion:saved.factsVersion+1,version:'c'.repeat(64),history:[...saved.history,{action:'save_facts',actor:args.p_actor,at:'2026-01-02T00:00:00Z',note:args.p_note,fields:Object.keys(args.p_patch)}]};db.set(saved.id,next);return {data:structuredClone(next),error:null};}});
let authCount=0,storeCount=0;const deps={authorize:async()=>{authCount++;return {userId:actor};},store:()=>{storeCount++;return store;}};
const url=id=>`https://synthetic.test/api/admin/program-review/${id}`;
const post=(id,body,origin='https://synthetic.test')=>new Request(url(id),{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(body)});
// Actual GET handler -> fake RPC -> DTO. This fails for all 16 before the fix.
const initial=[];for(const row of rows)initial.push((await programRequest(new Request(url(row.id)),row.id,deps)).status);
eq(initial,Array(16).fill(200));
for(const row of rows){
 const before=structuredClone(db.get(row.id));const dto=programItem(before,row.id);eq(dto.facts.official_url,row.facts.official_url);eq(dto.observedFacts,row.observedFacts);ok(!('originalSourceUrl' in dto));
 const draft={...structuredClone(dto.facts),description:'합성 설명을 확인하여 보완했습니다. 기존 조건은 유지합니다.'};
 const command=buildProgramSave(dto,draft,'',[]);eq(Object.keys(command.patch),['description']);eq(command.revision,revision);eq(command.version,version);
 const start=calls.length;const response=await programRequest(post(row.id,command),row.id,deps);eq(response.status,200);ok(response.headers.get('cache-control').includes('no-store'));eq(calls.length,start+1);eq(calls.at(-1).name,'admin_program_save');eq(calls.at(-1).args.p_actor,actor);
 const after=(await response.json()).item;eq(after.facts.description,draft.description);eq(after.facts.official_url,before.facts.official_url);eq(after.observedFacts,before.observedFacts);eq(after.source,before.source);eq(after.filterInfo,before.filterInfo);eq(after.history.slice(0,before.history.length),before.history);eq(after.factsVersion,2);eq(after.aiStatus,'blocked');eq(db.get(row.id).originalSourceUrl,before.originalSourceUrl);
 eq(programPatch(after.facts,after.facts,after.editableFields),{});
 const stale=await programRequest(post(row.id,command),row.id,deps);eq(stale.status,409);eq(db.get(row.id).factsVersion,2);
 // Attempted read-only field changes are not added to the permitted UI patch.
 const readonlyDraft={...structuredClone(after.facts),official_url:'https://evil.invalid/',description:'다른 합성 설명 변경'};
 eq(Object.keys(buildProgramSave(after,readonlyDraft,'',[]).patch),['description']);
}
const row=rows[0],current=programItem(db.get(row.id),row.id);
// URL editing, when the server explicitly permits it, uses the same contract.
const editable={...current,editableFields:['official_url']};
const replacement=fixture.links[2].url;eq(buildProgramSave(editable,{...current.facts,official_url:replacement},'',[]).patch,{official_url:replacement});
eq(programFacts({...base,official_url:'http://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=legacy_1'}).official_url,'http://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=legacy_1');
eq(programFacts({...base,official_url:''}).official_url,'');
for(const bad of ['https://evil.invalid/','http://kctg.or.kr/tour/touristSiteView.do?tourist_cd=A','https://kctg.or.kr.evil.invalid/tour/touristSiteView.do?tourist_cd=A','https://user@kctg.or.kr/tour/touristSiteView.do?tourist_cd=A','https://kctg.or.kr:443/tour/touristSiteView.do?tourist_cd=A','https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=A#x','https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=A&tourist_cd=B','https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=A&redirect=https://evil.invalid','https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=','https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=%0A','https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=%ZZ','https://kctg.or.kr/tour/touristSiteView.do?page_no=&amp;tourist_cd=A',' https://firesafety.eseoul.go.kr/multi/main.do','https://firesafety.eseoul.go.kr/multi/main.do\n','javascript:alert(1)','https://firesafety.eseoul.go.kr/multi/main.do?x=1','https://umppa.seoul.go.kr/icare/user/chilProgrm/orgideaExprnCtzn/BD_selectOrgideaExprnCtzn.do?q_progrmCl=1&q_placeCode=2','https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=A&x=1']){
 assert.throws(()=>programCommand({action:'save_facts',revision,version,note:'',resolve:[],patch:{official_url:bad}}),e=>e.code==='invalid_input');checks++;
 const count=calls.length;const response=await programRequest(post(row.id,{action:'save_facts',revision,version:current.version,note:'',resolve:[],patch:{official_url:bad}}),row.id,deps);eq(response.status,422);eq(calls.length,count);
}
for(const status of ['signed_out','forbidden','auth_error']){
 const count=calls.length,stores=storeCount;const denied={...deps,authorize:async()=>{throw new AdminAccessError(status);}};
 const response=await programRequest(new Request(url(row.id)),row.id,denied);eq(response.status,status==='signed_out'?401:status==='forbidden'?403:503);eq(calls.length,count);eq(storeCount,stores);
}
let count=calls.length;eq((await programRequest(post(row.id,{action:'save_facts',revision,version:current.version,note:'',resolve:[],patch:{description:'합성 변경'}},'https://evil.invalid'),row.id,deps)).status,403);eq(calls.length,count);
for(const code of ['PT409','XX000']){error={code,message:'DO_NOT_ECHO_PRIVATE_URL'};count=calls.length;const response=await programRequest(post(row.id,{action:'save_facts',revision,version:current.version,note:'',resolve:[],patch:{description:'합성 변경'}}),row.id,deps);eq(response.status,code==='PT409'?409:503);eq(calls.length,count+1);ok(!(await response.text()).includes('DO_NOT_ECHO'));}error=null;
ok(calls.every(x=>['admin_program_detail','admin_program_save'].includes(x.name)));ok(authCount>=calls.length);
console.log(`Seoul external URL Auth/RPC/DTO/edit checks passed: ${checks}; preserved URLs: 16; real DB/Auth/API/AI: 0.`);
