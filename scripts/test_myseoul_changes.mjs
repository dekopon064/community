// New change-review boundary tests / explicit loopback UI fixture. No real DB/auth.
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { createServer } from 'node:http';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(`${s}.ts`,c);throw e;}}});
const { LocalReviewStore } = await import('../app/lib/review/local-fixture.ts');
const { DatabaseReviewStore } = await import('../app/lib/review/database-store.ts');
const { databaseItem } = await import('../app/lib/review/database-dto.ts');
const { validateCommand } = await import('../app/lib/review/validation.ts');
const { reviewDetail } = await import('../app/lib/review/handlers.ts');
const { AdminAccessError } = await import('../app/lib/auth/admin-policy.ts');
const { myseoulReasonFields } = await import('../app/lib/review/myseoul-contract.ts');
const actor='00000000-0000-4000-8000-000000000001',id='20000000-0000-4000-8000-000000000001';
const item={...await new LocalReviewStore().get('candidates',id),source:{name:'myseoul_program',title:'원문 변경 확인 (합성 시험)',body:'새로운 프로그램 설명 — 합성 자료입니다.',url:'https://example.invalid/source'},revision:'a'.repeat(64),version:'b'.repeat(64),category:'program',
 programInfo:{inputFactsVersion:1,currentFactsVersion:1,inputChanged:true,canPublish:false,changeReviewed:false,changedFields:['설명','실제 회차·시간'],comparisonAvailable:true,applicationPeriod:'2099-10-01 ~ 2099-10-31',operatingPeriod:'2099-11-01 ~ 2099-11-30'}};
if(process.argv.includes('--serve')){
 const published={...structuredClone(item),id:'20000000-0000-4000-8000-000000000002',status:'published',publishedId:'50000000-0000-4000-8000-000000000001',publishedAt:'2026-10-01T00:00:00Z',source:{...item.source,title:'公開済み 원문 변경 (합성 시험)'}};
 const items=new Map([item,published].map(v=>[v.id,v]));
 createServer(async(req,res)=>{
  try{
   const chunks=[];for await(const c of req)chunks.push(c);const body=Buffer.concat(chunks);
   if(!req.url.startsWith('/rest/v1/rpc/admin_')){
    const up=await fetch(`http://127.0.0.1:54329${req.url}`,{method:req.method,headers:{'content-type':'application/json',authorization:req.headers.authorization??''},...(req.method==='GET'?{}:{body}),redirect:'manual'});
    res.writeHead(up.status,Object.fromEntries(up.headers));res.end(Buffer.from(await up.arrayBuffer()));return;
   }
   const args=JSON.parse(body.toString()),name=req.url.split('/').at(-1);let data,error;
   if(name==='admin_review_list')data=args.p_kind==='candidates'?[...items.values()].map(v=>({id:v.id,title:v.source.title,sourceName:v.source.name,status:v.status,reasons:[]})):[];
   else if(name==='admin_review_ai_waiting_list')data=[];
   else if(name==='admin_review_detail')data=items.get(args.p_id);
   else if(name==='admin_myseoul_review_change'){
    const old=items.get(args.p_id);
    if(!old||args.p_actor!==actor)error='review_invalid_input';
    else if(args.p_note==='실패 시험')error='local_connection_failure';
    else if(args.p_note==='충돌 시험'||args.p_version!==old.version)error='review_conflict';
    else{await new Promise(r=>setTimeout(r,500));data=structuredClone(old);if(args.p_content)data.content=args.p_content;data.version='c'.repeat(64);data.programInfo.changeReviewed=true;data.programInfo.canPublish=false;data.history.unshift({action:'save_candidate',actor,at:new Date().toISOString(),note:args.p_note,fields:['source_change_review:'+args.p_disposition,'source_change_stage:'+data.status]});items.set(data.id,data);}
   }else error='review_invalid_input';
   res.setHeader('content-type','application/json');res.setHeader('cache-control','no-store');if(error){res.statusCode=error==='review_conflict'?409:503;res.end(JSON.stringify({code:'PT409',message:error}));}else res.end(JSON.stringify(data));
  }catch{res.writeHead(500);res.end('{}');}
 }).listen(54331,'127.0.0.1',()=>console.log('Synthetic change-review UI RPC: 127.0.0.1:54331. No DB/provider.'));
}else{
 let checks=0;const ok=v=>{assert.ok(v);checks++;};
 ok(databaseItem(item,'candidates',id).programInfo.inputChanged);
 ok(databaseItem({...item,history:[{action:'save_candidate',actor,at:'2026-10-03T00:00:00Z',note:'합성',fields:['source_change_review:edited','source_change_stage:published']}]},'candidates',id).history[0].changeLabel==='공개 내용 수정·원문 변경 확인');
 ok(databaseItem({...item,programInfo:{...item.programInfo,changeReviewed:true,canPublish:true}},'candidates',id).programInfo.canPublish);
 assert.throws(()=>databaseItem({...item,source:{...item.source,name:'seoul_reservation'}},'candidates',id));checks++;
 const command={action:'review_change',revision:item.revision,version:item.version,disposition:'no_impact',note:'원문 대조 근거'};
 for(const invalid of [{...command,note:''},{...command,actor},{...command,content:item.content},{...command,disposition:'edited'},{...command,disposition:'ignore'}]){assert.throws(()=>validateCommand('candidates',invalid));checks++;}
 ok(validateCommand('candidates',{...command,disposition:'edited',content:item.content}).content.titleKo===item.content.titleKo);
 ok(myseoulReasonFields('source_change_conflict:operation')[0]==='periods');
 ok(myseoulReasonFields('source_change_conflict:unsupported').length===0);
 let calls=0;const store=new DatabaseReviewStore({rpc:async(name,args)=>{calls++;ok(name==='admin_myseoul_review_change'&&args.p_actor===actor&&args.p_content===null);return{data:item,error:null};}});
 const request=(cmd,origin='http://localhost')=>new Request('http://localhost/api/admin/review/candidates/'+id,{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(cmd)});
 const deps={authorize:async()=>({userId:actor}),store:()=>store};
 const result=await reviewDetail(request(command),'candidates',id,deps);ok(result.status===200&&result.headers.get('cache-control').includes('no-store'));
 const before=calls;ok((await reviewDetail(request(command,'https://evil.invalid'),'candidates',id,deps)).status===403);ok(calls===before);
 for(const state of ['signed_out','forbidden','auth_unavailable']){const r=await reviewDetail(request(command),'candidates',id,{authorize:async()=>{throw new AdminAccessError(state);},store:()=>{throw Error('DB before authorization');}});ok(r.status>=400&&r.headers.get('cache-control').includes('no-store'));}
 const failed=new DatabaseReviewStore({rpc:async()=>({data:null,error:{message:'review_conflict'}})});
 ok((await reviewDetail(request(command),'candidates',id,{...deps,store:()=>failed})).status===409);
 console.log(JSON.stringify({checks,mode:'synthetic',scope:'change-review actor/Origin/no-store/validation/projection'}));
}
