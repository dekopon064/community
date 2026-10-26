import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import fs from 'node:fs';import ts from 'typescript';
import {createHmac} from 'node:crypto';
import http from 'node:http';import https from 'node:https';import net from 'node:net';
const deny=()=>{throw Error('real_network_forbidden');};globalThis.fetch=http.request=http.get=https.request=https.get=net.Socket.prototype.connect=deny;
registerHooks({resolve(specifier,context,next){try{return next(specifier,context);}catch(error){if(specifier.startsWith('.')&&!/\.[a-z]+$/i.test(specifier))return next(specifier+'.ts',context);throw error;}},
 load(url,context,next){if(url.startsWith('file:')&&url.endsWith('.json'))return{format:'module',source:'export default '+fs.readFileSync(new URL(url),'utf8'),shortCircuit:true};if(url.startsWith('file:')&&url.endsWith('.ts'))return{format:'module',source:ts.transpileModule(fs.readFileSync(new URL(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText,shortCircuit:true};return next(url,context);}});
const {workerGrantRequest}=await import('../app/lib/pc-worker/handler.ts');
const {issueWorkerGrant}=await import('../app/lib/pc-worker/grants.ts');
const {PcWorkerClient}=await import('../app/lib/pc-worker/client.ts');
const {workerCommand,workerStatus,workerGrantInput,workerCatalogId,workerCatalog,pcWorkerSchema,workerHello}=await import('../app/lib/pc-worker/contracts.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const origin='http://127.0.0.1:3295',key='synthetic-only-credential-aaaaaaaaaaaaaaaaaaaaaaaa';
const actor='00000000-0000-4000-8000-000000000001';
const hello={schema:pcWorkerSchema,instance:'10000000-0000-4000-8000-000000000001',challenge:'20000000-0000-4000-8000-000000000001',project:'a'.repeat(20),catalog:workerCatalogId};
const cmd={source:'all',kind:'ai',limit:1};let serial=2;
const id=()=>`30000000-0000-4000-8000-${String(serial++).padStart(12,'0')}`;
const input=(action='connect')=>({action,hello,requestId:id(),command:action==='connect'?null:cmd});
const req=(body,extra={})=>new Request(origin+'/api/admin/pc-worker',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json',...extra},body:typeof body==='string'?body:JSON.stringify(body)});
let passed=0;async function test(name,fn){await fn();passed++;console.log('PASS '+name);}
for(const [code,status] of [['signed_out',401],['forbidden',403],['auth_unavailable',503],['configuration_error',503]])await test('authorization before capability: '+code,async()=>{
 let issued=0;const response=await workerGrantRequest(req(input()),{authorize:async()=>{throw new AdminAccessError(code);},issue:()=>{issued++;return'bad';}});
 assert.equal(response.status,status);assert.equal(issued,0);assert.match(response.headers.get('Cache-Control'),/no-store/);
});
const deps={authorize:async()=>({userId:actor}),issue:(v,a,o)=>issueWorkerGrant(v,a,o,{project:hello.project,key},1000000)};
await test('bounded, domain-separated grant never contains the server credential',async()=>{
 const body=input('run'),response=await workerGrantRequest(req(body),deps),data=await response.json();assert.equal(response.status,200);
 const [prefix,payload,mac]=data.ticket.split('.');assert.equal(prefix,'pcw1');const claims=JSON.parse(Buffer.from(payload,'base64url'));assert.equal(claims.exp-claims.iat,60);assert.deepEqual(claims.command,cmd);assert.equal(claims.actor,actor);assert.equal(claims.origin,origin);
 const derived=createHmac('sha256',key).update('machimoa.pc-worker.capability.v1').digest();assert.equal(mac,createHmac('sha256',derived).update(payload).digest('base64url'));assert(!data.ticket.includes(key));assert(!JSON.stringify(claims).includes(key));
});
await test('wrong Origin, oversized or invalid body, extra fields and unsupported commands are rejected',async()=>{
 for(const body of ['{', 'x'.repeat(4200), {...input(),shell:'do-not-run'}, {...input('run'),command:{...cmd,source:'invented'}},{...input('run'),command:{...cmd,limit:26}},{...input('run'),command:{...cmd,kind:'publish'}},{...input('run'),command:{...cmd,kind:'collect',limit:2}}]){
  assert.equal((await workerGrantRequest(req(body),deps)).status,422);
 }
 assert.equal((await workerGrantRequest(req(input(),{Origin:'https://attacker.invalid'}),deps)).status,403);
 assert.equal((await workerGrantRequest(new Request(origin+'/api/admin/pc-worker'),deps)).status,405);
 assert.throws(()=>issueWorkerGrant(workerGrantInput(input()),actor,origin,{project:'b'.repeat(20),key}));
});
function fixture({unknown=false,denied=false,invalid=false,terminalUnknown=false}={}){
 let view,calls=[],run=null,collect=0,ai=0,completed=false;const token='synthetic_local_connection_aaaaaaaaaa';
 const transport=async(url,options={})=>{
  calls.push({url,method:options.method,body:options.body});const body=options.body?JSON.parse(options.body):null;
  if(url.startsWith('/'))return workerGrantRequest(req(body),{...deps,authorize:async()=>{if(denied&&body.action==='run')throw new AdminAccessError('signed_out');return{userId:actor};}});
  if(url.endsWith('/hello'))return Response.json(hello);
  if(url.endsWith('/connect'))return Response.json({token,instance:hello.instance});
  if(options.headers?.Authorization!==`Bearer ${token}`)throw Error('missing_local_auth');
  if(url.endsWith('/run')){
   const c=JSON.parse(Buffer.from(body.ticket.split('.')[1],'base64url'));run={requestId:c.requestId,command:c.command,state:'running',code:'',counts:{}};
   if(run.command.kind==='collect')collect++;else ai++;
   if(unknown)throw Error('response_unknown_with_secret_do_not_echo');
   if(invalid)return Response.json({unverified:true});
  }
  return Response.json({busy:!!run&&(!completed||terminalUnknown),run:run?{...run,state:completed?terminalUnknown?'unknown':'completed':'running',counts:completed&&!terminalUnknown?{completed:1}:{}}:null});
 };
 const client=new PcWorkerClient(s=>{view=s;},transport,id);
 return{client,calls,get view(){return view;},get collect(){return collect;},get ai(){return ai;},finish(){completed=true;}};
}
await test('connect and status do not execute; each source/kind uses one explicit request',async()=>{
 for(const {source,kind} of [...workerCatalog.map(row=>({source:row.id,kind:'collect'})),{source:'all',kind:'collect'},{source:'all',kind:'ai'}]){
  const f=fixture();assert.equal(f.calls.length,0);await f.client.connect();assert.equal(f.collect+f.ai,0);assert.equal(f.view.connection,'ready');
  await f.client.run({source,kind,limit:1});assert.equal(f.collect+f.ai,1);assert.equal(f.view.run.command.source,source);assert.equal(f.view.run.command.kind,kind);assert.equal(f.view.run.state,'running');
  await f.client.run({source,kind,limit:1});assert.equal(f.collect+f.ai,1);f.finish();await f.client.refresh();assert.equal(f.view.run.state,'completed');assert.equal(f.collect+f.ai,1);
 }
});
await test('concurrent clicks start once and a known collection result never starts AI',async()=>{
 const f=fixture();await f.client.connect();await Promise.all([f.client.run({...cmd,kind:'collect'}),f.client.run(cmd)]);assert.equal(f.collect,1);assert.equal(f.ai,0);
 f.finish();await f.client.refresh();assert.equal(f.ai,0);
});
await test('unknown write response blocks another run and is reconciled using reads of the exact request',async()=>{
 const f=fixture({unknown:true});await f.client.connect();await f.client.run(cmd);assert(f.view.unknown);assert(!JSON.stringify(f.view).includes('secret'));await f.client.run(cmd);assert.equal(f.ai,1);
 f.finish();await f.client.refresh();assert.equal(f.view.run.state,'completed');assert.equal(f.view.unknown,false);assert(f.calls.at(-1).url.includes('?requestId='));assert.equal(f.ai,1);
});
await test('invalid success response is not completion and cannot cause automatic retransmission',async()=>{
 const f=fixture({invalid:true});await f.client.connect();await f.client.run(cmd);assert(f.view.unknown);await f.client.run(cmd);assert.equal(f.ai,1);assert.equal(f.calls.filter(c=>c.url.endsWith('/run')).length,1);
});
await test('a confirmed unknown worker result stays blocked after reads and reconnects',async()=>{
 const f=fixture({terminalUnknown:true});await f.client.connect();await f.client.run(cmd);f.finish();await f.client.refresh();
 assert.equal(f.view.run.state,'unknown');assert.equal(f.view.unknown,true);await f.client.connect();assert.equal(f.view.unknown,true);
 await f.client.run(cmd);assert.equal(f.ai,1);assert.equal(f.calls.filter(c=>c.url.endsWith('/run')).length,1);
});
await test('expired admin session prevents the local run even with an existing connection',async()=>{
 const f=fixture({denied:true});await f.client.connect();await f.client.run(cmd);assert.equal(f.view.error,'signed_out');assert.equal(f.ai,0);assert.equal(f.view.unknown,false);
});
await test('status projection rejects unsafe values instead of displaying raw data',()=>{
 for(const data of [{busy:true,run:{}},{busy:1,run:null},{busy:false,run:{requestId:id(),command:cmd,state:'completed',code:'',counts:{key:'secret'}}}])assert.throws(()=>workerStatus(data));
 assert.throws(()=>workerCommand({...cmd,filename:'arbitrary.py'}));
 assert.throws(()=>workerCommand({...cmd,source:['seoul_reservation']}));
});
await test('one catalog drives collection selection, all scope and matching PC versions',()=>{
 assert.deepEqual(workerCatalog,JSON.parse(fs.readFileSync(new URL('../app/lib/pc-worker/sources.json',import.meta.url),'utf8')));
 for(const row of workerCatalog){assert.equal(workerCommand({source:row.id,kind:'collect',limit:1}).source,row.id);assert.throws(()=>workerCommand({...cmd,source:row.id}));}
 assert.equal(workerCommand({...cmd,kind:'collect'}).source,'all');assert.throws(()=>workerHello({...hello,catalog:'older_catalog'}));
 assert.throws(()=>workerStatus({busy:false,run:{requestId:id(),command:cmd,state:'completed',code:'',counts:{},sourceResults:[{source:'unregistered',state:'completed',code:'',counts:{}}]}}));
});
await test('default browser fetch is called without the client object as its receiver',async()=>{
 const original=globalThis.fetch;let calls=0,view;
 globalThis.fetch=async function(){assert.equal(this,undefined);calls++;return Response.json(hello);};
 try{const client=new PcWorkerClient(next=>{view=next;});await client.connect();assert(calls>0);assert.equal(view.connection,'off');}
 finally{globalThis.fetch=original;}
});
await test('all AI scope is explicit and signed; numeric bounds and collection bounds remain',async()=>{
 const body={...input('run'),command:{...cmd,limit:'all'}};
 const response=await workerGrantRequest(req(body),deps);assert.equal(response.status,200);
 const ticket=(await response.json()).ticket;assert.equal(JSON.parse(Buffer.from(ticket.split('.')[1],'base64url')).command.limit,'all');
 for(const limit of ['ALL','25','',0,-1,26,true,null])assert.throws(()=>workerCommand({...cmd,limit}));
 assert.throws(()=>workerCommand({source:'all',kind:'collect',limit:'all'}));
 const f=fixture({unknown:true});await f.client.connect();await f.client.run({...cmd,limit:'all'});await f.client.run({...cmd,limit:'all'});
 assert.equal(f.ai,1);assert.equal(f.view.unknown,true);f.finish();await f.client.refresh();assert.equal(f.view.run.command.limit,'all');assert.equal(f.ai,1);
});
console.log(JSON.stringify({passed,real_auth:0,real_ai:0,db:0,external_network:0}));
