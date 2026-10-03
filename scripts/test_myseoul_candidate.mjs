// New My projection/status/authorization only. Synthetic RPC, no database/provider.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(`${s}.ts`,c);throw e;}}});
const {databaseItem}=await import('../app/lib/review/database-dto.ts');
const {myseoulItem}=await import('../app/lib/review/myseoul-store.ts');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {DatabaseReviewStore}=await import('../app/lib/review/database-store.ts');
const {reviewDetail}=await import('../app/lib/review/handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const python=process.env.MACHIMOA_TEST_PYTHON;if(!python)throw Error('Explicit test Python required');
const packet=JSON.parse(execFileSync(python,['-X','utf8','test_myseoul_ai.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
const id='20000000-0000-4000-8000-000000000001',actor='00000000-0000-4000-8000-000000000001';
const base=await new LocalReviewStore().get('candidates',id);
const metadata={inputFactsVersion:1,currentFactsVersion:2,inputChanged:true,canPublish:false,applicationPeriod:'2026-10-01 ~ 2026-10-31',operatingPeriod:'2026-11-01 ~ 2026-11-30'};
const candidate={...base,source:{...base.source,name:'myseoul_program'},version:'c'.repeat(64),programInfo:metadata,raw_payload:'SECRET_SENTINEL'};
let checks=0;const ok=v=>{assert.ok(v);checks++;};
const projected=databaseItem(candidate,'candidates',id);ok(projected.programInfo.inputChanged);ok(!projected.programInfo.canPublish);ok(!JSON.stringify(projected).includes('SECRET_SENTINEL'));
assert.throws(()=>databaseItem({...candidate,programInfo:{...metadata,canPublish:true}},'candidates',id));checks++;
const c=packet.contexts[0];
const detail={id,revision:c.revision,version:'a'.repeat(64),schema:c.schema,profile:c.profile,factsVersion:c.factsVersion,source:{name:c.source,title:c.title,url:c.facts.official_url,body:c.facts.description},facts:c.facts,observedFacts:c.observedFacts,result:{decision:'in_scope',disposition:'target',scope:'included',application:'open',quality:'sufficient',public_category:'program',reasons:[]},status:'resolved',editableFields:[],history:[]};
for(const aiStatus of ['blocked','queued','claimed','completed','failed','cancelled'])ok(myseoulItem({...detail,aiStatus},id).aiStatus===aiStatus);
assert.throws(()=>myseoulItem({...detail,aiStatus:'published'},id));checks++;
let calls=0;
const store=new DatabaseReviewStore({rpc:async(name,args)=>{calls++;if(name==='admin_review_save_candidate')ok(args.p_actor===actor);return{data:candidate,error:null};}});
const post=new Request('http://localhost/api/admin/review/candidates/'+id,{method:'POST',headers:{origin:'http://localhost','content-type':'application/json'},body:JSON.stringify({action:'save_candidate',revision:candidate.revision,version:candidate.version,content:candidate.content})});
const response=await reviewDetail(post,'candidates',id,{authorize:async()=>({userId:actor}),store:()=>store});ok(response.status===200);ok(response.headers.get('cache-control').includes('no-store'));
for(const code of ['signed_out','forbidden']){
 const before=calls;const r=await reviewDetail(new Request('http://localhost/api/admin/review/candidates/'+id),'candidates',id,{authorize:async()=>{throw new AdminAccessError(code);},store:()=>{throw Error('DB before auth');}});ok(r.status>=400&&calls===before);
}
console.log(JSON.stringify({checks,scope:'My candidate projection, AI state, guarded candidate save',mode:'synthetic'}));
