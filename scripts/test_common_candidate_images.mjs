// Real common handlers/DTO/store; existing and future sources are fake fixtures.
import assert from 'node:assert/strict';
import {imageFixture,id} from './test_seoul_candidate_images.mjs';
const {reviewDetail}=await import('../app/lib/review/handlers.ts');
const {databaseItem}=await import('../app/lib/review/database-dto.ts');
const {canEditCandidateImage}=await import('../app/lib/review/candidate-images.ts');
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const post=value=>new Request(`http://localhost/api/admin/review/candidates/${id}`,{method:'POST',headers:{'content-type':'application/json',origin:'http://localhost'},body:JSON.stringify(value)});
const originalFetch=globalThis.fetch;globalThis.fetch=()=>{throw Error('network forbidden');};
try{
 for(const source of ['myseoul_program','seoul_reservation','youthcenter_policy','youthcenter_content','synthetic_future_feed']){
  for(const sourceUrl of [null,'https://images.example.org/source.png']){
   const f=await imageFixture();if(source==='synthetic_future_feed')f.registerSource(source); // fake review registration, not product/DB config
   f.state={...f.state,source:{...f.state.source,name:source},image:{mode:'source',url:null,sourceUrl}};
   const original=f.state;
   eq(databaseItem(f.state,'candidates',id).image,f.state.image);eq(canEditCandidateImage(databaseItem(f.state,'candidates',id)),true);
   const command=image=>({action:'save_candidate',revision:f.state.revision,version:f.state.version,content:f.state.content,imageSelection:image});
   for(const image of [{mode:'override',url:'https://images.example.org/add.png'},{mode:'override',url:'https://images.example.org/edit.jpg'},{mode:'none',url:null},{mode:'source',url:null}]){
    const before=f.state,c=command(image),r=await reviewDetail(post(c),'candidates',id,f.deps);eq(r.status,200);
    const saved=(await r.json()).item;eq(saved.image,{...image,sourceUrl});eq(saved.content,before.content);eq(saved.source,original.source);
    eq(saved.revision,original.revision);eq(saved.history.length,before.history.length+1);eq(saved.version!==before.version,true);
    eq(f.calls.findLast(x=>x.name==='admin_review_save_candidate_image').args.p_version,before.version);
    const state=f.state;eq((await reviewDetail(post(c),'candidates',id,f.deps)).status,409);eq(f.state,state);
   }
   const before=f.state;f.control({failure:'throw'});eq((await reviewDetail(post(command({mode:'none',url:null})),'candidates',id,f.deps)).status,503);eq(f.state,before);
   const missing={...before,image:undefined};eq(canEditCandidateImage(databaseItem(missing,'candidates',id)),false);
   assert.throws(()=>databaseItem({...before,image:{mode:'override',url:'http://images.example.org/a.png',sourceUrl}},'candidates',id));checks++;
  }
 }
 const f=await imageFixture();f.state={...f.state,source:{...f.state.source,name:'unregistered_feed'}};
 const before=f.state,c={action:'save_candidate',revision:before.revision,version:before.version,content:before.content,imageSelection:{mode:'none',url:null}};
 eq((await reviewDetail(post(c),'candidates',id,f.deps)).status,422);eq(f.state,before);
 console.log(`Common candidate images: ${checks} source-independent real handler/DTO/fake RPC checks passed; 4 current + future synthetic source, with/without image. DB/AI/network=0.`);
}finally{globalThis.fetch=originalFetch;}
