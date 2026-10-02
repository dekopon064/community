// All Auth, OAuth and DB traffic is local fake infrastructure. No .env is read.
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { createServer } from 'node:http';
import { createHmac, randomUUID } from 'node:crypto';
import { createServerClient } from '@supabase/ssr';
import { fakeDatabase } from './saved_test_fixture.mjs';
import {readFile} from 'node:fs/promises';
registerHooks({resolve(s,c,n){try{return n(s,c)}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return n(`${s}.ts`,c);throw e}}});
const {savedRequest}=await import('../app/lib/saved/handlers.ts');
const {startWithSave,finishWithSave,logoutWithSave}=await import('../app/lib/saved/auth-flow.ts');
const {readIntent,matchesIntent}=await import('../app/lib/saved/intent.ts');
const {profileResponse,displayName}=await import('../app/lib/auth/profile.ts');
const {isPrivateApiRequest,mayCacheResponse}=await import('../app/lib/serviceWorkerCachePolicy.ts');
const fixture=await fakeDatabase(),{db,query,rpc,asRole,userA,userB,post,program,hidden,wrong}=fixture;
const key='local-fake-publishable-key',secret='local-fake-only-not-production';
const users=new Map([[userA,{id:userA,email:'local-a@example.invalid',aud:'authenticated',role:'authenticated',user_metadata:{full_name:'로컬 테스트 사용자 이름이 매우 깁니다'},app_metadata:{provider:'google'},created_at:new Date().toISOString()}],[userB,{id:userB,email:'local-b@example.invalid',aud:'authenticated',role:'authenticated',user_metadata:{name:'ローカル利用者'},app_metadata:{provider:'kakao'},created_at:new Date().toISOString()}]]);
const sign=id=>{const parts=[{alg:'HS256',typ:'JWT'},{sub:id,aud:'authenticated',role:'authenticated',iat:Math.floor(Date.now()/1000),exp:Math.floor(Date.now()/1000)+3600}].map(v=>Buffer.from(JSON.stringify(v)).toString('base64url'));return parts.join('.')+'.'+createHmac('sha256',secret).update(parts.join('.')).digest('base64url')};
const revoked=new Set();
function verified(raw){try{const [h,p,s]=raw.split('.');const v=JSON.parse(Buffer.from(p,'base64url'));return !revoked.has(raw)&&s===createHmac('sha256',secret).update(`${h}.${p}`).digest('base64url')&&v.exp>Date.now()/1000&&users.has(v.sub)?v.sub:null}catch{return null}}
let failRead=false,failSave=false,failProfile=false,failLogout=false,delayMs=0,nextConflict=null;
const save=async(id,uid=userA)=>rpc('save_information',[id,(await rpc('saved_information_state',[id],uid)).version],uid);
const prepare=async(id)=> (await rpc('prepare_saved_information_intent',[id])).token;
const names={save_information:['p_curation_id','p_version'],remove_saved_information:['p_curation_id'],saved_information_state:['p_curation_id'],list_saved_information:['p_locale','p_limit','p_offset'],resume_saved_information:['p_intent_id','p_curation_id'],prepare_saved_information_intent:['p_curation_id'],cancel_saved_information_intent:['p_intent_id'],cancel_saved_information_resume:['p_curation_id']};
const server=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');res.setHeader('Content-Type','application/json');let raw='';for await(const c of req)raw+=c;
 const send=(value,status=200)=>{res.statusCode=status;res.end(JSON.stringify(value))};
 const bearer=req.headers.authorization?.replace(/^Bearer /,''),uid=verified(bearer);
 try {
  // Preview controls exist only in --serve on loopback and mutate this new memory DB.
  if(process.argv.includes('--serve')&&url.pathname==='/__local_test'&&req.method==='POST'){
   const body=JSON.parse(raw||'{}');nextConflict=['removed','saved'].includes(body.conflict)?body.conflict:null;failRead=body.read===true;failSave=body.save===true;failProfile=body.profile===true;failLogout=body.logout===true;delayMs=body.delay===true?900:0;
   if(body.name==='none')users.get(userA).user_metadata={};
   if(body.name==='long')users.get(userA).user_metadata={full_name:'로컬 테스트 사용자 이름이 매우 깁니다'};
   if(body.seedUnavailable){await query('update public.curations set is_published=true where id=$1',[hidden]);await save(hidden,userA);await query('update public.curations set is_published=false where id=$1',[hidden]);}
   return send({localFakeOnly:true});
  }
  if(delayMs)await new Promise(r=>setTimeout(r,delayMs));
  if(url.pathname==='/auth/v1/token'){
   const body=JSON.parse(raw),id=body.auth_code==='local-b'?userB:body.auth_code==='local-a'?userA:body.refresh_token?.startsWith('fake-')?body.refresh_token.slice(5):null;
   if(!users.has(id))return send({code:'bad_code',msg:'Local test failure'},400);
   const token=sign(id);revoked.delete(token);return send({access_token:token,refresh_token:`fake-${id}`,token_type:'bearer',expires_in:3600,user:users.get(id)});
  }
  if(url.pathname==='/auth/v1/user')return failProfile?send({msg:'Local unavailable'},503):uid?send(users.get(uid)):send({code:'bad_jwt',msg:'Local token rejected'},401);
  if(url.pathname==='/auth/v1/logout'){if(failLogout)return send({msg:'Local logout failure'},503);if(bearer)revoked.add(bearer);return send({});}
  if(url.pathname==='/auth/v1/authorize'){
   const cb=new URL(url.searchParams.get('redirect_to'));if(!['localhost','127.0.0.1'].includes(cb.hostname))return send({},400);
   if(process.argv.includes('--serve')){
    res.setHeader('Content-Type','text/html; charset=utf-8');const link=(label,params)=>{const c=new URL(cb);for(const [k,v]of Object.entries(params))c.searchParams.set(k,v);return `<p><a href="${c.href.replaceAll('&','&amp;')}">${label}</a></p>`};
    return res.end('<main><h1>로컬 가짜 인증 · 실제 로그인 아님</h1>'+link('가짜 계정 A',{code:'local-a'})+link('가짜 계정 B',{code:'local-b'})+link('취소',{error:'access_denied'})+link('실패',{code:'bad'})+'</main>');
   }
   cb.searchParams.set('code','local-a');res.writeHead(302,{Location:cb.href});return res.end();
  }
  if(url.pathname==='/rest/v1/curations'){
   if(failRead)return send({code:'XX000',message:'Local read failure'},503);
   let sql='select * from public.curations where true',args=[];
   for(const field of ['id','slug','is_published']){const value=url.searchParams.get(field);if(value?.startsWith('eq.')){args.push(field==='is_published'?value.slice(3)==='true':value.slice(3));sql+=` and ${field}=$${args.length}`}}
   const rows=await asRole(uid?'authenticated':'anon',uid,async tx=>(await tx.query(sql,args)).rows);
   if(req.headers.accept?.includes('vnd.pgrst.object'))return rows.length===1?send(rows[0]):send({code:'PGRST116'},406);
   return send(rows);
  }
  const name=url.pathname.replace('/rest/v1/rpc/','');
  if(names[name]){
   if(!uid&&!['prepare_saved_information_intent','cancel_saved_information_intent'].includes(name))return send({code:'42501'},401);
   if(failRead&&name==='list_saved_information')return send({code:'XX000'},503);
   if(failSave&&['save_information','resume_saved_information'].includes(name))return send({code:'XX000'},503);
   const body=JSON.parse(raw||'{}');
   if(process.argv.includes('--serve')&&name==='save_information'&&nextConflict){
    const conflict=nextConflict;nextConflict=null;await rpc('remove_saved_information',[body.p_curation_id],uid);
    if(conflict==='saved')await save(body.p_curation_id,uid);
   }
   return send(await rpc(name,names[name].map(k=>body[k]??null),uid,uid?'authenticated':'anon'));
  }
  return send({},404);
 }catch(e){console.error('Local fake request failure:',e.code,e.message);send({code:e.code??'XX000',message:'Local test database request failed'},e.code==='PT404'?404:400)}
});
await new Promise(r=>server.listen(process.argv.includes('--serve')?54339:0,'127.0.0.1',r));
const backend=`http://127.0.0.1:${server.address().port}`;
if(process.argv.includes('--serve'))console.log(`LOCAL FAKE Auth + NEW memory DB: ${backend}; policy=${post}; program=${program}`);
else {
 let checks=0;const equal=(a,b)=>{assert.deepEqual(a,b);checks++};
 const site='http://localhost:3107',jar=new Map();let stored=null;
 const store={read:()=>stored?readIntent(encodeURIComponent(JSON.stringify(stored))):null,write:i=>{stored=i},clear:()=>{stored=null}};
 const factory=async()=>createServerClient(backend,key,{cookieOptions:{httpOnly:true,sameSite:'lax'},cookies:{getAll:()=>[...jar].map(([name,value])=>({name,value})),setAll:values=>{for(const {name,value,options}of values){if(options.maxAge===0)jar.delete(name);else jar.set(name,value)}}}});
 const request=(action,body={},origin=site)=>new Request(site+'/api/saved/'+action,{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify(body)});
 const call=async(action,body={})=>{
  // Synthetic client captures the version before a deliberate new save action.
  if(['save','request'].includes(action)&&body.version===undefined){const state=await savedRequest(new Request(site+'/api/saved/state?id='+body.id),'state',factory,store);if(state.ok)body={...body,version:(await state.json()).version};}
  const r=await savedRequest(request(action,body),action,factory,store);assert.match(r.headers.get('cache-control'),/private.*no-store/);return [r.status,await r.json()]};
 const read=async(action,query='')=>{const r=await savedRequest(new Request(site+'/api/saved/'+action+query),action,factory,store);assert.match(r.headers.get('cache-control'),/private.*no-store/);return [r.status,await r.json()]};
 const loginPost=token=>new Request(site+'/api/auth/start',{method:'POST',headers:{Origin:site},body:new URLSearchParams({locale:'ko',next:'/ko/info/local-policy',provider:'google',...(token?{saveIntent:token}:{})})});
 async function authenticate(id=userA,token){const start=await startWithSave(loginPost(token),factory,store);const cb=new URL(new URL(start.headers.get('location')).searchParams.get('redirect_to'));cb.searchParams.set('code',id===userA?'local-a':'local-b');return finishWithSave(new Request(cb),factory,store)}
 const count=async id=>(await query('select count(*)::int n from machimoa_saved.information where user_id=$1',[id]))[0].n;
 try {
  equal((await profileResponse(await factory(),false)).status,200);equal((await (await profileResponse(await factory(),false)).json()).status,'signed_out');
  equal(displayName({email:'a@example.invalid',user_metadata:{name:'a@example.invalid'}}),null);equal(displayName({user_metadata:{name:'\u0000  이름  '}}),'이름');equal(displayName({user_metadata:{}}),null);
  equal((await profileResponse(null,true)).status,503);
  for(const path of ['/api/auth/session','/api/saved/list','/api/saved/resume','/api/admin/review'])equal(isPrivateApiRequest(new URL(site+path),true,backend),true);
  for(const name of Object.keys(names))equal(isPrivateApiRequest(new URL(backend+'/rest/v1/rpc/'+name),false,backend),true);
  equal(mayCacheResponse(new Response('{}',{headers:{'Cache-Control':'private, no-store','Content-Type':'application/json'}})),false);
  equal((await call('save',{id:post}))[0],401);equal((await read('list'))[0],401);
  equal((await savedRequest(request('save',{id:post},'https://evil.invalid'),'save',factory,store)).status,403);
  equal((await call('save',{id:post,user_id:userB}))[0],400);
  for(const id of [hidden,wrong,randomUUID()])equal((await call('request',{id,slug:id===hidden?'local-private':id===wrong?'local-event':'absent'}))[0],404);
  let result=await call('request',{id:post,slug:'local-policy',locale:'ja'});equal(result[0],401);assert.ok(result[1].loginUrl.startsWith('/ja/login'));checks++;
  // General login clears an unrelated pending save and never performs a saved RPC.
  await authenticate();equal(stored,null);equal(await count(userA),0);
  const profile=await (await profileResponse(await factory(),true)).json();equal(profile.displayName,users.get(userA).user_metadata.full_name);equal(profile.accountId,userA);
  // Another tab may have completed login while a save-purpose page was open.
  stored={token:randomUUID(),id:post,slug:'local-policy',locale:'ko',issuedAt:Date.now(),phase:'pending'};
  let continuation=await savedRequest(request('continue',{id:post,token:stored.token}),'continue',factory,store);equal(continuation.status,303);equal(stored.phase,'ready');equal(await count(userA),0);store.clear();
  await logoutWithSave(new Request(site+'/api/auth/logout',{method:'POST',headers:{Origin:site},body:new URLSearchParams({locale:'ko',next:'/ko'})}),factory,store);equal(jar.size,0);equal(stored,null);
  result=await call('request',{id:post,slug:'local-policy',locale:'ko'});const pending={...stored};assert.ok(matchesIntent(pending,pending.token,'/ko/info/local-policy'));checks++;
  let start=await startWithSave(loginPost(pending.token),factory,store);let cb=new URL(new URL(start.headers.get('location')).searchParams.get('redirect_to'));equal(cb.searchParams.get('saveIntent'),pending.token);
  cb.searchParams.set('error','access_denied');let returned=await finishWithSave(new Request(cb),factory,store);assert.match(returned.headers.get('location'),/notice=cancelled/);checks++;equal(stored,null);equal(await count(userA),0);
  await call('request',{id:post,slug:'local-policy'});let failureToken=stored.token;start=await startWithSave(loginPost(failureToken),factory,store);cb=new URL(new URL(start.headers.get('location')).searchParams.get('redirect_to'));cb.searchParams.set('code','bad');returned=await finishWithSave(new Request(cb),factory,store);assert.match(returned.headers.get('location'),/notice=failed/);checks++;equal(stored,null);
  await call('request',{id:post,slug:'local-policy'});const resumeToken=stored.token;returned=await authenticate(userA,resumeToken);equal(await count(userA),0);equal(stored.phase,'ready');assert.ok(returned.headers.get('location').includes('saveIntent'));checks++;
  const ready={...stored};result=await call('resume',{id:post,token:resumeToken});equal(result[0],200);equal(result[1].saved,true);equal(stored,null);equal(await count(userA),1);
  equal((await call('resume',{id:post,token:resumeToken}))[0],409);equal(await count(userA),1);
  // Replay captured cookies, including after an explicit unsave.
  stored={...ready};equal((await call('resume',{id:post,token:resumeToken}))[0],409);
  equal((await call('remove',{id:post}))[1].saved,false);stored={...ready};equal((await call('resume',{id:post,token:resumeToken}))[0],409);equal(await count(userA),0);
  equal((await call('save',{id:post}))[0],200);equal((await call('save',{id:post}))[0],200);equal(await count(userA),1);
  equal((await read('state',`?id=${post}`))[1].saved,true);
  // Expired / future / wrong-account requests cannot mutate.
  equal(readIntent(encodeURIComponent(JSON.stringify({...ready,issuedAt:Date.now()-900001}))),null);
  equal(readIntent(encodeURIComponent(JSON.stringify({...ready,issuedAt:Date.now()+10000}))),null);
  equal((await rpc('resume_saved_information',[randomUUID(),program])).outcome,'expired');
  stored={...ready,token:randomUUID(),accountId:userB};equal((await call('resume',{id:post,token:stored.token}))[0],409);
  // Login completed, but saving unavailable: no success, deliberate retry works.
  await call('remove',{id:post});stored={...ready,token:await prepare(post),issuedAt:Date.now()};failSave=true;equal((await call('resume',{id:post,token:stored.token}))[0],503);equal(stored,null);equal(await count(userA),0);failSave=false;equal((await call('save',{id:post}))[0],200);
  // A SQL write error rolls back the save but consumes the token durably.
  await query('delete from machimoa_saved.information where user_id=$1 and original_curation_id=$2',[userA,program]);
  await db.exec("create function machimoa_saved.fail_insert() returns trigger language plpgsql as $$ begin raise exception 'local injected failure'; end $$; create trigger fake_write_failure after insert on machimoa_saved.information for each row execute function machimoa_saved.fail_insert();");
  const failed= await prepare(program);equal((await rpc('resume_saved_information',[failed,program])).outcome,'failed');equal((await rpc('saved_information_state',[program])).saved,false);
  await db.exec('drop trigger fake_write_failure on machimoa_saved.information; drop function machimoa_saved.fail_insert()');equal((await rpc('resume_saved_information',[failed,program])).outcome,'consumed');
  // Two accounts: same stable post, separate rows, no caller-supplied ownership.
  await logoutWithSave(new Request(site+'/api/auth/logout',{method:'POST',headers:{Origin:site},body:new URLSearchParams()}),factory,store);await authenticate(userB);
  equal((await read('state',`?id=${post}`))[1].saved,false);equal((await read('list'))[1].items,[]);equal((await call('save',{id:post}))[0],200);equal(await count(userA),1);equal(await count(userB),1);equal((await call('remove',{id:post}))[0],200);equal(await count(userA),1);
  // List faults remain errors, not an empty list or unavailable content.
  failRead=true;equal((await read('list'))[0],503);failRead=false;
  await call('save',{id:program});await query('update public.curations set is_published=false where id=$1',[program]);let list=(await read('list'))[1];equal(list.items[0].availability,'unavailable');equal(list.items[0].information,null);equal((await call('remove',{id:program}))[0],200);
  await save(post,userA);await query('delete from public.curations where id=$1',[post]);list=await rpc('list_saved_information',['ko',25,0],userA);equal(list.items[0].information,null);equal((await rpc('remove_saved_information',[post],userA)).saved,false);
  // Raw ledger writes and anonymous calls stay forbidden.
  for(const name of ['resume_receipts','resume_fences']){await assert.rejects(()=>asRole('authenticated',userA,tx=>tx.query(`select * from machimoa_saved.${name}`)),e=>e.code==='42501');checks++;}
  await assert.rejects(()=>rpc('resume_saved_information',[randomUUID(),program],userA,'anon'),e=>e.code==='42501');checks++;
  await query('update public.curations set is_published=true where id=$1',[program]);const stale=await prepare(program);await rpc('cancel_saved_information_resume',[],userB);equal((await rpc('resume_saved_information',[stale,program],userB)).outcome,'cancelled');
  const beforeRemove=await prepare(program);await rpc('remove_saved_information',[program],userA);equal((await rpc('resume_saved_information',[beforeRemove,program],userA)).outcome,'cancelled');
  const unavailable=await prepare(program);await query('update public.curations set is_published=false where id=$1',[program]);equal((await rpc('resume_saved_information',[unavailable,program],userA)).outcome,'unavailable');
  // Forged browser user data / JWT never supplies display identity or authority.
  const savedJar=new Map(jar);jar.clear();jar.set('sb-127-auth-token','base64-'+Buffer.from(JSON.stringify({access_token:'bad.token.signature',user:{id:userA,user_metadata:{name:'FORGED NAME'}},expires_at:9999999999})).toString('base64url'));
  const forged=await (await profileResponse(await factory(),true)).json();equal(forged.displayName,null);assert.notEqual(forged.status,'signed_in');checks++;jar.clear();for(const pair of savedJar)jar.set(...pair);
  await logoutWithSave(new Request(site+'/api/auth/logout',{method:'POST',headers:{Origin:site},body:new URLSearchParams()}),factory,store);equal(jar.size,0);equal((await read('list'))[0],401);equal((await (await profileResponse(await factory(),true)).json()).status,'expired');
  const rows=await query('select * from machimoa_saved.information');
  await db.exec(await readFile(new URL('../supabase/rollback/20261001000300_saved_information_order_down.sql',import.meta.url),'utf8'));
  equal(await query('select * from machimoa_saved.information'),rows);
  await db.exec(await readFile(new URL('../supabase/rollback/20261001000200_saved_information_resume_down.sql',import.meta.url),'utf8'));
  equal(await query('select * from machimoa_saved.information'),rows);
  equal((await query("select to_regprocedure('public.resume_saved_information(uuid,uuid,timestamptz)') p"))[0].p,null);
  equal((await rpc('remove_saved_information',[program],userB)).saved,false);
  console.log(`PASS: ${checks} saved-flow assertions; fake Auth + actual SQL in NEW memory PostgreSQL. No real OAuth or shared DB.`);
 }finally {await new Promise(r=>server.close(r));await db.close();}
}
