// Focused regression of independent findings M1/M2/L1/L2; no real Auth/DB.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {fakeDatabase} from './saved_test_fixture.mjs';
registerHooks({resolve(s,c,n){try{return n(s,c)}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return n(s+'.ts',c);throw e}}});
const {savedRequest}=await import('../app/lib/saved/handlers.ts');
const {publicBrowseReturnTo}=await import('../app/lib/auth/urls.ts');
const {readIntent}=await import('../app/lib/saved/intent.ts');
const f=await fakeDatabase();
let checks=0,uid=f.userA,stored=null,blocked=null,entered=null;
const check=(a,b,label)=>{assert.deepEqual(a,b,label);checks++;};
const names={save_information:['p_curation_id','p_version'],remove_saved_information:['p_curation_id'],saved_information_state:['p_curation_id'],list_saved_information:['p_locale','p_limit','p_offset'],prepare_saved_information_intent:['p_curation_id'],cancel_saved_information_intent:['p_intent_id'],resume_saved_information:['p_intent_id','p_curation_id'],cancel_saved_information_resume:['p_curation_id']};
const factory=async()=>{const owner=uid;return {auth:{getUser:async()=>({data:{user:owner?{id:owner,user_metadata:{name:'Synthetic'}}:null},error:null})},rpc:async(name,body={})=>{
 if(name==='save_information'&&blocked){entered();await blocked;}
 try{return{data:await f.rpc(name,names[name].map(k=>body[k]??null),owner,owner?'authenticated':'anon'),error:null};}catch(e){return{data:null,error:{code:e.code}};}
}};};
const store={read:()=>stored?readIntent(encodeURIComponent(JSON.stringify(stored))):null,write:v=>stored=v,clear:()=>stored=null};
const site='http://localhost:3107';
async function call(action,body={},get=false){const req=new Request(site+'/api/saved/'+action+(get?'?'+new URLSearchParams(body):''),get?{}:{method:'POST',headers:{Origin:site,'Content-Type':'application/json'},body:JSON.stringify(body)});const r=await savedRequest(req,action,factory,store);assert.match(r.headers.get('cache-control'),/private.*no-store/);return {status:r.status,data:await r.json()};}
const state=()=>call('state',{id:f.post},true);
const prepare=async(id=f.post)=> (await f.rpc('prepare_saved_information_intent',[id])).token;
async function freshSave(){const current=await state();return call('save',{id:f.post,version:current.data.version});}
try{
 for(const action of ['save','request']){
  await call('remove',{id:f.post});const before=await state();
  let release;blocked=new Promise(r=>release=r);const barrier=new Promise(r=>entered=r);
  const stale=call(action,{id:f.post,slug:'local-policy',version:before.data.version});await barrier;
  check((await call('remove',{id:f.post})).data.saved,false,'newer removal completes');blocked=null;release();
  const response=await stale;check(response.status,409,'older '+action+' rejected');check(response.data.error,'state_changed');check(response.data.saved,false);
  check((await state()).data.saved,false,'late '+action+' cannot recreate');
  check((await freshSave()).data.saved,true,'fresh save after removal');
  check((await call(action,{id:f.post,slug:'local-policy',version:response.data.version})).data.saved,true,'repeat current version idempotent');
 }
 // Capture a request version before it is delayed even ahead of authentication.
 const delayedVersion=(await state()).data.version;await call('remove',{id:f.post});
 check((await call('save',{id:f.post,version:delayedVersion})).status,409,'version already in browser protects pre-auth delays');
 check((await call('save',{id:f.post})).status,409,'old client cannot bypass version');
 check((await call('save',{id:f.post,version:'999999999999999999'})).status,409,'forged version not current');
 check((await call('save',{id:f.post,version:2})).status,409,'non-string version');
 // Separate tab and account: only the same owner/post invalidation is relevant.
 const aVersion=(await state()).data.version;uid=f.userB;await call('remove',{id:f.post});uid=f.userA;
 check((await call('save',{id:f.post,version:aVersion})).data.saved,true,'B cannot invalidate A');
 const beforeLogout=(await state()).data.version;await call('cancel',{});check((await call('save',{id:f.post,version:beforeLogout})).status,409,'account cancellation fences ordinary saves');
 check((await freshSave()).status,200,'fresh action after account cancellation');
 for(const skew of [4000,-4000]){
  const token=await prepare();await call('remove',{id:f.post});
  stored={token,id:f.post,slug:'local-policy',locale:'ko',phase:'ready',accountId:f.userA,issuedAt:Date.now()+skew};
  check(!!store.read(),true,'synthetic skew cookie accepted');
  check((await call('resume',{id:f.post,token})).status,409,'skew cannot bypass DB order');check((await state()).data.saved,false);
  const next=await prepare();stored={token:next,id:f.post,slug:'local-policy',locale:'ko',phase:'ready',accountId:f.userA,issuedAt:Date.now()+skew};
  check((await call('resume',{id:f.post,token:next})).data.saved,true,'new post-removal intent saves');
  check((await f.rpc('resume_saved_information',[next,f.post])).outcome,'consumed','duplicate not new success');
 }
 const expired=await prepare();await f.query("update machimoa_saved.intent_orders set created_at=clock_timestamp()-interval '16 minutes' where token=$1",[expired]);
 check((await f.rpc('resume_saved_information',[expired,f.post])).outcome,'expired','DB TTL');
 check((await f.rpc('resume_saved_information',[randomUUID(),f.post])).outcome,'expired','unregistered app-issued nonce rejected');
 const cancelled=await prepare();await f.rpc('cancel_saved_information_resume',[],f.userA);check((await f.rpc('resume_saved_information',[cancelled,f.post])).outcome,'cancelled');
 const otherCancel=await prepare();await f.rpc('cancel_saved_information_resume',[],f.userB);check((await f.rpc('resume_saved_information',[otherCancel,f.post],f.userA)).outcome,'saved','other account cancel isolated');
 const wrongAccount=await prepare();stored={token:wrongAccount,id:f.post,slug:'local-policy',locale:'ko',phase:'ready',accountId:f.userB,issuedAt:Date.now()};check((await call('resume',{id:f.post,token:wrongAccount})).status,409);
 const wrongId=await prepare();check((await f.rpc('resume_saved_information',[wrongId,f.program])).outcome,'expired','token bound to stable UUID');
 // Anonymous cancellation must remain durable even if an older callback restores
 // its captured cookie later. No GET/callback makes a database mutation.
 const guestCancelled=await prepare();stored={token:guestCancelled,id:f.post,slug:'local-policy',locale:'ko',phase:'pending',issuedAt:Date.now()};uid=null;
 check((await call('cancel')).data.cancelled,true,'guest cancel recorded in DB');uid=f.userA;
 check((await f.rpc('resume_saved_information',[guestCancelled,f.post])).outcome,'cancelled','captured guest nonce cannot resume after cancel');
 // Anonymous can only prepare a currently public target; not access personal state.
 check(typeof(await f.rpc('prepare_saved_information_intent',[f.post],null,'anon')).token,'string');
 for(const id of [f.hidden,f.wrong,randomUUID()]){await assert.rejects(()=>f.rpc('prepare_saved_information_intent',[id],null,'anon'),e=>e.code==='PT404');checks++;}
 for(const [name,args] of [['saved_information_state',[f.post]],['save_information',[f.post,'0']],['resume_saved_information',[wrongId,f.post]],['remove_saved_information',[f.post]]]){await assert.rejects(()=>f.rpc(name,args,null,'anon'),e=>e.code==='42501');checks++;}
 for(const [name,args] of [['save_information',[f.post]],['resume_saved_information',[wrongId,f.post,new Date().toISOString()]]]){await assert.rejects(()=>f.rpc(name,args),e=>e.code==='42501');checks++;}
 await assert.rejects(()=>f.asRole('authenticated',f.userA,tx=>tx.query('delete from machimoa_saved.information where original_curation_id=$1',[f.post])),e=>e.code==='42501');checks++;
 for(const table of ['intent_orders','resume_fences','resume_receipts']){await assert.rejects(()=>f.asRole('authenticated',f.userA,tx=>tx.query('select * from machimoa_saved.'+table)),e=>e.code==='42501');checks++;}
 // Every reviewed field, including all ECMAScript trim code points.
 const fields=['title_ko','summary_ko','content_ko','title_ja','summary_ja','content_ja'];
 const whitespace='\u0009\u000a\u000b\u000c\u000d \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff';
 for(const field of fields){
  const original=(await f.query('select '+field+' as value from public.curations where id=$1',[f.post]))[0].value;
  for(const blank of [...whitespace,'\t'.repeat(20),'\t \r\n']){
   // Exercise the gate's real composite type without weakening legacy content
   // constraints, some of which already reject a single ASCII space.
   check((await f.query('select machimoa_saved.is_savable(jsonb_populate_record(c,jsonb_build_object($1::text,$2::text))) value from public.curations c where id=$3',[field,blank,f.post]))[0].value,!!blank.trim(),'app/SQL trim agreement');
  }
  await f.query('update public.curations set '+field+'=$1 where id=$2',['\t'.repeat(20),f.post]);
  const version=(await state()).data.version;check((await call('save',{id:f.post,version})).status,404,'whitespace blocked at write');
  const list=(await call('list',{},true)).data;const item=list.items.find(v=>v.id===f.post);check(item.availability,'unavailable');check(item.information,null);
  for(const visible of ['\t 한국어 日本語 \n','\u200b','\u0085']){check((await f.query('select machimoa_saved.is_savable(jsonb_populate_record(c,jsonb_build_object($1::text,$2::text))) value from public.curations c where id=$3',[field,visible,f.post]))[0].value,!!visible.trim());}
  await f.query('update public.curations set '+field+'=$1 where id=$2',[original,f.post]);
 }
 for(const locale of ['ko','ja']){
  for(const path of ['saved','saved?offset=25','saved/','admin/review','%73aved']){
   check(publicBrowseReturnTo('/'+locale+'/'+path,locale),'/'+locale);
   const response=await savedRequest(new Request(site+'/api/saved/cancel',{method:'POST',headers:{Origin:site},body:new URLSearchParams({locale,next:'/'+locale+'/'+path})}),'cancel',factory,store);
   check(new URL(response.headers.get('location')).pathname,'/'+locale,'guest POST destination');
  }
  check(publicBrowseReturnTo('/'+locale+'/info/local-policy',locale),'/'+locale+'/info/local-policy');
  check(publicBrowseReturnTo('https://evil.invalid',locale),'/'+locale);
 }
 const login=await readFile(new URL('../app/[locale]/login/page.tsx',import.meta.url),'utf8');assert.match(login,/browseNext = publicBrowseReturnTo\(next, locale\)/);checks++;
 // Third migration rollback must preserve bookmarks and restore previous grants.
 const rows=await f.query('select * from machimoa_saved.information order by user_id,original_curation_id');
 await f.db.exec(await readFile(new URL('../supabase/rollback/20261001000300_saved_information_order_down.sql',import.meta.url),'utf8'));
 check(await f.query('select * from machimoa_saved.information order by user_id,original_curation_id'),rows,'non-destructive rollback');
 check((await f.rpc('save_information',[f.post])).saved,true,'Stage 2 function restored');
 check((await f.query("select to_regprocedure('public.save_information(uuid,text)') value"))[0].value,null);
 console.log(`PASS: ${checks} focused regression assertions for M1/M2/L1/L2; fresh memory DB and fake Auth only.`);
}finally{await f.db.close();}
