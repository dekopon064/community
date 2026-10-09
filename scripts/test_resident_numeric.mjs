import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
registerHooks({ resolve(s,c,next) { try { return next(s,c); } catch(error) { if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw error; } } });
const { RESIDENT_CODE, EXPECTED_RESIDENT_CODE, commentPage } = await import('../app/lib/comments/contracts.ts');
const { commentRequest } = await import('../app/lib/comments/handler.ts');
globalThis.fetch = () => { throw Error('external network forbidden'); };
let checks=0;const check=value=>{assert.ok(value);checks++;};
const account='00000000-0000-4000-8000-000000000001',id='10000000-0000-4000-8000-000000000001',commentId='20000000-0000-4000-8000-000000000001',requestId='30000000-0000-4000-8000-000000000001';
let result, error=null, calls=[];
const dependencies={client:async()=>({auth:{getUser:async()=>({data:{user:{id:account}},error:null})},rpc:async(name,args)=>{calls.push({name,args});return {data:result,error};}}),admin:async()=>({status:'forbidden'}),authorize:async()=>{throw Error('not used');},service:()=>{throw Error('not used');}};
const post=payload=>new Request('http://localhost:3999/api/comments',{method:'POST',headers:{origin:'http://localhost:3999','content-type':'application/json'},body:JSON.stringify({id,...payload})});
const page=code=>({code,items:[{id:commentId,residentCode:code,body:'合成 😀',createdAt:'2026-10-09T00:00:00Z',canDelete:true}],next:null});
async function run(request,status=200){const response=await commentRequest(request,dependencies);check(response.status===status);check(response.headers.get('cache-control').includes('no-store'));return response.json();}
for(const code of ['00000','00031','99999']){
  check(RESIDENT_CODE.test(code));check(EXPECTED_RESIDENT_CODE.test(code));
  const dto=commentPage(page(code),true,false);check(dto.viewer.code===code&&dto.items[0].residentCode===code);
  result={code};check((await run(post({action:'prepare'}))).code===code);
  result={outcome:'accepted',commentId,state:'live'};await run(post({action:'create',requestId,body:'合成 😀',expectedCode:code}));
  check(calls.at(-1).args.p_expected_code===code);check(!Object.values(calls.at(-1).args).includes(account));
}
for(const code of ['1234','123456','ABCDE','abcde','１２３４５',' 00031','00031 ','00031\n','00031\r\n','00031\t','A7K2Q9']){
  check(!RESIDENT_CODE.test(code));assert.throws(()=>commentPage(page(code),true,false));checks++;
  result={code};await run(post({action:'prepare'}),503);
}
for(const code of [31,null,{},['00031']]){
  assert.throws(()=>commentPage(page(code),true,false));checks++;
  result={code};await run(post({action:'prepare'}),503);
}
for(const code of ['1234','ABCDE','abcde','１２３４５',' 00031','00031\n','A7K2Q9\n',31,null]){
  const before=calls.length;await run(post({action:'create',requestId,body:'draft retained',expectedCode:code}),400);check(calls.length===before);
}
// A former valid six-character code is only a compatibility input. SQL still
// checks the current resident: one request, identity fence, no automatic rewrite.
for(const code of ['A7K2Q9','234567']){
  check(EXPECTED_RESIDENT_CODE.test(code));error={code:'PT428'};const before=calls.length;
  const answer=await run(post({action:'create',requestId,body:'draft retained',expectedCode:code}),409);
  check(answer.error==='identity_changed');check(calls.length===before+1);check(calls.at(-1).args.p_expected_code===code);
}
error=null;result={outcome:'accepted',commentId,state:'live'};
check((await run(new Request(`http://localhost:3999/api/comments?id=${id}&requestId=${requestId}`))).outcome==='accepted');
check(calls.at(-1).name==='information_comment_request_state');check(!('p_expected_code' in calls.at(-1).args));
console.log(JSON.stringify({checks,actualAdapter:true,realNetwork:false,productionAccess:false}));
