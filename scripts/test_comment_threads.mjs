import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
registerHooks({ resolve(s,c,next) { try { return next(s,c); } catch(error) { if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw error; } } });
const {commentRequest}=await import('../app/lib/comments/handler.ts');
globalThis.fetch=()=>{throw new Error('external network forbidden');};
let checks=0;const check=(v)=>{assert.ok(v);checks++;};
const A='00000000-0000-4000-8000-000000000001',ID='10000000-0000-4000-8000-000000000001',CID='20000000-0000-4000-8000-000000000001',KEY='30000000-0000-4000-8000-000000000001';
let uid=A,admin=false,adminActor=A,calls=[],result=null,sqlError=null;
const rpc=async(name,args)=>{calls.push({name,args,service:false});return {data:result,error:sqlError};};
const deps={client:async()=>({auth:{getUser:async()=>({data:{user:uid?{id:uid,email:'private@example.invalid',user_metadata:{name:'NEVER_PUBLIC'}}:null},error:null})},rpc}),admin:async()=>admin?{status:'admin',userId:adminActor}:{status:'forbidden'},authorize:async()=>{if(!admin)throw {status:'forbidden'};return {userId:adminActor};},service:()=>({rpc:async(name,args)=>{calls.push({name,args,service:true});return {data:result,error:sqlError};}})};
const post=(payload,headers={})=>new Request('http://localhost:3999/api/comments',{method:'POST',headers:{origin:'http://localhost:3999','content-type':'application/json',...headers},body:JSON.stringify(payload)});
const query=(suffix='')=>new Request(`http://localhost:3999/api/comments?id=${ID}${suffix}`);
async function run(request,status=200){const response=await commentRequest(request,deps);check(response.status===status);check(response.headers.get('cache-control').includes('no-store'));return response.json();}
function page(){return {code:uid?'00031':null,items:[{id:CID,residentCode:'99999',body:'일반 텍스트 <script>safe</script> 😀',createdAt:'2026-10-09T00:00:00.123456Z',canDelete:true,state:'live',replyCount:2,email:'NEVER_PUBLIC',user_id:A}],next:null,profile:'NEVER_PUBLIC'};}

result=page();let output=await run(query());check(calls.at(-1).name==='list_information_comment_threads');check(output.items[0].replyCount===2);check(!JSON.stringify(output).includes('NEVER_PUBLIC'));
result={count:25,owners:[A]};output=await run(query('&view=count'));check(output.count===25&&Object.keys(output).length===1);check(calls.at(-1).name==='count_information_comments');
for(const count of [0,1,100000]){result={count};check((await run(query('&view=count'))).count===count);}
for(const count of [-1,1.5,'12',null,Number.MAX_SAFE_INTEGER+1]){result={count};await run(query('&view=count'),503);}
result=page();result.items[0].replyCount=0;result.parentState='live';output=await run(query('&parentId='+CID));check(calls.at(-1).name==='list_information_comment_replies');check(calls.at(-1).args.p_parent_id===CID);check(output.items[0].state==='live');
// Reply adapter exposes ten at a time while reusing the bounded SQL page.
result=page();result.parentState='live';result.items=Array.from({length:20},(_,i)=>({...result.items[0],id:`40000000-0000-4000-8000-${String(i+1).padStart(12,'0')}`,replyCount:0}));
output=await run(query('&parentId='+CID));check(output.items.length===10);check(output.next.id===result.items[9].id);check(output.parentState==='live');
result.items=result.items.slice(10);output=await run(query('&parentId='+CID+'&at=2026-10-09T00:00:00Z&beforeId='+output.next.id));check(output.items.length===10&&output.next===null);
for(const parentState of [undefined,'unknown',0]){result=page();result.items[0].replyCount=0;result.parentState=parentState;await run(query('&parentId='+CID),503);}
for(const params of ['&view=bad','&view=count&parentId='+CID,'&requestId='+KEY+'&parentId='+CID,'&parentId=bad','&parentId='+CID+'&at=bad&beforeId='+KEY])await run(query(params),400);
result=page();result.items[0]={...result.items[0],state:'deleted',residentCode:null,body:null,canDelete:false};output=await run(query());check(output.items[0].body===null&&output.items[0].residentCode===null);check(!JSON.stringify(output).includes('NEVER_PUBLIC'));
for(const change of [{body:'hidden secret'},{residentCode:'00031'},{canDelete:true},{replyCount:0},{state:'unknown'}]){result=page();result.items[0]={...result.items[0],state:'hidden',residentCode:null,body:null,canDelete:false,...change};await run(query(),503);}
result={outcome:'accepted',commentId:CID,state:'live'};
const create={id:ID,action:'create',requestId:KEY,body:' reply 😀 ',expectedCode:'00031',parentId:CID};await run(post(create));check(calls.at(-1).name==='create_information_comment_reply');check(calls.at(-1).args.p_parent_id===CID);check(calls.at(-1).args.p_body==='reply 😀');check(!Object.values(calls.at(-1).args).includes(A));
await run(post({...create,parentId:null}),400);await run(post({...create,parentId:'bad'}),400);await run(post({...create,userId:A}),400);await run(post(create,{origin:'http://other.invalid'}),403);
uid=null;await run(post(create),401);result={count:2};check((await run(query('&view=count'))).count===2);
uid=A;sqlError={code:'PT410',message:'private diagnostic'};output=await run(post(create),409);check(output.error==='parent_unavailable');check(!JSON.stringify(output).includes('private'));
sqlError={code:'XX000'};const before=calls.length;await run(post(create),503);check(calls.length===before+1);sqlError=null;
for(const lang of ['ko','ja']){const now=JSON.parse(readFileSync(new URL(`../messages/${lang}.json`,import.meta.url)));const original=JSON.parse(execFileSync('git',['show',`HEAD:messages/${lang}.json`],{encoding:'utf8'}));delete now.Comments;delete original.Comments;assert.deepEqual(now,original);checks++;}
console.log(JSON.stringify({checks,actualHandler:true,externalNetwork:false,realUsers:false}));
