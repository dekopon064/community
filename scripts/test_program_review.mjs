// Test doubles only: no environment secrets, actual Auth or network/Production DB.
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
registerHooks({resolve(specifier,context,next) {
  try {return next(specifier,context);}catch(e){if(specifier.startsWith('.')&&!/\.[a-z]+$/i.test(specifier))return next(`${specifier}.ts`,context);throw e;}
}});
const {programCommand,programFacts}=await import('../app/lib/review/program-contract.ts');
const {ProgramReviewStore,programItem}=await import('../app/lib/review/program-store.ts');
const {programRequest}=await import('../app/lib/review/program-handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {mayCacheResponse}=await import('../app/lib/serviceWorkerCachePolicy.ts');
const fixture=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_program_db.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
const id='00000000-0000-4000-8000-000000000002',actor='00000000-0000-4000-8000-000000000001';
const facts=fixture.fixtures[0].item.program_facts;
const item={id,revision:'a'.repeat(64),version:'b'.repeat(64),schema:'program-scope-v1-local',profile:'program_capital_v1_local',factsVersion:1,
  source:{name:'seoul_reservation',title:'합성 프로그램',url:facts.official_url,body:'비실행 일반 텍스트'},facts,observedFacts:facts,
  result:{decision:'review_required',disposition:'observe_only',reasons:['activity_location_unknown']},status:'open',aiStatus:'blocked',editableFields:['activity_region'],history:[],raw_payload:'DO_NOT_ECHO'};
const command={action:'save_facts',revision:item.revision,version:item.version,note:'공식 근거 확인',patch:{activity_region:'capital',activity_evidence:['서울 개최 확인']},resolve:['activity_location_unknown']};
let checks=0,calls=[];let error=null;let malformed=false;
const store=new ProgramReviewStore({async rpc(name,args){calls.push({name,args});return {data:malformed?{raw_payload:'DO_NOT_ECHO'}:name==='admin_program_list'?[{id,title:'합성 프로그램',reasons:[],raw_payload:'DO_NOT_ECHO'}]:item,error};}});
assert.equal(JSON.stringify(programItem(item,id)).includes('DO_NOT_ECHO'),false);checks++;
assert.ok(programItem(item,id).reasonGuidance[0].text.includes('실제 개최지'));checks++;
for(const bad of [{...item,factsVersion:{raw_payload:'DO_NOT_ECHO'}},{...item,editableFields:['constructor']}]){
  assert.throws(()=>programItem(bad,id),e=>e.code==='unavailable');checks++;
}
assert.deepEqual(programFacts({...facts,raw_payload:'DO_NOT_ECHO'}),facts);checks++;
for(const body of [{...command,actor:'forged'},{...command,patch:{missing:[]}},{...command,patch:{activity_region:'bogus'}},{...command,note:''},{...command,patch:{constructor:'bad'}},{...command,patch:{official_url:'https://evil.invalid/'}}]){
  assert.throws(()=>programCommand(body),e=>e.code==='invalid_input');checks++;
}
const auth=async()=>({userId:actor});let selected=0;
const deps={authorize:auth,store:()=>{selected++;return store;}};
const url=`https://example.test/api/admin/program-review/${id}`;
const post=(body,origin='https://example.test')=>new Request(url,{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(body)});
for(const status of ['signed_out','forbidden','auth_error','configuration_error']){
  const authorize=async()=>{throw new AdminAccessError(status);};const count=calls.length,before=selected;
  for(const request of [new Request(url),post(command)]){
    const response=await programRequest(request,id,{...deps,authorize});assert.equal(response.status,status==='signed_out'?401:status==='forbidden'?403:503);
    assert.ok(response.headers.get('cache-control').includes('no-store'));checks++;
  }
  assert.equal(calls.length,count);assert.equal(selected,before);checks++;
}
let response=await programRequest(new Request(url),id,deps);assert.equal(response.status,200);assert.ok(response.headers.get('cache-control').includes('no-store'));
assert.equal(mayCacheResponse(response),false);checks++;
response=await programRequest(post(command),id,deps);assert.equal(response.status,200);assert.equal(calls.at(-1).args.p_actor,actor);assert.deepEqual(calls.at(-1).args.p_patch,command.patch);checks++;
let before=calls.length;
for(const request of [post(command,'https://evil.invalid'),post({...command,actor:'forged'}),post({...command,note:'x'.repeat(200001)})]){
  response=await programRequest(request,id,deps);assert.ok([403,422].includes(response.status));assert.equal(calls.length,before);checks++;
}
response=await programRequest(new Request('https://example.test/api/admin/program-review?offset=25'),null,deps);
assert.equal(response.status,200);assert.deepEqual(calls.at(-1).args,{p_offset:25,p_limit:25});assert.equal((await response.text()).includes('DO_NOT_ECHO'),false);checks++;
for(const code of ['PT409','PT422','PT404','XX000']){
  error={code,message:'DO_NOT_ECHO_SECRET_URL'};response=await programRequest(post(command),id,deps);
  assert.equal(response.status,code==='PT409'?409:code==='PT422'?422:code==='PT404'?404:503);assert.equal((await response.text()).includes('DO_NOT_ECHO'),false);checks++;
}
error=null;malformed=true;response=await programRequest(new Request(url),id,deps);assert.equal(response.status,503);checks++;
console.log(`Program server/DTO/auth double checks passed: ${checks}. No real DB or Auth.`);
