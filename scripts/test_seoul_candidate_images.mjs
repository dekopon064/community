// Real handlers/DTO/store with synthetic administrator RPC only. No DB/provider.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {DatabaseReviewStore}=await import('../app/lib/review/database-store.ts');
const {databaseItem}=await import('../app/lib/review/database-dto.ts');
const {reviewDetail}=await import('../app/lib/review/handlers.ts');
const {AdminAccessError}=await import('../app/lib/auth/admin-policy.ts');
const {LocalReviewStore}=await import('../app/lib/review/local-fixture.ts');
const {canEditCandidateImage}=await import('../app/lib/review/candidate-images.ts');
export const actor='00000000-0000-4000-8000-000000000001';
export const id='20000000-0000-4000-8000-000000000001';
export async function imageFixture(){
 const sample=await new LocalReviewStore().get('candidates',id);
 let state={...sample,version:'b'.repeat(64),category:'program',
  source:{name:'seoul_reservation',title:'합성 서울 예약 프로그램',url:'https://example.invalid/synthetic',body:'합성 원문입니다. 실제 수집·DB·AI를 사용하지 않습니다.'},
  image:{mode:'source',url:null,sourceUrl:'https://images.example.org/source.png'},
  programInfo:{inputFactsVersion:1,currentFactsVersion:1,inputChanged:false,canPublish:true,applicationPeriod:'2099.10.01~2099.10.10',operatingPeriod:'2099.10.18'}};
 state.content={...state.content,titleKo:state.source.title};
 let failure=null,seq=15,authorized=true;const calls=[];
 const registeredSources=new Set(['myseoul_program','seoul_reservation','youthcenter','youthcenter_policy','youthcenter_content']);
 const rpc=async(name,args)=>{
  calls.push({name,args:structuredClone(args)});
  if(failure==='throw')throw Error('synthetic ambiguous response');
  if(failure)return {data:null,error:{message:failure}};
  if(name==='admin_review_list')return {data:args.p_kind==='candidates'?[{id,title:state.content.titleKo,sourceName:state.source.name,status:state.status,reasons:[]}]:[],error:null};
  if(name==='admin_review_detail')return {data:structuredClone(state),error:null};
  if(!['admin_review_save_candidate_image','admin_review_save_candidate'].includes(name))return {data:null,error:{message:'review_invalid_input'}};
  if(args.p_revision!==state.revision||args.p_version!==state.version)return {data:null,error:{message:'review_conflict'}};
  if(state.status!=='pending'||state.publishedId)return {data:null,error:{message:'review_already_processed'}};
  if(args.p_image&&!registeredSources.has(state.source.name))return {data:null,error:{message:'review_invalid_input'}};
  const image=args.p_image?{...args.p_image,sourceUrl:state.image.sourceUrl}:state.image;
  if(JSON.stringify(image)===JSON.stringify(state.image)&&JSON.stringify(args.p_content)===JSON.stringify(state.content))return {data:structuredClone(state),error:null};
  // Commit both fields and history together in this fake; SQL itself is unapplied.
  state={...state,content:structuredClone(args.p_content),image:structuredClone(image),version:(seq++).toString(16).padStart(64,'0'),
   history:[...state.history,{action:'save_candidate',actor:args.p_actor,at:new Date().toISOString(),note:'합성 이미지 선택 변경'}]};
  return {data:structuredClone(state),error:null};
 };
 const store=new DatabaseReviewStore({rpc});
 const deps={authorize:async()=>{if(!authorized)throw new AdminAccessError('signed_out');return {userId:actor};},store:()=>store};
 return {deps,store,calls,registerSource(name){registeredSources.add(name);},get state(){return structuredClone(state);},set state(value){state=structuredClone(value);},control(value){failure=value.failure??null;authorized=value.authorized!==false;if(value.sourceUrl!==undefined)state.image.sourceUrl=value.sourceUrl;}};
}

