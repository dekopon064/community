import assert from 'node:assert/strict';
import fs from 'node:fs';import ts from 'typescript';import {registerHooks,syncBuiltinESMExports} from 'node:module';
import {randomUUID} from 'node:crypto';import http from 'node:http';import https from 'node:https';import net from 'node:net';
const deny=()=>{throw Error('external_network_forbidden');};globalThis.fetch=http.request=http.get=https.request=https.get=net.Socket.prototype.connect=deny;syncBuiltinESMExports();
registerHooks({resolve(s,c,next){if(s==='server-only')return{url:'data:text/javascript,export{}',shortCircuit:true};try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}},load(url,c,next){if(url.startsWith('file:')&&url.endsWith('.ts'))return{format:'module',source:ts.transpileModule(fs.readFileSync(new URL(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText,shortCircuit:true};return next(url,c);}});
const {livingHandler}=await import('../app/lib/living/handler.ts');
const {LocalLivingStore,DatabaseLivingStore}=await import('../app/lib/living/store.ts');
const {livingCommand,livingDocument,livingArticle,emptyLivingDocument,livingBody}=await import('../app/lib/living/contract.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const example=JSON.parse(fs.readFileSync(new URL('./fixtures/living-instagram-example.json',import.meta.url),'utf8'));
const actor='00000000-0000-4000-8000-000000000001',origin='http://127.0.0.1:3298';let passed=0;
async function test(name,fn){await fn();passed++;console.log('PASS '+name);}
const req=(body,headers={})=>new Request(origin+'/api/admin/living',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json',...headers},body:JSON.stringify(body)});
const command=(id=randomUUID(),document=example)=>({id,version:'0',requestId:randomUUID(),action:'save',document:structuredClone(document)});
const store=new LocalLivingStore(),deps={authorize:async()=>({userId:actor}),store:()=>store};
for(const [status,httpCode]of [['signed_out',401],['forbidden',403],['auth_unavailable',503],['configuration_error',503]])await test('real admin guard contract '+status,async()=>{
 let reads=0;const denied=await livingHandler(req(command()),{authorize:async()=>{throw new AdminAccessError(status);},store:()=>{reads++;return store;}});assert.equal(denied.status,httpCode);assert.equal(reads,0);assert.match(denied.headers.get('cache-control'),/no-store/);
});
await test('Origin, method, malformed JSON, size and client actor fail closed',async()=>{
 for(const r of [req(command(),{Origin:'https://attacker.invalid'}),req({...command(),actor:'forged'}),req(command(),{'Content-Type':'text/plain'}),new Request(origin+'/api/admin/living',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:'bad'}),req({...command(),padding:'x'.repeat(2*1024*1024)})])assert.ok((await livingHandler(r,deps)).status>=400);
 assert.equal((await livingHandler(new Request(origin+'/api/admin/living',{method:'DELETE'}),deps)).status,405);
 assert.equal((await store.list(0)).length,0);
});
await test('partial bilingual drafts can be saved privately and cannot publish',async()=>{
 const c=command(randomUUID(),emptyLivingDocument());c.document.content.titleJa='外国人登録の準備';
 const item=await store.write(livingCommand(c),actor);assert.equal(item.status,'draft');assert.equal(store.publications.size,0);
 await assert.rejects(store.write({...c,version:item.version,requestId:randomUUID(),action:'publish',document:null},actor),e=>e.code==='invalid_input');
 assert.equal((await store.get(c.id)).version,item.version);
});
const c=command();let item;
await test('original editor values, conditions, references and date persist exactly',async()=>{
 const response=await livingHandler(req(c),deps);assert.equal(response.status,200);const data=await response.json();item=livingArticle(data.item);
 assert.deepEqual(item.document,example);assert.equal(item.status,'draft');assert.equal(item.history[0].actor,actor);assert.equal(store.publications.size,0);
 assert.deepEqual(await store.get(c.id),item);
});
await test('request deduplication and stale request protect current version',async()=>{
 assert.deepEqual(await store.write(c,actor),item);assert.equal(item.history.length,1);
 await assert.rejects(store.write(c,'00000000-0000-4000-8000-000000000002'),e=>e.code==='conflict');
 await assert.rejects(store.write({...c,requestId:randomUUID()},actor),e=>e.code==='conflict');
 const saved=await store.write({...c,version:item.version,requestId:randomUUID(),document:{...example,checkedOn:'2026-10-23'}},actor);
 await assert.rejects(store.write(c,actor),e=>e.code==='conflict');item=saved;
});
await test('only a saved complete snapshot can publish; no body injection at publish',async()=>{
 assert.throws(()=>livingCommand({...c,version:item.version,action:'publish',document:example}),e=>e.code==='invalid_input');
 const publish={...c,version:item.version,requestId:randomUUID(),action:'publish',document:null};
 const response=await livingHandler(req(publish),deps);assert.equal(response.status,200);item=(await response.json()).item;
 assert.equal(item.status,'published');assert.equal(store.publications.size,1);
 const publicItem=store.publications.get(c.id);assert.equal(publicItem.user_category,'living');
 assert.equal(publicItem.content_ko,livingBody(item.document,'ko'));assert.equal(publicItem.content_ja,livingBody(item.document,'ja'));
 assert.match(publicItem.content_ja,/予約だけでは申請したことになりません/);assert.match(publicItem.content_ko,/별도 확인/);
 assert.deepEqual(await store.write(publish,actor),item);assert.equal(store.publications.size,1);
 await assert.rejects(store.write({...publish,requestId:randomUUID(),version:item.version},actor),e=>e.code==='already_processed');
 await assert.rejects(store.write({...c,requestId:randomUUID(),version:item.version},actor),e=>e.code==='already_processed');
});
await test('bounded list excludes article body and GET never changes history',async()=>{
 const before=structuredClone(item),list=await store.list(0);assert.equal(Object.keys(list[0]).sort().join(','),'id,status,title');
 assert.equal((await livingHandler(new Request(origin+'/api/admin/living?id='+c.id),deps)).status,200);
 assert.deepEqual(await store.get(c.id),before);
 for(const query of ['id=bad','offset=-1','offset=9999999'])assert.equal((await livingHandler(new Request(origin+'/api/admin/living?'+query),deps)).status,422);
});
await test('unsafe URL, invalid date, schema injection, length and missing values rejected',async()=>{
 for(const [field,value]of [['imageUrl','http://127.0.0.1/a.png'],['imageUrl','https://a.example.org/a.svg'],['referenceUrl','javascript:alert(1)'],['referenceUrl','https://user:pass@official.example.org/'],['referenceUrl','https://a.local/a'],['checkedOn','2026-02-30']])assert.throws(()=>livingDocument({...example,[field]:value}));
 assert.throws(()=>livingDocument({...example,extra:'forbidden'}));assert.throws(()=>livingDocument({...example,content:{...example.content,titleKo:'x'.repeat(301)}}));
 assert.throws(()=>livingCommand({...c,requestId:'not-an-id'}));assert.throws(()=>livingArticle({...item,raw:'secret',version:'bad'}));
});
await test('RPC wrapper sends only verified actor and bounded formal contract',async()=>{
 const calls=[],client={rpc:async(name,args)=>{calls.push({name,args});return{data:name==='admin_living_read'&&args.p_id===null?await store.list(0):item,error:null};}};
 const database=new DatabaseLivingStore(client);assert.equal((await database.list(0)).length,2);assert.deepEqual(await database.get(c.id),item);
 await database.write({...c,version:item.version},actor);assert.equal(calls.at(-1).args.p_actor,actor);assert.equal(calls.at(-1).name,'admin_living_write');
 assert.deepEqual(Object.keys(calls.at(-1).args).sort(),['p_action','p_actor','p_document','p_id','p_request_id','p_version']);
});
await test('unknown write response performs one RPC only, with no retry or AI',async()=>{
 let calls=0;const database=new DatabaseLivingStore({rpc:async()=>{calls++;throw Error('private-secret-never-expose');}});
 const response=await livingHandler(req(command()),{...deps,store:()=>database});assert.equal(response.status,503);assert.equal(calls,1);assert.equal(JSON.stringify(await response.json()).includes('private-secret'),false);
});
await test('public projection trims edges while preserving drafts and rejects appended footer overflow atomically',async()=>{
 const isolated=new LocalLivingStore(),padded={...example,content:Object.fromEntries(Object.entries(example.content).map(([k,v])=>[k,'  '+v+'  ']))};
 const cmd=command(randomUUID(),padded),saved=await isolated.write(cmd,actor);
 const published=await isolated.write({...cmd,version:saved.version,requestId:randomUUID(),action:'publish',document:null},actor);
 assert.deepEqual(published.document,padded);assert.equal(isolated.publications.get(cmd.id).title_ko,example.content.titleKo);
 assert.equal(isolated.publications.get(cmd.id).content_ko,livingBody(example,'ko'));
 const large=command(randomUUID(),{...example,content:{...example.content,contentKo:'x'.repeat(200000)}}),draft=await isolated.write(large,actor);
 await assert.rejects(isolated.write({...large,version:draft.version,requestId:randomUUID(),action:'publish',document:null},actor),e=>e.code==='invalid_input');
 assert.deepEqual(await isolated.get(large.id),draft);assert.equal(isolated.publications.has(large.id),false);
});
console.log(JSON.stringify({passed,real_auth:0,operational_db:0,ai:0,real_publications:0}));
