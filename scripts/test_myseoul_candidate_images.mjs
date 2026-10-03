// Protected handler/adapter with a fake administrator RPC. No remote connection.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {createServer} from 'node:http';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {DatabaseReviewStore}=await import('../app/lib/review/database-store.ts');
const {reviewDetail}=await import('../app/lib/review/handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {validateCommand}=await import('../app/lib/review/validation.ts');
const fixture=new LocalReviewStore();const id='20000000-0000-4000-8000-000000000001',actor='00000000-0000-4000-8000-000000000001';
let state={...await fixture.get('candidates',id),version:'c'.repeat(64),source:{name:'myseoul_program',title:'합성 My Seoul+ 프로그램',url:'https://global.seoul.go.kr/synthetic',body:'로컬 검증용 원문'},
 image:{mode:'source',url:null,sourceUrl:'https://images.example.org/source.png'},
 programInfo:{inputFactsVersion:1,currentFactsVersion:1,inputChanged:false,canPublish:true,changeReviewed:false,changedFields:[],comparisonAvailable:true,applicationPeriod:'접수 중',operatingPeriod:'검증용 기간'}};
state.content={...state.content,titleKo:'합성 My Seoul+ 프로그램'};
let failure=null,calls=[],stores=0,seq=12;
const rpc=async(name,args)=>{
 calls.push({name,args});
 if(failure)return {data:null,error:{message:failure}};
 if(name==='admin_review_list')return {data:args.p_kind==='candidates'?[{id,title:state.content.titleKo,sourceName:'myseoul_program',status:'pending',reasons:[]}]:[],error:null};
 if(name==='admin_myseoul_save_candidate_image'||name==='admin_review_save_candidate'){
  if(args.p_version!==state.version)return {data:null,error:{message:'review_conflict'}};
  state={...state,content:args.p_content,version:(seq++).toString(16).padStart(64,'0'),image:args.p_image?{...args.p_image,sourceUrl:state.image.sourceUrl}:state.image,
    history:[{action:'save_candidate',actor:args.p_actor,at:new Date().toISOString(),note:'합성 이미지 저장'},...state.history]};
 }
 return {data:structuredClone(state),error:null};
};
const store=new DatabaseReviewStore({rpc});
const deps={authorize:async()=>({userId:actor}),store:()=>{stores++;return store;}};
const command=i=>({action:'save_candidate',revision:state.revision,version:state.version,content:state.content,imageSelection:i});
const post=(value,origin='http://localhost')=>new Request(`http://localhost/api/admin/review/candidates/${id}`,{method:'POST',headers:{'content-type':'application/json',origin},body:JSON.stringify(value)});
if(process.argv.includes('--serve')){
 const server=createServer(async(req,res)=>{
  const chunks=[];for await(const chunk of req)chunks.push(chunk);const body=Buffer.concat(chunks).toString();
  res.setHeader('content-type','application/json');
  if(req.url==='/test/control'){
   const c=JSON.parse(body);failure=c.failure??null;
   if(c.sourceUrl!==undefined)state.image.sourceUrl=c.sourceUrl;
   if(c.reset){state.image={mode:'source',url:null,sourceUrl:'https://images.example.org/source.png'};state.version=(seq++).toString(16).padStart(64,'0');}
   return res.end('{}');
  }
  if(req.url==='/test/state')return res.end(JSON.stringify({state,calls}));
  if(req.url.startsWith('/rest/v1/rpc/')){const r=await rpc(req.url.split('/').at(-1),JSON.parse(body));res.statusCode=r.error?409:200;return res.end(JSON.stringify(r.error?{code:'PT409',message:r.error.message}:r.data));}
  if(req.url.startsWith('/rest/v1/curations'))return res.end('[]');
  if(req.url.startsWith('/auth/v1/user')){
   try{const claims=JSON.parse(Buffer.from(req.headers.authorization.split('.')[1],'base64url'));
    return res.end(JSON.stringify({id:claims.sub,aud:'authenticated',role:'authenticated',user_metadata:{full_name:'가짜 관리자'}}));
   }catch{res.statusCode=401;return res.end('{"code":"bad_jwt"}');}
  }
  res.statusCode=404;res.end('{}');
 });
 await new Promise(r=>server.listen(54367,'127.0.0.1',r));console.log('Synthetic auth/RPC/empty public-data backend http://127.0.0.1:54367 (no DB/provider)');
}else{
 let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
 for(const i of [{mode:'source',url:null},{mode:'override',url:' https://images.example.org/test.png '},{mode:'none',url:null}]){
  const r=await reviewDetail(post(command(i)),'candidates',id,deps);eq(r.status,200);eq(r.headers.get('cache-control'),'private, no-store, max-age=0');
  eq((await r.json()).item.image.mode,i.mode);eq(calls.at(-1).args.p_actor,actor);eq(calls.at(-1).name,'admin_myseoul_save_candidate_image');
 }
 for(const i of [{mode:'override',url:'http://images.example.org/a.png'},{mode:'override',url:'https://images.example.org/a.svg'},{mode:'override',url:'https://127.0.0.1/a.png'},{mode:'override',url:''},{mode:'none',url:'https://images.example.org/a.png'},{mode:'source',url:null,actor}]){
  const n=calls.length;eq((await reviewDetail(post(command(i)),'candidates',id,deps)).status,422);eq(calls.length,n);
 }
 for(const status of ['signed_out','forbidden']){
  const n=stores;eq((await reviewDetail(post(command({mode:'none',url:null})),'candidates',id,{...deps,authorize:async()=>{throw new AdminAccessError(status);}})).status,status==='signed_out'?401:403);eq(stores,n);
 }
 const n=calls.length;eq((await reviewDetail(post(command({mode:'none',url:null}),'https://outside.example.org'),'candidates',id,deps)).status,403);eq(calls.length,n);
 const previous=structuredClone(state);failure='review_conflict';eq((await reviewDetail(post(command({mode:'none',url:null})),'candidates',id,deps)).status,409);eq(state,previous);
 failure='synthetic_error';eq((await reviewDetail(post(command({mode:'none',url:null})),'candidates',id,deps)).status,503);eq(state,previous);
 eq('imageSelection' in validateCommand('candidates',{action:'save_candidate',revision:state.revision,version:state.version,content:state.content}),false);
 assert.throws(()=>validateCommand('candidates',{...command({mode:'none',url:null}),actor}));checks++;
 console.log(`My candidate images: ${checks} fake-admin handler/DTO/RPC checks passed; no SQL/provider.`);
}
