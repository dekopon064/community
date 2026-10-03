// Fresh isolated in-memory PGlite, synthetic rows/provider output only.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {registerHooks} from 'node:module';
import {fileURLToPath} from 'node:url';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
registerHooks({resolve(s,c,next){
 // DTO localization only; make any accidental DB call fail without networking.
 if(s==='@/app/lib/supabase')return {url:'data:text/javascript,export const supabase={from(){throw Error("network forbidden")}};',shortCircuit:true};
 if(s.startsWith('@/'))s=new URL('../'+s.slice(2)+'.ts',import.meta.url).href;
 try{return next(s,c);}catch(e){if(s.startsWith('.')&&!/\.[a-z]+$/i.test(s))return next(s+'.ts',c);throw e;}
}});
const {sourceImageUrl}=await import('../app/lib/sourceImages.ts');
const {localizeCuration}=await import('../app/lib/curations.ts');
const python=process.env.MACHIMOA_TEST_PYTHON;
if(!python)throw Error('Explicit existing local Python required');
const samples=JSON.parse(execFileSync(python,['-X','utf8','test_myseoul_ai.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'}));
const f=await reviewDatabase();let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const migration=n=>readFile(new URL('../supabase/migrations/'+n,import.meta.url),'utf8');
const actor='00000000-0000-4000-8000-000000000001';
try{
 const {db,query:q,rpc,source,candidate}=f;
 for(const n of ['20261002000100_admin_review_trash.sql','20261002000200_admin_review_trash_publication.sql','20261002000300_myseoul_program_contract.sql','20261002000400_myseoul_program_ai.sql','20261003000000_source_images.sql','20261003000001_myseoul_change_collection.sql','20261003000100_myseoul_list_discovery.sql'])await db.exec(await migration(n));
 const definitions=()=>q("select oid::regprocedure::text name,pg_get_functiondef(oid) body,proacl::text acl from pg_proc where pronamespace in ('machimoa_review'::regnamespace,'public'::regnamespace) order by 1");
 const before=await definitions(),sources=await q('select * from machimoa_review.ingest_sources order by source_id');
 const acl=before.find(x=>x.name==='machimoa_review.project_published_source_image()').acl;
 await db.exec(await migration('20261003000200_myseoul_source_images.sql'));
 eq((await definitions()).filter(x=>x.name!=='machimoa_review.project_published_source_image()'),before.filter(x=>x.name!=='machimoa_review.project_published_source_image()'));
 eq((await definitions()).find(x=>x.name==='machimoa_review.project_published_source_image()').acl,acl);
 eq(await q('select * from machimoa_review.ingest_sources order by source_id'),sources);
 for(const role of ['anon','authenticated','service_role'])eq((await q('select has_function_privilege($1,\'machimoa_review.project_published_source_image()\',\'execute\') v',[role]))[0].v,false);
 for(const value of ['https://global.seoul.go.kr/poster.jpg',null,'http://global.seoul.go.kr/poster.jpg','https://127.0.0.1/a.png','https://global.seoul.go.kr/a.svg','data:image/png;base64,ignored'])eq((await q('select machimoa_review.safe_source_image_url($1) v',[value]))[0].v,sourceImageUrl(value));
 const synthetic=async(origin,key,image)=>{
  const id=await source(key,origin),cid=await candidate(key,origin);
  await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[id,JSON.stringify(image)]);
  const pub=(await q("insert into public.curations(slug,title,summary,content,source,source_item_id,is_published) values($1,'제목','요약','본문',$2,$1,true) returning id",[key,origin]))[0].id;
  const project=()=>q("update machimoa_review.curation_candidates set review_status='published',published_curation_id=$2,published_at=now(),reviewed_at=now(),reviewed_by='synthetic' where id=$1",[cid,pub]);
  await project();return {id,cid,pub,project};
 };
 const image=pub=>q('select source_image_url from public.curations where id=$1',[pub]).then(r=>r[0].source_image_url);
 const my=await synthetic('myseoul_program','A'.repeat(32)+':'+ 'B'.repeat(32),{source_image_url:'https://global.seoul.go.kr/poster.jpg'});
 eq(await image(my.pub),'https://global.seoul.go.kr/poster.jpg');
 // Correctly cleared for absent/invalid URL, older revision, different item.
 for(const value of [null,'http://global.seoul.go.kr/b.jpg']){
  await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[my.id,JSON.stringify({source_image_url:'https://global.seoul.go.kr/poster.jpg'})]);await my.project();
  await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[my.id,JSON.stringify({source_image_url:value})]);await my.project();eq(await image(my.pub),null);
 }
 await q("update machimoa_review.source_items set normalized_payload=$2,revision_hash=repeat('b',64) where id=$1",[my.id,JSON.stringify({source_image_url:'https://global.seoul.go.kr/new.jpg'})]);
 await my.project();eq(await image(my.pub),null);
 await q("update machimoa_review.source_items set revision_hash=repeat('a',64) where id=$1",[my.id]);await my.project();eq(await image(my.pub),'https://global.seoul.go.kr/new.jpg');
 await q("update machimoa_review.source_items set external_key=$2 where id=$1",[my.id,'C'.repeat(32)+':'+ 'D'.repeat(32)]);await my.project();eq(await image(my.pub),null);
 const youth=await synthetic('youthcenter_content','image-youth',{source_image_url:'https://images.example.org/youth.jpg'});
 const seoul=await synthetic('seoul_reservation','image-seoul',{provider_fields:{IMGURL:'https://images.example.org/seoul.jpg'}});
 eq(await image(youth.pub),'https://images.example.org/youth.jpg');eq(await image(seoul.pub),'https://images.example.org/seoul.jpg');
 const policy=await synthetic('youthcenter_policy','image-policy',{source_image_url:'https://images.example.org/policy.jpg'});eq(await image(policy.pub),null);
 // Actual My observation / synthetic completion / existing protected publication.
 await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program'");
 const run=(await q("select * from public.start_ingest_run('myseoul_program',600)"))[0].run_id;
 const packet=structuredClone(samples.packets[0]);packet.normalized_payload.source_image_url='https://global.seoul.go.kr/live-synthetic.jpg';
 const item=(await rpc('observe_myseoul_program',[run,[packet],null]))[0];
 const claim=(await rpc('claim_myseoul_program_ai',[item.id,item.revision,'synthetic',300]))[0];
 const done=await rpc('finish_myseoul_program_ai',[claim.jobId,claim.revision,claim.factsVersion,claim.claimedAt,claim.leaseUntil,claim.workerId,samples.outputs[0]]);
 let detail=await rpc('admin_review_detail',['candidates',done.candidateId]);
 const publicBefore=(await q('select count(*)::int n from public.curations'))[0].n;
 await assert.rejects(()=>db.transaction(async tx=>{
  await tx.exec('set local role service_role');
  const r=(await tx.query('select public.admin_review_publish($1,$2,$3,$4) v',[done.candidateId,detail.revision,detail.version,actor])).rows[0].v;
  assert.equal((await tx.query('select source_image_url from public.curations where id=$1',[r.publishedId])).rows[0].source_image_url,packet.normalized_payload.source_image_url);
  throw Error('synthetic failure after projection');
 }));checks++;
 eq((await q('select count(*)::int n from public.curations'))[0].n,publicBefore);eq((await rpc('admin_review_detail',['candidates',done.candidateId])).status,'pending');
 detail=await rpc('admin_review_publish',[done.candidateId,detail.revision,detail.version,actor]);
 eq(await image(detail.publishedId),packet.normalized_payload.source_image_url);
 const provenance=await q('select * from machimoa_review.program_candidate_inputs where candidate_id=$1',[done.candidateId]);
 const next=structuredClone(packet);next.revision_hash='f'.repeat(64);next.myseoul_facts.source_revision=next.revision_hash;next.normalized_payload.source_image_url=null;
 await q("update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{qualification_note}',to_jsonb('운영자 확인 보완'::text)),facts_version=facts_version+1 where source_item_id=$1",[item.id]);
 await rpc('observe_myseoul_program',[run,[next],null]);
 eq(await image(detail.publishedId),packet.normalized_payload.source_image_url); // ingestion does not edit public
 eq((await rpc('admin_myseoul_program_detail',[item.id])).facts.qualification_note,'운영자 확인 보완');
 eq((await q("select count(*)::int n from machimoa_review.processing_jobs where source_item_id=$1 and revision_hash=$2 and processing_stage='ai_enrichment' and status='queued'",[item.id,next.revision_hash]))[0].n,0);
 detail=await rpc('admin_review_detail',['candidates',done.candidateId]);
 const edited={...detail.content,contentKo:detail.content.contentKo+' 확인 안내',contentJa:detail.content.contentJa+' 確認案内'};
 detail=await rpc('admin_myseoul_review_change',[done.candidateId,detail.revision,detail.version,'edited','원문 변경과 이미지 제거 확인',edited,actor]);
 eq(await image(detail.publishedId),null);eq(detail.status,'published');
 eq(await q('select * from machimoa_review.program_candidate_inputs where candidate_id=$1',[done.candidateId]),provenance);
 const row=(await q('select * from public.curations where id=$1',[detail.publishedId]))[0];
 eq(localizeCuration(row,'ko').source_image_url,null);
 eq(localizeCuration({...row,source_image_url:'https://global.seoul.go.kr/poster.jpg'},'ja').source_image_url,'https://global.seoul.go.kr/poster.jpg');
 eq(localizeCuration({...row,source_image_url:'http://global.seoul.go.kr/poster.jpg'},'ko').source_image_url,null);
 await q('update machimoa_review.source_items set external_key=$2 where id=$1',[my.id,'A'.repeat(32)+':'+ 'B'.repeat(32)]);await my.project();
 eq(await image(my.pub),'https://global.seoul.go.kr/new.jpg');
 await db.exec(await readFile(new URL('../supabase/rollback/20261003000200_myseoul_source_images_down.sql',import.meta.url),'utf8'));
 eq(await definitions(),before);
 eq((await q("select count(*)::int n from pg_trigger where tgname='project_myseoul_updated_source_image'"))[0].n,0);
 eq(await image(youth.pub),'https://images.example.org/youth.jpg');
 eq(await image(my.pub),'https://global.seoul.go.kr/new.jpg');
 console.log(`My source images: ${checks} PGlite/DTO checks passed; synthetic only; independent PostgreSQL/PostgREST/live images not exercised.`);
}catch(e){if(e.query)throw Error(`SQL check failed: ${e.code} ${e.message}`);throw e;}
finally{await f.db.close();}
