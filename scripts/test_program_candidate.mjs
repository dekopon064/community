// Synthetic candidate/RPC/Auth only. No database, environment loading or provider.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(`${s}.ts`,c);throw e;}}});
const {databaseItem}=await import('../app/lib/review/database-dto.ts');
const {DatabaseReviewStore}=await import('../app/lib/review/database-store.ts');
const {reviewDetail}=await import('../app/lib/review/handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const id='20000000-0000-4000-8000-000000000001';
const actor='00000000-0000-4000-8000-000000000001';
const old={...await new LocalReviewStore().get('candidates',id),version:'c'.repeat(64)};
const metadata={inputFactsVersion:1,currentFactsVersion:1,inputChanged:false,canPublish:true,
 applicationPeriod:'2026-10-01 ~ 2026-10-31',operatingPeriod:'2026-11-01 ~ 2026-11-30',raw_payload:'SECRET_SENTINEL'};
const candidate={...old,source:{...old.source,name:'seoul_reservation'},version:'c'.repeat(64),programInfo:metadata,raw_payload:'SECRET_SENTINEL'};
let checks=0;const check=v=>{assert.ok(v);checks++;};
const item=databaseItem(candidate,'candidates',id);
check(item.programInfo.operatingPeriod.includes('2026-11'));
check(!JSON.stringify(item).includes('SECRET_SENTINEL'));
check(!('programInfo' in databaseItem(old,'candidates',id)));
for(const patch of [{inputFactsVersion:'1'},{currentFactsVersion:0},{inputChanged:true},{canPublish:'true'},{inputFactsVersion:0},
 {currentFactsVersion:2,inputChanged:true,canPublish:true}]) {
 assert.throws(()=>databaseItem({...candidate,programInfo:{...metadata,...patch}},'candidates',id),e=>e.code==='unavailable');checks++;
}
let calls=0;
const makeClient=(message)=>({rpc:async(name,args)=>{calls++;if(message)return{data:null,error:{message}};
 if(name==='admin_review_save_candidate'){check(args.p_actor===actor);check(!('actor' in args));}
 return{data:candidate,error:null};}});
let store=new DatabaseReviewStore(makeClient());
const deps={authorize:async()=>({userId:actor}),store:()=>store};
const get=await reviewDetail(new Request('http://localhost/api/admin/review/candidates/'+id),'candidates',id,deps);
check(get.status===200&&get.headers.get('cache-control').includes('no-store'));
check(!JSON.stringify(await get.json()).includes('SECRET_SENTINEL'));
for(const status of ['signed_out','forbidden','auth_error']) {
 const prior=calls;
 const result=await reviewDetail(new Request('http://localhost/api/admin/review/candidates/'+id),'candidates',id,
 {authorize:async()=>{throw new AdminAccessError(status);},store:()=>{throw Error('store accessed before auth');}});
 check(result.status>=400&&calls===prior);check(result.headers.get('cache-control').includes('no-store'));
}
function post(body){return new Request('http://localhost/api/admin/review/candidates/'+id,{method:'POST',headers:{origin:'http://localhost','content-type':'application/json'},body:JSON.stringify(body)});}
const command={action:'save_candidate',revision:candidate.revision,version:candidate.version,content:candidate.content};
const saved=await reviewDetail(post(command),'candidates',id,deps);check(saved.status===200);
const prior=calls;
const forged=await reviewDetail(post({...command,actor:'forged'}),'candidates',id,deps);check(forged.status===422&&calls===prior);
for(const [dbMessage,code] of [['program_candidate_input_changed','program_input_changed'],['program_candidate_unavailable','program_unavailable']]) {
 store=new DatabaseReviewStore(makeClient(dbMessage));
 const r=await reviewDetail(post({action:'publish',revision:candidate.revision,version:candidate.version}),'candidates',id,deps);
 check(r.status===409&&(await r.json()).code===code);check(r.headers.get('cache-control').includes('no-store'));
}
console.log(`Program candidate projection/authorization/transport checks passed: ${checks}. Synthetic only.`);
