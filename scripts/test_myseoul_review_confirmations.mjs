// Exact new commands, fake administrator/Auth/RPC only. No environment or network.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
const root=fileURLToPath(new URL('../',import.meta.url)),require=createRequire(import.meta.url),ts=require('typescript'),cache=new Map();
function load(name){const file=path.resolve(root,name);if(cache.has(file))return cache.get(file);const exports={};cache.set(file,exports);
 const code=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 new Function('require','exports',code)(s=>{if(s.startsWith('.')){const p=path.resolve(path.dirname(file),s);return load(path.relative(root,p+'.ts'));}return require(s);},exports);return exports;
}
const {myseoulCommand,myseoulGuidance}=load('app/lib/review/myseoul-contract.ts');
const {myseoulItem,MySeoulReviewStore}=load('app/lib/review/myseoul-store.ts');
const {myseoulRequest}=load('app/lib/review/myseoul-handlers.ts');
const {AdminAccessError}=load('app/lib/auth/admin-policy.ts');
const fixture=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_myseoul_db.py','--fixtures'],{cwd:path.join(root,'scripts'),encoding:'utf8'})).fixtures[0];
const facts=fixture.item.myseoul_facts,id='00000000-0000-4000-8000-000000000002',actor='00000000-0000-4000-8000-000000000001';
const item={id,revision:facts.source_revision,version:'b'.repeat(64),schema:facts.schema_version,profile:'myseoul-program-v1-local',factsVersion:1,source:{name:'myseoul_program',title:'합성',url:facts.official_url,body:''},facts,observedFacts:facts,result:fixture.expected,status:'open',aiStatus:'blocked',editableFields:['description','activity_region','delivery_mode'],history:[],bodyReview:{required:true,confirmed:false,imageUrl:'https://global.seoul.go.kr/contents/commoneditor/synthetic.png'},activityReview:{confirmed:false}};
const known=value=>({status:'known',value}),na={status:'not_applicable',value:null};
const data={schema:'content-filters-v1',category:'program',topic:known('culture_experience'),location:known({scope:'specific',venues:[{province:'11',district:null,facility:'',address:''}]}),delivery:known('onsite'),audience:known('other'),spaceKind:na,application:known({deadlineKind:'fixed',start:{value:'2020-01-01',precision:'day'},end:{value:'2099-10-15',precision:'day'},sourceStatus:'unknown'}),schedule:na};
const body={action:'confirm_body',revision:item.revision,version:item.version,description:'합성 이미지 원문을 확인하고 사람이 입력한 프로그램 설명입니다.',confirmed:true};
const activity={action:'confirm_activity',revision:item.revision,version:item.version,filterVersion:1,data,fields:['location'],patch:{}};
let checks=0,calls=[];
const ok=v=>{assert.ok(v);checks++;};const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
eq(myseoulCommand(body),body);eq(myseoulCommand(activity),activity);
for(const c of [{...body,confirmed:false},{...body,confirmed:undefined},{...body,description:'짧음'},{...body,actor:'forged'},{...body,description:'<img>'},{...activity,filterVersion:0},{...activity,fields:[]},{...activity,fields:['topic']},{...activity,patch:{venue:'가짜 시설'}},{...activity,patch:{activity_evidence:['가짜 인용']}},{...activity,patch:{issues:[]}},{...activity,actor:'forged'}]){assert.throws(()=>myseoulCommand(c));checks++;}
ok(!myseoulGuidance('attachment_dependent').includes('지원하지 않는'));
const parsed=myseoulItem({...item,bodyReview:{...item.bodyReview,actor:'DO_NOT_EXPOSE',history:['DO_NOT_EXPOSE']},activityReview:{confirmed:false,actor:'DO_NOT_EXPOSE'}},id);ok(!JSON.stringify(parsed).includes('DO_NOT_EXPOSE'));
const store=new MySeoulReviewStore({async rpc(name,args){calls.push({name,args});return {data:item,error:null};}});
const deps={authorize:async()=>({userId:actor}),store:()=>store};
const url=`https://example.test/api/admin/myseoul-review/${id}`;
const post=(c,origin='https://example.test')=>new Request(url,{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(c)});
for(const [c,name] of [[body,'admin_myseoul_body_confirm'],[activity,'admin_myseoul_activity_confirm']]){
 const r=await myseoulRequest(post(c),id,deps);eq(r.status,200);ok(r.headers.get('cache-control').includes('no-store'));eq(calls.at(-1).name,name);eq(calls.at(-1).args.p_actor,actor);
 if(c===activity){eq(calls.at(-1).args.p_filters,{location:data.location});eq(calls.at(-1).args.p_patch,{});}
 else eq(calls.at(-1).args.p_description,body.description);
 const before=calls.length;
 eq((await myseoulRequest(post(c,'https://evil.invalid'),id,deps)).status,403);eq(calls.length,before);
 eq((await myseoulRequest(post({...c,actor:'forged'}),id,deps)).status,422);eq(calls.length,before);
 for(const status of ['signed_out','forbidden']){eq((await myseoulRequest(post(c),id,{...deps,authorize:async()=>{throw new AdminAccessError(status);}})).status,status==='signed_out'?401:403);eq(calls.length,before);}
}
const before=calls.length;eq((await myseoulRequest(new Request(url),id,deps)).status,200);eq(calls.length,before+1);eq(calls.at(-1).name,'admin_myseoul_program_detail');
console.log(JSON.stringify({checks,result:'passed',actualProviderCalls:0,externalConnections:0}));
