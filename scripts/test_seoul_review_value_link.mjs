// Synthetic extraction -> actual DTO/Auth handler -> fenced fake RPC. No network.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {execFileSync} from 'node:child_process';
import http from 'node:http';
import https from 'node:https';
registerHooks({resolve(s,c,n){try{return n(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return n(s+'.ts',c);throw e;}}});
globalThis.fetch=()=>{throw Error('network forbidden')};http.request=https.request=()=>{throw Error('network forbidden')};
const {ProgramReviewStore}=await import('../app/lib/review/program-store.ts');
const {programRequest}=await import('../app/lib/review/program-handlers.ts');
const {programCommand}=await import('../app/lib/review/program-contract.ts');
const {buildProgramSave,displayProgramValue}=await import('../app/lib/review/program-ui.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const packets=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','scripts/test_seoul_review_value_link.py','--export'],{encoding:'utf8'}));
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};const ok=v=>{assert.ok(v);checks++;};
eq(displayProgramValue('source_status','announced'),'접수 전');
const id='30000000-0000-4000-8000-000000000001',actor='00000000-0000-4000-8000-000000000002';
for(const packet of packets){
 const original=packet.item,filters={schema:'content-filters-v1',revision:original.revision_hash,filterVersion:7,data:original.filterFacts.data,missing:[],origins:{topic:'operator'}};
 let row={id,revision:original.revision_hash,version:'a'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:3,source:{name:'seoul_reservation',title:original.min_fields.title,url:original.program_facts.official_url,body:original.normalized_payload.program_text},facts:structuredClone(original.program_facts),observedFacts:structuredClone(original.program_facts),filterInfo:filters,status:'open',aiStatus:'blocked',result:{decision:'review_required',disposition:'observe_only',reasons:['program_description_missing']},editableFields:['description'],history:[{action:'save_facts',actor,at:'2026-01-01T00:00:00Z',note:'기존 이력',fields:['source_status']}]};
 const before=structuredClone(row);const calls=[];
 const store=new ProgramReviewStore({async rpc(name,args){calls.push({name,args:structuredClone(args)});if(name==='admin_program_detail')return {data:row,error:null};assert.equal(name,'admin_program_save');if(args.p_revision!==row.revision||args.p_version!==row.version)return {data:null,error:{code:'PT409'}};if(Object.keys(args.p_patch).some(k=>!row.editableFields.includes(k)))return {data:null,error:{code:'PT422'}};row={...row,facts:{...row.facts,...args.p_patch},factsVersion:4,version:'b'.repeat(64),history:[...row.history,{action:'save_facts',actor:args.p_actor,at:'2026-01-02T00:00:00Z',note:'',fields:Object.keys(args.p_patch)}]};return {data:row,error:null};}});
 const deps={authorize:async()=>({userId:actor}),store:()=>store},url='https://example.test/api/admin/program-review/'+id;
 let response=await programRequest(new Request(url),id,deps);eq(response.status,200);let loaded=(await response.json()).item;
 eq(loaded.facts.source_status,original.program_facts.source_status);eq(loaded.observedFacts,before.observedFacts);eq(loaded.filterInfo.filterVersion,7);
 const command=buildProgramSave(loaded,{...loaded.facts,description:'합성 운영자 설명입니다. 기존 조건을 유지하며 확인합니다.'},'',[]);
 eq(Object.keys(command.patch),['description']);eq(command.revision,before.revision);eq(command.version,before.version);
 const post=body=>new Request(url,{method:'POST',headers:{origin:'https://example.test','content-type':'application/json'},body:JSON.stringify(body)});
 response=await programRequest(post(command),id,deps);eq(response.status,200);
 eq(row.observedFacts,before.observedFacts);eq(row.source,before.source);eq(row.filterInfo,before.filterInfo);eq(row.history.slice(0,1),before.history);eq(row.factsVersion,4);eq(row.aiStatus,'blocked');
 response=await programRequest(post(command),id,deps);eq(response.status,409);eq(row.factsVersion,4);
 const stale={...command,revision:'c'.repeat(64),version:row.version};eq((await programRequest(post(stale),id,deps)).status,409);
 for(const denied of ['signed_out','forbidden','auth_error']){const n=calls.length;response=await programRequest(new Request(url),id,{...deps,authorize:async()=>{throw new AdminAccessError(denied)}});eq(response.status,{signed_out:401,forbidden:403,auth_error:503}[denied]);eq(calls.length,n);}
 const n=calls.length;eq((await programRequest(new Request(url,{method:'POST',headers:{origin:'https://evil.test','content-type':'application/json'},body:JSON.stringify(command)}),id,deps)).status,403);eq(calls.length,n);
 ok(calls.every(x=>['admin_program_detail','admin_program_save'].includes(x.name)));
}
assert.throws(()=>programCommand({action:'save_facts',revision:'a'.repeat(64),version:'b'.repeat(64),patch:{source_status:'invented'},resolve:[],note:''}));checks++;
console.log(JSON.stringify({checks,syntheticAuthRpc:true,packets:packets.length,network:0,ai:0,result:'passed'}));
