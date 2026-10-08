// Focused adapter tests only. This is a fake RPC model, not PostgreSQL verification.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
registerHooks({resolve(s,c,n){try{return n(s,c)}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return n(s+'.ts',c);throw e}}});
const {savedRequest}=await import('../app/lib/saved/handlers.ts');
const {savedCountRequest}=await import('../app/lib/saved/count.ts');
const {readIntent}=await import('../app/lib/saved/intent.ts');
const {mayCacheResponse}=await import('../app/lib/serviceWorkerCachePolicy.ts');
const origin='http://127.0.0.1:3187',A=randomUUID(),B=randomUUID();
const categories=['policy','program','event','youth_space','living'];
const rows=categories.map(category=>({id:randomUUID(),slug:'synthetic-'+category,user_category:category,is_published:true,title_ko:'합성 제목',summary_ko:'합성 요약',content_ko:'합성 내용',title_ja:'テスト',summary_ja:'テスト',content_ja:'テスト'}));
const hidden={...rows[0],id:randomUUID(),slug:'synthetic-hidden',is_published:false},bad={...rows[0],id:randomUUID(),user_category:'unknown'},missing=randomUUID();
rows.push(hidden,bad);
let uid=A,intent=null,calls=[],countError=null,countOverride=null,writeError=null;
const saved=new Set(),versions=new Map(),tokens=new Map();
const key=(owner,id)=>owner+':'+id;
const eligible=row=>row?.is_published&&categories.includes(row.user_category)&&['title_ko','summary_ko','content_ko','title_ja','summary_ja','content_ja'].every(k=>typeof row[k]==='string'&&row[k].trim());
function state(owner,id){return{id,saved:saved.has(key(owner,id)),version:String(versions.get(key(owner,id))??0)}}
async function rpc(name,args={},owner=null){calls.push({name,args,owner});
 const id=args.p_curation_id,row=rows.find(x=>x.id===id);
 if(name==='saved_information_count'){
  if(countError)return{error:{code:countError},data:null};if(countOverride)return{data:countOverride,error:null};
  return eligible(row)?{data:{id,savedCount:[...saved].filter(k=>k.endsWith(':'+id)).length},error:null}:{data:null,error:{code:'PT404'}};
 }
 if(name==='prepare_saved_information_intent'){
  if(!eligible(row))return{data:null,error:{code:'PT404'}};
  const token=randomUUID();tokens.set(token,{id,used:false,cancelled:false,expired:false});return{data:{token},error:null};
 }
 if(name==='cancel_saved_information_intent'){const token=tokens.get(args.p_intent_id);if(token)token.cancelled=true;return{data:{cancelled:true},error:null}}
 if(!owner)return{data:null,error:{code:'42501'}};
 if(name==='saved_information_state')return{data:state(owner,id),error:null};
 if(name==='list_saved_information')return{data:{items:rows.filter(row=>saved.has(key(owner,row.id))).map(row=>({id:row.id,availability:eligible(row)?'available':'unavailable',information:eligible(row)?{slug:row.slug,category:row.user_category}:null})),hasMore:false},error:null};
 if(name==='remove_saved_information'){saved.delete(key(owner,id));versions.set(key(owner,id),Number(state(owner,id).version)+1);return{data:state(owner,id),error:null}}
 if(name==='save_information'){
  if(writeError)return{data:null,error:{code:writeError}};
  if(args.p_version!==state(owner,id).version)return{data:{...state(owner,id),outcome:'stale'},error:null};
  if(!eligible(row))return{data:null,error:{code:'PT404'}};
  saved.add(key(owner,id));return{data:state(owner,id),error:null};
 }
 if(name==='resume_saved_information'){
  const t=tokens.get(args.p_intent_id);if(!t||t.id!==id||t.used||t.expired||t.cancelled)return{data:{outcome:'expired'},error:null};
  t.used=true;if(!eligible(row))return{data:{outcome:'unavailable'},error:null};saved.add(key(owner,id));return{data:{...state(owner,id),outcome:'saved'},error:null};
 }
 if(name==='cancel_saved_information_resume'){for(const row of rows)versions.set(key(owner,row.id),Number(state(owner,row.id).version)+1);return{data:{cancelled:true},error:null}}
 throw Error('Unexpected RPC '+name);
}
const factory=async()=>{const owner=uid;return{auth:{getUser:async()=>({data:{user:owner?{id:owner}:null},error:null})},rpc:(n,a)=>rpc(n,a,owner),from:()=>{let values={};return{select(){return this},eq(k,v){values[k]=v;return this},async maybeSingle(){return{data:rows.find(r=>Object.entries(values).every(([k,v])=>r[k]===v))??null,error:null}}}}}};
const store={read:()=>intent?readIntent(encodeURIComponent(JSON.stringify(intent))):null,write:x=>intent=x,clear:()=>intent=null};
const publicFactory=()=>({rpc:(n,a)=>rpc(n,a,null)});
let checks=0;const eq=(a,b,label)=>{assert.deepEqual(a,b,label);checks++};
async function call(action,body={},get=false,from=origin){const r=await savedRequest(new Request(origin+'/api/saved/'+action+(get?'?'+new URLSearchParams(body):''),get?{}:{method:'POST',headers:{Origin:from,'Content-Type':'application/json'},body:JSON.stringify(body)}),action,factory,store);assert.match(r.headers.get('cache-control'),/private.*no-store/);return{status:r.status,data:r.status>=300&&r.status<400?{}:await r.json()}}
async function count(id){const r=await savedCountRequest(new Request(origin+'/api/saved-count?id='+id),publicFactory);assert.match(r.headers.get('cache-control'),/no-store/);eq(mayCacheResponse(r),false,'aggregate must not enter SW cache');return{status:r.status,data:r.status>=300&&r.status<400?{}:await r.json()}}
for(const row of rows.slice(0,5)){
 uid=A;eq((await count(row.id)).data.savedCount,0,'zero');eq((await call('save',{id:row.id,version:'0'})).data.saved,true,row.user_category+' save');eq((await count(row.id)).data.savedCount,1);
 eq((await call('save',{id:row.id,version:'0'})).status,200,'idempotent');eq((await count(row.id)).data.savedCount,1);
 uid=B;eq((await call('state',{id:row.id},true)).data.saved,false,'account isolated');eq((await call('save',{id:row.id,version:'0'})).data.saved,true);eq((await count(row.id)).data.savedCount,2);
 uid=A;eq((await call('remove',{id:row.id})).data.saved,false);eq((await count(row.id)).data.savedCount,1);eq((await call('save',{id:row.id,version:'0'})).status,409,'stale write not refreshed');
 uid=null;eq((await call('request',{id:row.id,slug:row.slug,locale:'ja'})).status,401,'guest intent all categories');eq(intent.locale,'ja');
 uid=A;await call('continue',{id:row.id,token:intent.token});const token=intent.token;eq((await call('resume',{id:row.id,token})).data.saved,true);eq((await call('resume',{id:row.id,token})).status,409,'single resume');eq((await count(row.id)).data.savedCount,2);
}
uid=A;eq((await call('list',{locale:'ko'},true)).data.items.length,5,'all categories in personal list');uid=B;eq((await call('list',{locale:'ja'},true)).data.items.length,5);
for(const row of [hidden,bad,{id:missing,slug:'missing'}]){
 uid=null;eq((await call('request',{id:row.id,slug:row.slug})).status,404);eq((await count(row.id)).status,404);
 uid=A;eq((await call('save',{id:row.id,version:'0'})).status,404);
}
const sample=rows[2];sample.is_published=false;uid=A;const unavailable=(await call('list',{},true)).data.items.find(x=>x.id===sample.id);eq(unavailable,{id:sample.id,availability:'unavailable',information:null});eq((await count(sample.id)).status,404);eq((await call('remove',{id:sample.id})).data.saved,false,'hidden remove allowed');sample.is_published=true;
uid=null;for(const field of ['title_ko','summary_ko','content_ko','title_ja','summary_ja','content_ja']){const old=sample[field];sample[field]='\t\u3000\n';eq((await call('request',{id:sample.id,slug:sample.slug})).status,404,'JS trim gate '+field);sample[field]=old}
// Intent account binding, cancellation and expiry stay in the existing handler.
await call('request',{id:sample.id,slug:sample.slug});uid=A;await call('continue',{id:sample.id,token:intent.token});uid=B;eq((await call('resume',{id:sample.id,token:intent.token})).status,409,'wrong account');
uid=null;await call('request',{id:sample.id,slug:sample.slug});await call('cancel');eq(intent,null);
uid=null;await call('request',{id:sample.id,slug:sample.slug});uid=A;await call('continue',{id:sample.id,token:intent.token});tokens.get(intent.token).expired=true;eq((await call('resume',{id:sample.id,token:intent.token})).status,409);
const before=calls.length;eq((await call('save',{id:sample.id,version:'0',userId:B})).status,400,'owner injection');eq((await call('remove',{id:sample.id},false,'https://wrong.invalid')).status,403,'Origin');eq(calls.length,before,'invalid requests do not write');
countError='XX000';eq((await count(sample.id)).status,503,'read failure not zero');const v=(await call('state',{id:sample.id},true)).data.version;eq((await call('save',{id:sample.id,version:v})).status,200,'count failure independent');countError=null;
for(const value of [-1,1.2,'4',null,Number.MAX_SAFE_INTEGER+1]){countOverride={id:sample.id,savedCount:value};eq((await count(sample.id)).status,503,'invalid numeric result')}
countOverride={id:sample.id,savedCount:3,userId:A,email:'secret.invalid',rows:[A]};eq((await count(sample.id)).data,{id:sample.id,savedCount:3},'response whitelist');countOverride={id:missing,savedCount:3};eq((await count(sample.id)).status,503);countOverride=null;
eq((await count(sample.id.toUpperCase())).status,200,'uppercase UUID is canonicalized');
for(const q of ['id=bad','id='+sample.id+'&id='+sample.id,'id='+sample.id+'&owner='+A]){const r=await savedCountRequest(new Request(origin+'/api/saved-count?'+q),publicFactory);eq(r.status,400)}
eq((await savedCountRequest(new Request(origin+'/api/saved-count?id='+sample.id,{method:'POST'}),publicFactory)).status,405);
eq((await savedCountRequest(new Request(origin+'/api/saved-count?id='+sample.id),()=>null)).status,503);
writeError='XX000';const writesBefore=calls.filter(x=>x.name==='save_information').length;eq((await call('save',{id:sample.id,version:v})).status,503);eq(calls.filter(x=>x.name==='save_information').length,writesBefore+1,'no retry after ambiguous/error write');writeError=null;
const route=await readFile(new URL('../app/api/saved-count/route.ts',import.meta.url),'utf8');assert.doesNotMatch(route,/cookies\(|getUser|service.role|createAuthClient/);checks++;
const list=await readFile(new URL('../app/components/auth/SavedList.tsx',import.meta.url),'utf8');assert.match(list,/isUserCategory\(information\.category\)/);checks++;
for(const locale of ['ko','ja']){const data=JSON.parse(await readFile(new URL('../messages/'+locale+'.json',import.meta.url),'utf8'));for(const k of ['count','countLoading','countUnavailable','countRetry'])assert.ok(data.Saved[k]);checks++}
console.log(JSON.stringify({checks,actualSQLExecuted:false,externalRequests:0,scope:'actual handlers with fake Auth/RPC'}));
