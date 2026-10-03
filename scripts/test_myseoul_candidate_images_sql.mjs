// Fresh in-memory PGlite; synthetic source/candidates/output, no provider/network.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {registerHooks} from 'node:module';
import {fileURLToPath} from 'node:url';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
registerHooks({resolve(s,c,next){try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}}});
const {databaseItem}=await import('../app/lib/review/database-dto.ts');
const f=await reviewDatabase();let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const actor='00000000-0000-4000-8000-000000000001';
const migration=n=>readFile(new URL('../supabase/migrations/'+n,import.meta.url),'utf8');
const samples=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','test_myseoul_ai.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
try{
 const {db,query:q,rpc}=f;
 for(const n of ['20261002000100_admin_review_trash.sql','20261002000200_admin_review_trash_publication.sql','20261002000300_myseoul_program_contract.sql','20261002000400_myseoul_program_ai.sql','20261003000000_source_images.sql','20261003000001_myseoul_change_collection.sql','20261003000100_myseoul_list_discovery.sql','20261003000200_myseoul_source_images.sql'])await db.exec(await migration(n));
 const defs=()=>q("select oid::regprocedure::text name,pg_get_functiondef(oid) body,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'machimoa_review'::regnamespace) order by 1");
 const before=await defs();
 const previousProjection=before.find(r=>r.name==='machimoa_review.project_published_source_image()').body;
 await db.exec(previousProjection.replace('begin','begin\n-- synthetic later change'));
 await assert.rejects(async()=>db.exec(await migration('20261003000300_myseoul_candidate_images.sql')),e=>e.message==='source_image_projection_definition_changed');checks++;
 await db.exec('rollback');await db.exec(previousProjection);
 await db.exec(await migration('20261003000300_myseoul_candidate_images.sql'));
 const after=await defs();const changed=['machimoa_review.admin_review_item(text,uuid)','machimoa_review.project_published_source_image()','admin_myseoul_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)'];
 eq(after.filter(r=>!changed.includes(r.name)),before.filter(r=>!changed.includes(r.name)));
 for(const role of ['anon','authenticated']){
  eq((await q("select has_function_privilege($1,'admin_myseoul_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)','execute') v",[role]))[0].v,false);
  eq((await q("select has_table_privilege($1,'machimoa_review.curation_candidates','update') v",[role]))[0].v,false);
 }
 eq((await q("select has_function_privilege('service_role','admin_myseoul_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)','execute') v"))[0].v,true);
 for(const name of changed.slice(0,2))eq(after.find(r=>r.name===name).acl,before.find(r=>r.name===name).acl);
 await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program'");
 const run=(await q("select * from public.start_ingest_run('myseoul_program',600)"))[0].run_id;
 const make=async(index,image)=>{

  const packet=JSON.parse(JSON.stringify(samples.packets[0]).replaceAll(samples.packets[0].external_key.split(':')[1],index.toString(16).toUpperCase().padStart(32,'0')));
  packet.normalized_payload.program_id=packet.external_key.split(':')[1];packet.normalized_payload.source_image_url=image;
  const item=(await rpc('observe_myseoul_program',[run,[packet],null]))[0];
  const claim=(await rpc('claim_myseoul_program_ai',[item.id,item.revision,'synthetic',300]))[0];
  const done=await rpc('finish_myseoul_program_ai',[claim.jobId,claim.revision,claim.factsVersion,claim.claimedAt,claim.leaseUntil,claim.workerId,samples.outputs[0]]);
  return {sid:item.id,id:done.candidateId,packet,detail:await rpc('admin_review_detail',['candidates',done.candidateId])};
 };
 const save=(d,i,content=d.content)=>rpc('admin_myseoul_save_candidate_image',[d.id,d.revision,d.version,content,i,actor]);
 const image=id=>q('select source_image_url from public.curations where id=$1',[id]).then(r=>r[0].source_image_url);
 const provenance=sid=>q("select s.revision_hash,s.normalized_payload,f.facts,f.facts_version,(select jsonb_agg(to_jsonb(j) order by j.id) from machimoa_review.processing_jobs j where j.source_item_id=s.id) jobs,(select jsonb_agg(to_jsonb(i) order by i.candidate_id) from machimoa_review.program_candidate_inputs i where i.source_item_id=s.id) inputs from machimoa_review.source_items s join machimoa_review.source_item_program_facts f on f.source_item_id=s.id where s.id=$1",[sid]);
 const a=await make(101,'https://images.example.org/source.png');let d=a.detail;
 eq(d.image,{mode:'source',url:null,sourceUrl:a.packet.normalized_payload.source_image_url});eq(databaseItem(d,'candidates',d.id).image,d.image);
 const original=await provenance(a.sid);
 for(const i of [{mode:'override',url:'https://images.example.org/first.png'},{mode:'override',url:'https://images.example.org/second.png'},{mode:'none',url:null},{mode:'source',url:null}]){
  const old=d;d=await save(d,i);eq(d.image,{...i,sourceUrl:a.packet.normalized_payload.source_image_url});assert.notEqual(d.version,old.version);checks++;
  await assert.rejects(()=>save(old,i),e=>e.message==='review_conflict');checks++;
  eq(await provenance(a.sid),original);eq(d.content,old.content);eq(databaseItem(d,'candidates',d.id).image,d.image);
 }
 eq((await save(d,{mode:'source',url:null})).version,d.version); // exact no-op
 const beforeInvalid=d;
 for(const i of [{mode:'override',url:'http://images.example.org/a.png'},{mode:'override',url:'https://127.0.0.1/a.png'},{mode:'override',url:'https://images.example.org/a.svg'},{mode:'override',url:''},{mode:'none',url:'https://images.example.org/a.png'},{mode:'bad',url:null},{mode:'source',url:null,actor:actor}]){
  await assert.rejects(()=>save(d,i,{...d.content,titleKo:'실패하면 남기지 않을 제목'}),e=>e.message==='review_invalid_input');checks++;
  eq(await rpc('admin_review_detail',['candidates',d.id]),beforeInvalid);
 }
 // An event insert failure must roll back both content and image selection.
 await db.exec("create function public.synthetic_event_failure() returns trigger language plpgsql as $$begin if 'image_selection_mode'=any(new.changed_fields) then raise exception 'synthetic image event failure';end if;return new;end$$; create trigger synthetic_image_event_failure before insert on machimoa_review.admin_review_events for each row execute function public.synthetic_event_failure();");
 await assert.rejects(()=>save(d,{mode:'none',url:null},{...d.content,titleKo:'원자성 검증'}));checks++;
 eq(await rpc('admin_review_detail',['candidates',d.id]),beforeInvalid);
 await db.exec('drop trigger synthetic_image_event_failure on machimoa_review.admin_review_events;drop function public.synthetic_event_failure()');
 const b=await make(102,null);eq(b.detail.image.sourceUrl,null);eq(b.detail.programInfo.canPublish,true);
 const variants=[[a,{mode:'override',url:'https://images.example.org/operator.png'}],[b,{mode:'none',url:null}],[await make(103,'https://images.example.org/third.png'),{mode:'source',url:null}],[await make(104,null),{mode:'source',url:null}]];
 for(const [entry,selection] of variants){
  let detail=await rpc('admin_review_detail',['candidates',entry.id]);detail=await save(detail,selection);
  const state=await rpc('admin_review_detail',['candidates',entry.id]);const publicCount=(await q('select count(*)::int n from public.curations'))[0].n;
  await assert.rejects(()=>db.transaction(async tx=>{
   await tx.exec('set local role service_role');await tx.query('select public.admin_review_publish($1,$2,$3,$4)',[detail.id,detail.revision,detail.version,actor]);throw Error('synthetic failure after publication');
  }));checks++;eq(await rpc('admin_review_detail',['candidates',entry.id]),state);eq((await q('select count(*)::int n from public.curations'))[0].n,publicCount);
  detail=await rpc('admin_review_publish',[detail.id,detail.revision,detail.version,actor]);
  eq(await image(detail.publishedId),selection.mode==='override'?selection.url:selection.mode==='none'?null:entry.packet.normalized_payload.source_image_url);
  await assert.rejects(()=>save(detail,{mode:'source',url:null}),e=>['review_already_processed','review_invalid_input'].includes(e.message));checks++;
  if(entry===a){await q("update machimoa_review.curation_candidates set title_ko=title_ko||' 원문 대조' where id=$1",[entry.id]);eq(await image(detail.publishedId),selection.url);}
 }
 await f.source('other-image','youthcenter_content');const otherId=await f.candidate('other-image','youthcenter_content');
 const other=await rpc('admin_review_detail',['candidates',otherId]);await assert.rejects(()=>save(other,{mode:'none',url:null}),e=>e.message==='review_invalid_input');checks++;eq((await q('select image_selection_mode from machimoa_review.curation_candidates where id=$1',[otherId]))[0].image_selection_mode,'source');
 // The modified shared trigger retains youth/Seoul projection semantics.
 for(const [origin,payload] of [['youthcenter_content',{source_image_url:'https://images.example.org/youth.png'}],['seoul_reservation',{provider_fields:{IMGURL:'https://images.example.org/seoul.png'}}]]){
  const key='projection-'+origin,sid=await f.source(key,origin),cid=await f.candidate(key,origin);
  await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[sid,JSON.stringify(payload)]);
  const pub=(await q("insert into public.curations(slug,title,summary,content,source,source_item_id,is_published) values($1,'합성 제목','요약','본문',$2,$1,true) returning id",[key,origin]))[0].id;
  await q("update machimoa_review.curation_candidates set review_status='published',published_curation_id=$2,published_at=now(),reviewed_at=now(),reviewed_by='synthetic' where id=$1",[cid,pub]);
  eq(await image(pub),payload.source_image_url??payload.provider_fields.IMGURL);
 }
 // Revision mismatch uses no source image, never a different candidate's URL.
 const e=await make(105,'https://images.example.org/older.png');const newer=structuredClone(e.packet);newer.revision_hash='e'.repeat(64);newer.myseoul_facts.source_revision=newer.revision_hash;await rpc('observe_myseoul_program',[run,[newer],null]);
 eq((await rpc('admin_review_detail',['candidates',e.id])).image.sourceUrl,null);
 await assert.rejects(async()=>db.exec(await readFile(new URL('../supabase/rollback/20261003000300_myseoul_candidate_images_down.sql',import.meta.url),'utf8')),e=>e.message==='candidate_image_choices_require_preservation');checks++;
 await db.exec('rollback');
 // Rollback allowed with only default choices; retained columns/history/data.
 await q("update machimoa_review.curation_candidates set image_selection_mode='source',image_override_url=null");
 const events=(await q('select count(*)::int n from machimoa_review.admin_review_events'))[0].n;
 await db.exec(await readFile(new URL('../supabase/rollback/20261003000300_myseoul_candidate_images_down.sql',import.meta.url),'utf8'));
 eq((await defs()).filter(r=>!changed.includes(r.name)),before.filter(r=>!changed.includes(r.name)));
 for(const name of changed.slice(0,2))eq((await defs()).find(r=>r.name===name),before.find(r=>r.name===name));
 eq((await q('select count(*)::int n from machimoa_review.admin_review_events'))[0].n,events);
 console.log(`My candidate images: ${checks} isolated PGlite/DTO checks passed. No independent PostgreSQL/PostgREST/provider.`);
}catch(e){if(e.query)throw Error(`SQL check failed: ${e.code} ${e.message}`);throw e;}finally{await f.db.close();}
