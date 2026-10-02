// Injected requests/identities and RPC doubles only; no network/provider/config files.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {trashCommand,trashList,TrashStore}=await import('../app/lib/review/trash.ts');
const {trashRequest}=await import('../app/lib/review/trash-handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {DatabaseReviewStore}=await import('../app/lib/review/database-store.ts');
const {ProgramReviewStore}=await import('../app/lib/review/program-store.ts');
const {validateCommand}=await import('../app/lib/review/validation.ts');
const {programCommand}=await import('../app/lib/review/program-contract.ts');
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const id='00000000-0000-4000-8000-000000000001',episode='00000000-0000-4000-8000-000000000002',requestId='00000000-0000-4000-8000-000000000003';
const command={action:'exclude',id,revision:'a'.repeat(64),version:'b'.repeat(64),reasonCode:'service_not_suitable',note:'',requestId};
const row={id:episode,sourceItemId:id,revision:command.revision,version:command.version,sourceName:'youthcenter_policy',title:'합성 정책',reasonCode:'service_not_suitable',note:'서비스에 적합하지 않음',excludedAt:'2026-10-02T00:00:00Z',expiresAt:'2026-10-05T00:00:00Z',canRestore:true,blockReason:null};
const list={serverNow:'2026-10-02T01:00:00Z',items:[row]};
eq(trashCommand(command),command);eq(trashCommand({...command,reasonCode:'custom',note:' 사유 '}),{...command,reasonCode:'custom',note:'사유'});
for(const invalid of [{...command,id:'bad'},{...command,requestId:''},{...command,reasonCode:'arbitrary'},{...command,note:'manual injection'},{...command,actor:id},{...command,action:'delete'},{...command,reasonCode:'custom',note:''},{...command,version:'bad'}]){assert.throws(()=>trashCommand(invalid));checks++;}
eq(trashList({...list,private:'DO_NOT_ECHO'}),list);
for(const invalid of [{...list,serverNow:'bad'},{...list,items:Array(26).fill(row)},{...list,items:[{...row,canRestore:false}]},{...list,items:[{...row,expiresAt:'2026-10-05T01:00:00Z'}]},{...list,items:[{...row,blockReason:'RAW_ERROR'}]}]){assert.throws(()=>trashList(invalid));checks++;}
const calls=[];const store={list:async()=>list,execute:async(c,actor)=>{calls.push({c,actor});return {episodeId:episode,expiresAt:row.expiresAt,item:{status:'excluded'}};}};
const deps={authorize:async()=>({userId:id}),store:()=>store};
const url='https://machimoa.example/api/admin/review-trash';
const req=body=>new Request(url,{method:'POST',headers:{Origin:'https://machimoa.example','Content-Type':'application/json'},body:JSON.stringify(body)});
for(const [status,expected] of [['signed_out',401],['forbidden',403]]){
 const response=await trashRequest(req(command),{authorize:async()=>{throw new AdminAccessError(status);},store:()=>{throw Error('must not construct store');}});eq(response.status,expected);eq(/private.*no-store/.test(response.headers.get('cache-control')),true);
}
let response=await trashRequest(req(command),deps);eq(response.status,200);eq(calls[0].actor,id);eq(/private.*no-store/.test(response.headers.get('cache-control')),true);
response=await trashRequest(new Request(url),deps);eq((await response.json()).items.length,1);
response=await trashRequest(new Request(url+'?offset=-1'),deps);eq(response.status,422);
response=await trashRequest(new Request(url,{method:'POST',headers:{Origin:'https://evil.example','Content-Type':'application/json'},body:JSON.stringify(command)}),deps);eq(response.status,403);
response=await trashRequest(new Request(url,{method:'POST',headers:{Origin:'https://machimoa.example','Content-Type':'text/plain'},body:'{}'}),deps);eq(response.status,422);
response=await trashRequest(new Request(url,{method:'POST',headers:{Origin:'https://machimoa.example','Content-Type':'application/json'},body:'x'.repeat(20001)}),deps);eq(response.status,422);
response=await trashRequest(req({...command,actor:requestId}),deps);eq(response.status,422);eq(calls.length,1);
const errorCodes={trash_expired:'trash_expired',trash_source_changed:'trash_source_changed',trash_processing_active:'trash_processing_active',trash_already_published:'trash_already_published',RAW_SECRET:'unavailable'};
for(const [message,code] of Object.entries(errorCodes)){
 const bad=new TrashStore({rpc:async()=>({data:null,error:{message}})});
 const r=await trashRequest(new Request(url),{...deps,store:()=>bad});eq((await r.json()).code,code);eq(/private.*no-store/.test(r.headers.get('cache-control')),true);
}
const base=await new LocalReviewStore().get('facts','10000000-0000-4000-8000-000000000001');
const projected={...base,id,revision:command.revision,version:command.version,editableFields:[],excludeAllowed:true,restoredReviewPending:true};
const factCmd=validateCommand('facts',{action:'save_facts',revision:command.revision,version:command.version,facts:projected.facts,confirmRestored:true});eq(factCmd.confirmRestored,true);
const names=[];const dbStore=new DatabaseReviewStore({rpc:async(name,args)=>{names.push(name);eq(args.p_actor,id);return {data:projected,error:null};}});
eq((await dbStore.execute('facts',id,factCmd,id)).restoredReviewPending,true);eq(names,['admin_review_save_restored']);
const empty={action:'save_facts',revision:command.revision,version:command.version,note:'복구 후 사실 재확인',patch:{},resolve:[],confirmRestored:true};
eq(programCommand(empty),empty);assert.throws(()=>programCommand({...empty,confirmRestored:undefined}));checks++;
assert.throws(()=>validateCommand('facts',{...factCmd,confirmRestored:false}));checks++;
console.log(JSON.stringify({result:'pass',checks,environment:'fabricated Auth/request/RPC doubles only'}));
