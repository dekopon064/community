// Request/auth/RPC doubles only. No browser, production URLs or credentials.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {dismissCommand,dismissPreview,TrashStore}=await import('../app/lib/review/trash.ts');
const {trashRequest}=await import('../app/lib/review/trash-handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const episode='00000000-0000-4000-8000-000000000001',requestId='00000000-0000-4000-8000-000000000002',actor='00000000-0000-4000-8000-000000000003';
const command={action:'dismiss',episodeId:episode,version:'a'.repeat(64),requestId};
eq(dismissCommand(command),command);eq(dismissPreview({count:27,version:command.version}),{count:27,version:command.version});
for(const raw of [{...command,actor},{...command,action:'empty'},{...command,requestId:'bad'},{...command,version:'b'},{...command,extra:'x'}]){assert.throws(()=>dismissCommand(raw));checks++;}
const calls=[];
const store=new TrashStore({rpc:async(name,args)=>{calls.push({name,args});return{data:name==='admin_review_trash_dismiss_preview'?{count:27,version:command.version}:{action:args.p_action,episodeId:args.p_episode,count:args.p_action==='empty'?27:1},error:null};}});
const deps={authorize:async()=>({userId:actor}),store:()=>store};
const post=(body,origin='https://local.invalid')=>new Request('https://local.invalid/api/admin/review-trash',{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(body)});
let r=await trashRequest(post(command),deps);eq(r.status,200);eq((await r.json()).count,1);eq(calls.at(-1).args.p_actor,actor);assert.match(r.headers.get('cache-control'),/private.*no-store/);checks++;
r=await trashRequest(new Request('https://local.invalid/api/admin/review-trash?preview=dismiss'),deps);eq(r.status,200);eq((await r.json()).count,27);
r=await trashRequest(post({...command,action:'empty',episodeId:null}),deps);eq(r.status,200);eq((await r.json()).count,27);
eq((await trashRequest(post(command,'https://other.invalid'),deps)).status,403);
eq((await trashRequest(post({...command,actor}),deps)).status,422);
for(const code of ['signed_out','forbidden']) {
 let reached=false;
 const response=await trashRequest(post(command),{authorize:async()=>{throw new AdminAccessError(code);},store:()=>{reached=true;return store;}});
 eq(reached,false);eq(response.status,code==='signed_out'?401:403);
}
eq((await trashRequest(post(command),{...deps,store:()=>({dismiss:async()=>{throw Error('synthetic');}})})).status,503);
console.log(JSON.stringify({result:'pass',checks,environment:'fabricated Auth + RPC doubles'}));