if(process.argv[1]?.endsWith('test_seoul_candidate_images.mjs')){
 let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
 const f=await imageFixture(),initial=f.state,post=(command,origin='http://localhost')=>new Request(`http://localhost/api/admin/review/candidates/${id}`,{method:'POST',headers:{'content-type':'application/json',origin},body:JSON.stringify(command)});
 const command=image=>({action:'save_candidate',revision:f.state.revision,version:f.state.version,content:f.state.content,...(image?{imageSelection:image}:{})});
 const send=c=>reviewDetail(post(c),'candidates',id,f.deps);
 const originalFetch=globalThis.fetch;globalThis.fetch=()=>{throw Error('network forbidden');};
 try{
  eq(canEditCandidateImage(databaseItem(f.state,'candidates',id)),true);
  f.control({sourceUrl:null});eq(canEditCandidateImage(databaseItem(f.state,'candidates',id)),true);
  for(const image of [{mode:'override',url:'https://images.example.org/new.png'},{mode:'override',url:'https://images.example.org/edited.jpg'},{mode:'none',url:null},{mode:'source',url:null}]){
   const before=f.state,stale=command(image),r=await send(stale);eq(r.status,200);eq(r.headers.get('cache-control'),'private, no-store, max-age=0');
   eq((await r.json()).item.image,{...image,sourceUrl:null});eq(f.calls.at(-1).name,'admin_review_save_candidate_image');eq(f.calls.at(-1).args.p_actor,actor);
   eq(f.state.content,before.content);eq(f.state.source,initial.source);eq(f.state.revision,initial.revision);eq(f.state.programInfo,initial.programInfo);
   eq(f.state.history.length,before.history.length+1);eq((await send(stale)).status,409);
  }
  const unchanged=f.state;eq((await send(command({mode:'source',url:null}))).status,200);eq(f.state,unchanged);
  // Omitting imageSelection is a content-only save, preserving existing choice.
  const c=command();c.content={...c.content,titleKo:'합성 제목 수정'};eq((await send(c)).status,200);eq(f.calls.at(-1).name,'admin_review_save_candidate');eq(f.state.image,unchanged.image);
  for(const image of [{mode:'override',url:'http://images.example.org/a.png'},{mode:'override',url:'https://127.0.0.1/a.png'},{mode:'override',url:'https://images.example.org/a.svg'},{mode:'override',url:''},{mode:'none',url:'https://images.example.org/a.png'}]){
   const n=f.calls.length,before=f.state;eq((await send(command(image))).status,422);eq(f.calls.length,n);eq(f.state,before);
  }
  const before=f.state;for(const failure of ['review_conflict','synthetic_save_error','throw']){
   f.control({failure});const n=f.calls.length;eq((await send(command({mode:'none',url:null}))).status,failure==='review_conflict'?409:503);eq(f.calls.length,n+1);eq(f.state,before);
  }
  f.control({authorized:false});let n=f.calls.length;eq((await send(command({mode:'none',url:null}))).status,401);eq(f.calls.length,n);
  f.control({});n=f.calls.length;eq((await reviewDetail(post(command({mode:'none',url:null}),'https://outside.example.org'),'candidates',id,f.deps)).status,403);eq(f.calls.length,n);
  for(const status of ['published','rejected','superseded']){f.state={...before,status};eq(canEditCandidateImage(f.state),false);eq((await send(command({mode:'none',url:null}))).status,409);}
  f.state={...before,image:undefined};eq(canEditCandidateImage(databaseItem(f.state,'candidates',id)),false); // no invented empty selection
  assert.throws(()=>databaseItem({...before,image:{mode:'override',url:'http://images.example.org/a.png',sourceUrl:null}},'candidates',id));checks++;
  assert.throws(()=>databaseItem({...before,image:{mode:'source',url:null,sourceUrl:'https://127.0.0.1/a.png'}},'candidates',id));checks++;
  f.state={...before,source:{...before.source,name:'myseoul_program'}};eq(canEditCandidateImage(f.state),true);
  for(const source of ['youthcenter_policy','youthcenter_content'])eq(canEditCandidateImage({...before,source:{...before.source,name:source}}),true);
  console.log(`Seoul candidate images: ${checks} real handler/DTO/fake RPC checks passed. DB/AI/network=0; SQL runtime untested.`);
 }finally{globalThis.fetch=originalFetch;}
}
