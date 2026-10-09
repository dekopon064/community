import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
registerHooks({ resolve(s,c,next) { try { return next(s,c); } catch(error) { if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw error; } } });
const {commentRequest}=await import('../app/lib/comments/handler.ts');
const {validComment,normalizeComment,commentPage}=await import('../app/lib/comments/contracts.ts');
globalThis.fetch=()=>{throw new Error('external network forbidden');};
let checks=0;const check=(v)=>{assert.ok(v);checks++;};
const A='00000000-0000-4000-8000-000000000001',ID='10000000-0000-4000-8000-000000000001',CID='20000000-0000-4000-8000-000000000001',KEY='30000000-0000-4000-8000-000000000001';
let uid=A,admin=false,adminActor=A,calls=[],result=null,sqlError=null;
const rpc=async(name,args)=>{calls.push({name,args,service:false});return {data:result,error:sqlError};};
const deps={client:async()=>({auth:{getUser:async()=>({data:{user:uid?{id:uid,email:'private@example.invalid',user_metadata:{name:'NEVER_PUBLIC'}}:null},error:null})},rpc}),admin:async()=>admin?{status:'admin',userId:adminActor}:{status:'forbidden'},authorize:async()=>{if(!admin)throw {status:'forbidden'};return {userId:adminActor};},service:()=>({rpc:async(name,args)=>{calls.push({name,args,service:true});return {data:result,error:sqlError};}})};
const post=(payload,headers={})=>new Request('http://localhost:3999/api/comments',{method:'POST',headers:{origin:'http://localhost:3999','content-type':'application/json',...headers},body:JSON.stringify(payload)});
const query=(suffix='')=>new Request(`http://localhost:3999/api/comments?id=${ID}${suffix}`);
async function run(request,status=200){const response=await commentRequest(request,deps);check(response.status===status);check(response.headers.get('cache-control').includes('no-store'));return response.json();}
function page(){return {code:uid?'00031':null,items:[{id:CID,residentCode:'99999',body:'일반 텍스트 <script>safe</script> 😀',createdAt:'2026-10-09T00:00:00.123456Z',canDelete:true,email:'NEVER_PUBLIC',user_id:A}],next:null,profile:'NEVER_PUBLIC'};}
for(const input of ['hello','😀'.repeat(1000),'\r\n 日本語 \r\n'])check(validComment(input));
for(const input of [' ','😀'.repeat(1001),'a\u0001','a\u000b','\ud800',null,[]])check(!validComment(input));
check(normalizeComment('\r\n a\rb \r\n')==='a\nb');
result=page();let output=await run(query());check(!JSON.stringify(output).includes('NEVER_PUBLIC'));check(!JSON.stringify(output).includes(A));check(output.viewer.code==='00031');
check(calls.at(-1).name==='list_information_comments');check(calls.at(-1).args.p_before_at===null);
uid=null;result=page();output=await run(query());check(!output.items[0].canDelete&&!output.viewer.signedIn&&output.viewer.code===null);
for(const action of ['prepare','create','remove','hide']){const before=calls.length;await run(post({id:ID,action,...(action==='create'?{requestId:KEY,body:'text',expectedCode:'00031'}:{}),...(['remove','hide'].includes(action)?{commentId:CID}:{})}),401);check(calls.length===before);}
await run(query(`&requestId=${KEY}`),401);
uid=A;
for(const request of [post({id:ID,action:'prepare'},{origin:'http://other.invalid'}),post({id:ID,action:'prepare'},{origin:''})])await run(request,403);
for(const request of [query('&id='+ID),query('&actor='+A),query('&at=broken&beforeId='+CID),post({id:ID,action:'prepare',userId:A}),post({id:ID,action:'create',requestId:KEY,body:' ',expectedCode:'00031'}),post({id:ID,action:'create',requestId:KEY,body:'valid',expectedCode:'O0I1L9'}),post({id:ID,action:'prepare'},{'content-type':'text/plain'})])await run(request,400);
await run(post({id:ID,action:'create',requestId:KEY,body:'x'.repeat(9000),expectedCode:'00031'}),413);
for(const action of ['toString','constructor','__proto__'])await run(post({id:ID,action}),400);
result={code:'00031',private:A};output=await run(post({id:ID,action:'prepare'}));check(Object.keys(output).join()==='code');check(calls.at(-1).name==='prepare_comment_resident');
result={outcome:'accepted',commentId:CID,state:'live',body:'private'};
output=await run(post({id:ID,action:'create',requestId:KEY,body:'\r\n hello 😀 \r\n',expectedCode:'00031'}));check(output.outcome==='accepted');check(calls.at(-1).args.p_body==='hello 😀');check(calls.at(-1).args.p_expected_code==='00031');check(!Object.values(calls.at(-1).args).includes(A));
for(const state of ['live','deleted','hidden']){result={outcome:'accepted',commentId:CID,state};check((await run(query('&requestId='+KEY))).state===state);}
result={outcome:'absent'};check((await run(query('&requestId='+KEY))).outcome==='absent');
result={outcome:'deleted'};await run(post({id:ID,action:'remove',commentId:CID}));check(calls.at(-1).name==='remove_information_comment');
await run(post({id:ID,action:'hide',commentId:CID}),403);
admin=true;adminActor='00000000-0000-4000-8000-000000000002';await run(post({id:ID,action:'hide',commentId:CID}),403);
adminActor=A;result={outcome:'hidden',hidden_by:'NEVER_PUBLIC'};output=await run(post({id:ID,action:'hide',commentId:CID}));check(output.outcome==='hidden'&&!JSON.stringify(output).includes('NEVER_PUBLIC'));check(calls.at(-1).service&&calls.at(-1).args.p_actor===A);
for(const [code,status] of [['PT404',404],['PT401',401],['PT403',403],['PT409',409],['PT428',409],['PT429',429],['22023',400],['XX000',503]]){sqlError={code,message:'NEVER_PUBLIC'};const before=calls.length;output=await run(post({id:ID,action:'create',requestId:KEY,body:'valid',expectedCode:'00031'}),status);check(calls.length===before+1);check(!JSON.stringify(output).includes('NEVER_PUBLIC'));}
sqlError=null;result={outcome:'accepted',commentId:CID,state:'wrong'};await run(post({id:ID,action:'create',requestId:KEY,body:'valid',expectedCode:'00031'}),503);
for(const bad of [null,{...page(),code:A},{...page(),items:[...page().items,...page().items]},{...page(),next:{at:'bad',id:CID}},{...page(),items:[{...page().items[0],body:null}]}]){assert.throws(()=>commentPage(bad,true,false));checks++;}
for(const locale of ['ko','ja']){const now=JSON.parse(readFileSync(new URL(`../messages/${locale}.json`,import.meta.url)));const original=JSON.parse(execFileSync('git',['show',`HEAD:messages/${locale}.json`],{encoding:'utf8'}));delete now.Comments;delete original.Comments;assert.deepEqual(now,original);checks++;}
const component=readFileSync(new URL('../app/components/ContentComments.tsx',import.meta.url),'utf8');check(!component.includes('dangerouslySetInnerHTML'));check(component.includes('setPending(value)')&&component.includes('resolveSubmission'));check(component.includes('crypto.randomUUID()'));
console.log(JSON.stringify({checks,externalNetworkAttempts:0,realUsers:false,productionAccess:false}));
