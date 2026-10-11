// Synthetic records and injected RPC only. No Auth/DB/provider network.
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {DatabaseReviewStore}=await import('../app/lib/review/database-store.ts');
const {reviewDetail,listReviews}=await import('../app/lib/review/handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {publishedBodyCommand,canEditPublishedBody}=await import('../app/lib/review/published-body.ts');
const {databaseItem}=await import('../app/lib/review/database-dto.ts');
globalThis.fetch=()=>{throw Error('NETWORK_FORBIDDEN');};
const id='20000000-0000-4000-8000-000000000001', actor='00000000-0000-4000-8000-000000000001',origin='http://127.0.0.1:3250';
let checks=0;
function eq(a,b){assert.deepEqual(a,b);checks++;}
const store=new LocalReviewStore(), deps={authorize:async()=>({userId:actor}),store:()=>store};
const pending=await store.get('candidates',id);
eq(canEditPublishedBody(pending),false);
const published=await store.execute('candidates',id,{action:'publish',revision:pending.revision,version:pending.version},actor);
eq((await store.list('candidates',0,'published')).map(x=>x.id),[id]);
eq((await store.list('candidates')).length,0);
eq(canEditPublishedBody(published),true);
eq(canEditPublishedBody({...published,publishedBodyVersion:undefined}),false);
eq(canEditPublishedBody({...published,programInfo:{inputChanged:true}}),false);
const command=publishedBodyCommand(published,published.content.contentKo+'\n\n**합성 비용: 무료**',published.content.contentJa+'\n\n**合成費用：無料**','중복 목록 정리');
const req=(body,headers={})=>new Request(`${origin}/api/admin/review/candidates/${id}?status=published`,{method:'POST',headers:{Origin:origin,'Content-Type':'application/json',...headers},body:JSON.stringify(body)});
async function post(body,d=deps,headers={}){const r=await reviewDetail(req(body,headers),'candidates',id,d);assert.match(r.headers.get('Cache-Control'),/private.*no-store/);return {status:r.status,data:await r.json()};}
for(const [status,http] of [['signed_out',401],['forbidden',403],['auth_unavailable',503]]){
 let touches=0;const denied={authorize:async()=>{throw new AdminAccessError(status);},store:()=>{touches++;return store;}};
 eq((await post(command,denied)).status,http);
 eq((await listReviews(new Request(origin+'/api/admin/review?kind=candidates&status=published'),denied)).status,http);eq(touches,0);
}
eq((await post(command,deps,{Origin:'https://attacker.invalid'})).status,403);
for(const extras of [{actor:'FORGED'},{titleKo:'changed'},{imageSelection:{mode:'none',url:null}},{filters:{}},{content:{}}])eq((await post({...command,...extras})).status,422);
eq((await post({...command,note:''})).status,422);
eq((await post({...command,contentKo:''})).status,422);
eq((await post({...command,publicVersion:'stale'})).status,422);
eq((await post({...command,publicVersion:'b'.repeat(64)})).status,409);
eq((await post({...command,contentKo:published.content.contentKo,contentJa:published.content.contentJa})).status,422);
const concurrent=await Promise.all([post(command),post(command)]);
eq(concurrent.map(x=>x.status).sort(),[200,409]);
const saved=await store.get('candidates',id,'published');
eq(saved.publishedAt,published.publishedAt);eq(saved.publishedId,published.publishedId);eq(saved.status,'published');eq(saved.source,published.source);
eq(saved.content.titleKo,published.content.titleKo);eq(saved.content.summaryJa,published.content.summaryJa);
eq(saved.history.length,published.history.length+1);eq(saved.history.at(-1).actor,actor);eq(saved.history.at(-1).changeLabel,'공개 본문 수정');
assert.notEqual(saved.version,published.version);assert.notEqual(saved.publishedBodyVersion,published.publishedBodyVersion);checks+=2;
eq((await post(command)).status,409);
eq((await listReviews(new Request(origin+'/api/admin/review?kind=facts&status=published'),deps)).status,422);
eq((await listReviews(new Request(origin+'/api/admin/review?kind=candidates&status=rejected'),deps)).status,422);
const dto={...saved,version:'c'.repeat(64)};
const calls=[];let fail=null;
const db=new DatabaseReviewStore({rpc:async(name,args)=>{calls.push({name,args});return {data:name.endsWith('_list')?[]:dto,error:fail};}});
await db.list('candidates',25,'published');eq(calls.at(-1),{name:'admin_review_published_list',args:{p_offset:25,p_limit:25}});
await db.get('candidates',id,'published');eq(calls.at(-1),{name:'admin_review_published_detail',args:{p_id:id}});
await db.execute('candidates',id,command,actor);eq(calls.at(-1).name,'admin_review_save_published_body');
eq(calls.at(-1).args,{p_id:id,p_revision:command.revision,p_version:command.version,p_public_version:command.publicVersion,p_body:{contentKo:command.contentKo,contentJa:command.contentJa},p_note:command.note,p_actor:actor});
for(const [message,code] of [['review_conflict','conflict'],['review_already_processed','already_processed'],['program_candidate_unavailable','program_unavailable'],['classification_candidate_input_changed','program_input_changed'],['classification_processing_active','conflict'],['unknown','unavailable']]){
 fail={message};const before=calls.length;await assert.rejects(db.execute('candidates',id,command,actor),e=>e.code===code);eq(calls.length-before,1);
}
const history={...dto,history:[{action:'save_candidate',actor,at:new Date().toISOString(),note:'test',fields:['published_body_edit']}]};
eq(databaseItem(history,'candidates',id).history[0].changeLabel,'공개 본문 수정');
assert.throws(()=>databaseItem({...dto,status:'pending'},'candidates',id));checks++;
console.log(`Published body edit: ${checks} assertions passed; synthetic Auth/store/RPC, 0 network/DB/AI calls.`);
