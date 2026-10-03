// Synthetic Auth/RPC only. No secrets, network, actual account or DB.
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
registerHooks({resolve(specifier,context,next){try{return next(specifier,context);}catch(e){if(specifier.startsWith('.')&&!/\.[a-z]+$/i.test(specifier))return next(`${specifier}.ts`,context);throw e;}}});
const {myseoulCommand,myseoulFacts,myseoulReasonFields}=await import('../app/lib/review/myseoul-contract.ts');
const {myseoulItem,MySeoulReviewStore}=await import('../app/lib/review/myseoul-store.ts');
const {myseoulRequest}=await import('../app/lib/review/myseoul-handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {mayCacheResponse}=await import('../app/lib/serviceWorkerCachePolicy.ts');
const samples=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_myseoul_db.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
const id='00000000-0000-4000-8000-000000000002',actor='00000000-0000-4000-8000-000000000001';
const fixture=samples.fixtures.find(f=>f.name==='two_conflicts'),facts=fixture.item.myseoul_facts;
const item={id,revision:facts.source_revision,version:'b'.repeat(64),schema:facts.schema_version,profile:'myseoul-program-v1-local',factsVersion:1,
source:{name:'myseoul_program',title:'합성 제목',url:facts.official_url,body:facts.description},facts,observedFacts:facts,
result:fixture.expected,status:'open',aiStatus:'blocked',editableFields:['application_methods','application_links','fees'],history:[],raw_payload:'DO_NOT_ECHO'};
const command={action:'save_facts',revision:item.revision,version:item.version,note:'원문 신청 방법 확인',patch:{application_methods:['인터넷·방문 병행']},resolve:['source_fact_conflict:application_method']};
let checks=0,calls=[],error=null,data=item;
const store=new MySeoulReviewStore({async rpc(name,args){calls.push({name,args});return {data,error};}});
assert.ok(!JSON.stringify(myseoulItem(item,id)).includes('DO_NOT_ECHO'));checks++;
assert.deepEqual(myseoulFacts({...facts,raw_payload:'DO_NOT_ECHO'}),facts);checks++;
for(const bad of [{...item,aiStatus:'queued'},{...item,schema:'program-scope-v1-local'},{...item,source:{...item.source,name:'seoul_reservation'}},{...item,editableFields:['issues']},{...item,revision:'a'.repeat(64)},{...item,factsVersion:0},{...item,facts:{...facts,official_url:'https://evil.invalid'}}]){
assert.throws(()=>myseoulItem(bad,id),e=>e.code==='unavailable');checks++;
}
for(const bad of [{...command,actor:'forged'},{...command,patch:{issues:[]}},{...command,patch:{missing:[]}},{...command,patch:{conflicts:[]}},{...command,patch:{delivery_mode:'hybrid'}},{...command,note:''},{...command,patch:{fees:[{component:'bogus',evidence:['무료']}]}},{...command,patch:{application_links:['javascript:alert(1)']}},{...command,patch:{description:'<img src=x onerror=alert(1)>'}}]){
assert.throws(()=>myseoulCommand(bad),e=>e.code==='invalid_input');checks++;
}
assert.deepEqual(myseoulReasonFields('source_fact_conflict:tuition'),['fees']);assert.deepEqual(myseoulReasonFields('unsupported_reason'),[]);checks++;
let selected=0;const deps={authorize:async()=>({userId:actor}),store:()=>{selected++;return store;}};
const url=`https://example.test/api/admin/myseoul-review/${id}`;
const post=(body,origin='https://example.test')=>new Request(url,{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(body)});
for(const status of ['signed_out','forbidden','auth_error','configuration_error']){
const before=calls.length,s=selected;
for(const request of [new Request(url),post(command)]){const response=await myseoulRequest(request,id,{...deps,authorize:async()=>{throw new AdminAccessError(status);}});assert.equal(response.status,status==='signed_out'?401:status==='forbidden'?403:503);assert.ok(response.headers.get('cache-control').includes('no-store'));checks++;}
assert.equal(calls.length,before);assert.equal(selected,s);checks++;
}
let response=await myseoulRequest(new Request(url),id,deps);assert.equal(response.status,200);assert.equal(mayCacheResponse(response),false);checks++;
response=await myseoulRequest(post(command),id,deps);assert.equal(response.status,200);assert.equal(calls.at(-1).name,'admin_myseoul_program_save');assert.equal(calls.at(-1).args.p_actor,actor);checks++;
const exclude={action:'exclude',revision:item.revision,version:item.version,note:'서비스 범위상 제외'};
response=await myseoulRequest(post(exclude),id,deps);assert.equal(response.status,200);assert.equal(calls.at(-1).name,'admin_myseoul_program_exclude');checks++;
let before=calls.length;
for(const request of [post(command,'https://evil.invalid'),post({...command,actor:'forged'}),post({...command,note:'x'.repeat(200001)}),new Request(url,{method:'POST',headers:{origin:'https://example.test','content-type':'application/json'},body:'{wrong'})]){
response=await myseoulRequest(request,id,deps);assert.ok([403,422].includes(response.status));assert.equal(calls.length,before);checks++;
}
for(const code of ['PT409','PT422','PT404','XX000']){error={code,message:'SECRET'};response=await myseoulRequest(post(command),id,deps);assert.equal(response.status,code==='PT409'?409:code==='PT422'?422:code==='PT404'?404:503);assert.ok(!(await response.text()).includes('SECRET'));checks++;}
error=null;data=null;response=await myseoulRequest(new Request(url),id,deps);assert.equal(response.status,503);checks++;
for(const f of samples.fixtures){assert.deepEqual(myseoulFacts(f.item.myseoul_facts),f.item.myseoul_facts);checks++;}
console.log(`My Seoul+ synthetic server contract checks passed: ${checks}. UI/Auth/PostgREST not connected.`);
