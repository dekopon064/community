// Fresh, isolated in-memory PostgreSQL only; no operational DB/auth/provider calls.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const fail=async(fn,code,message)=>{await assert.rejects(fn,e=>e.code===code&&(!message||e.message===message));checks++;};
const f=await reviewDatabase(),q=f.query,rpc=f.rpc;
const actor='00000000-0000-4000-8000-000000000001';
const get=id=>rpc('admin_review_detail',['facts',id]);
const trash=()=>rpc('admin_review_trash',[0,25]);
const entry=async id=>(await trash()).items.find(x=>x.sourceItemId===id);
const exclude=async(id,reason='service_not_suitable')=>{const i=await get(id);return rpc('admin_review_exclude_reason',[id,i.revision,i.version,reason,reason==='custom'?'합성 직접 제외 사유':'',actor,randomUUID()]);};
const restore=e=>rpc('admin_review_restore',[e.id,e.revision,e.version,actor,randomUUID()]);
async function seed(key,origin='youthcenter_content'){
 const id=await f.source(key,origin);
 await q(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes) values($1,$2,'content_review','queued',now(),now(),array['user_category_unconfirmed'])`,[id,f.revision]);
 return id;
}
async function publicRow(key,published,origin='youthcenter_content'){
 return (await q(`insert into public.curations(slug,source,source_item_id,title,content,is_published) values($1,$2,$1,'합성 제목','합성 본문',$3) returning id`,[key,origin,published]))[0].id;
}
async function history(key,curationId,origin='youthcenter_content',revision=f.revision){
 const candidate=await f.candidate(key,origin);
 await q(`update machimoa_review.curation_candidates set source_revision_hash=$4,review_status='published',published_at=now(),reviewed_at=now(),reviewed_by=$2,published_curation_id=$3 where id=$1`,[candidate,actor,curationId,revision]);
 return candidate;
}
async function publication(key,curationId,candidate,status='unpublished',origin='youthcenter_content'){
 await q(`insert into machimoa_review.source_publications(source_id,external_key,revision_hash,candidate_id,public_curation_id,publication_status,published_at,unpublished_at,takedown_status) values($1,$2,$3,$4,$5,$6,now(),case when $6='unpublished' then now() end,case when $6='unpublished' then 'unpublished' else 'none' end)`,[origin,key,f.revision,candidate,curationId,status]);
}
try{
 await f.db.exec(await readFile(new URL('../supabase/migrations/20261002000100_admin_review_trash.sql',import.meta.url),'utf8'));
 const beforeFunctions=await q(`select oid::regprocedure::text signature,pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'machimoa_review'::regnamespace) order by signature`);
 await f.db.exec(await readFile(new URL('../supabase/migrations/20261002000200_admin_review_trash_publication.sql',import.meta.url),'utf8'));
 // Reproduce the reported state: historical published candidate, actual unpublished row.
 const id=await seed('historical-unpublished'),pid=await publicRow('historical-unpublished',false),cid=await history('historical-unpublished',pid);
 await publication('historical-unpublished',pid,cid);
 const histBefore=await q('select * from machimoa_review.curation_candidates where id=$1',[cid]);
 const pubBefore=await q('select * from machimoa_review.source_publications where public_curation_id=$1',[pid]);
 const facts=(await get(id)).facts;
 eq((await exclude(id)).item.status,'excluded');eq((await entry(id)).canRestore,true);
 eq(await q('select * from machimoa_review.curation_candidates where id=$1',[cid]),histBefore);
 eq(await q('select * from machimoa_review.source_publications where public_curation_id=$1',[pid]),pubBefore);
 let result=await restore(await entry(id));eq(result.item.status,'open');eq(result.item.restoredReviewPending,true);eq(result.item.facts,facts);
 eq((await q(`select exists(select 1 from machimoa_review.processing_jobs where source_item_id=$1 and processing_stage='ai_enrichment' and status in ('queued','claimed')) live`,[id]))[0].live,false);
 eq((await exclude(id,'region_not_suitable')).item.status,'excluded');eq((await entry(id)).canRestore,true);
 // Current live flag wins over stale source publication/candidate markers.
 const stale=await seed('stale-lineage'),stalePid=await publicRow('stale-lineage',false),staleCid=await history('stale-lineage',stalePid);
 await publication('stale-lineage',stalePid,staleCid,'published');eq((await exclude(stale,'custom')).item.status,'excluded');
 const hidden=await seed('custom-unpublished'),hiddenPid=await publicRow('custom-unpublished',false);await history('custom-unpublished',hiddenPid);
 const hiddenItem=await get(hidden);eq((await rpc('admin_review_exclude',[hidden,hiddenItem.revision,hiddenItem.version,'합성 기타 사유',actor])).status,'excluded');
 for(const [key,origin] of [['live-content','youthcenter_content'],['live-policy','youthcenter_policy']]){
  const live=await seed(key,origin),livePid=await publicRow(key,true,origin),liveCid=await history(key,livePid,origin);
  await publication(key,livePid,liveCid,'published',origin);
  const item=await get(live),events=await q('select * from machimoa_review.admin_review_events where source_item_id=$1',[live]);
  await fail(()=>exclude(live),'PT409','trash_already_published');eq(await get(live),item);eq(await entry(live),undefined);
  await fail(()=>rpc('admin_review_exclude',[live,item.revision,item.version,'합성 기타 사유',actor]),'PT409','trash_already_published');
  eq(await q('select * from machimoa_review.admin_review_events where source_item_id=$1',[live]),events);
  // Lower-level shared manual exclude is also protected, even bypassing trash wrappers.
  await fail(()=>rpc('resolve_ingest_review_decision',[live,item.revision,'content','reject','unknown',[],['manual_non_target'],'local',actor,'합성 기타 사유']),'P0001','candidate_already_published');
 }
 const noHistory=await seed('live-no-history');await publicRow('live-no-history',true);
 await fail(()=>exclude(noHistory),'PT409','trash_already_published');
 const oldRevision=await seed('live-old-revision'),oldPid=await publicRow('live-old-revision',true);await history('live-old-revision',oldPid,'youthcenter_content','b'.repeat(64));
 await fail(()=>exclude(oldRevision),'PT409','trash_already_published');
 // UUID lineage keeps protection even if legacy public source labels are missing.
 const lineage=await seed('live-uuid-only'),lineagePid=await publicRow('unrelated-label',true);await history('live-uuid-only',lineagePid);
 await fail(()=>exclude(lineage),'PT409','trash_already_published');
 const publicationOnly=await seed('live-lineage-only'),publicationPid=await publicRow('other-public-label',true);
 await publication('live-lineage-only',publicationPid,null,'published');await fail(()=>exclude(publicationOnly),'PT409','trash_already_published');
 const removedPublic=await seed('removed-public-row');await history('removed-public-row',null);eq((await exclude(removedPublic)).item.status,'excluded');
 const seoul=await seed('seoul-live','seoul_reservation'),seoulPid=await publicRow('seoul-live',true,'seoul_reservation');
 await fail(()=>q('select machimoa_review.admin_trash_lock($1,$2,$3)',[seoul,f.revision,actor]),'PT409','trash_already_published');
 await q('update public.curations set is_published=false where id=$1',[seoulPid]);
 await q('select machimoa_review.admin_trash_lock($1,$2,$3)',[seoul,f.revision,actor]);checks++;
 const unrelated=await seed('unrelated-source');await publicRow('unrelated-source',true,'youthcenter');eq((await exclude(unrelated)).item.status,'excluded');
 // Both list and command reflect later public visibility; historical flags stay intact.
 let e=await entry(id);await q('update public.curations set is_published=true where id=$1',[pid]);
 eq((await entry(id)).blockReason,'already_published');eq((await entry(id)).canRestore,false);
 await fail(()=>restore(e),'PT409','trash_already_published');
 await q('update public.curations set is_published=false where id=$1',[pid]);eq((await entry(id)).canRestore,true);
 result=await restore(await entry(id));eq(result.item.restoredReviewPending,true);eq(result.item.facts,facts);
 eq(await q('select * from machimoa_review.curation_candidates where id=$1',[cid]),histBefore);
 // Existing adjacent worker, revision, expiry and role protections remain.
 const worker=await seed('worker-protected');await f.job(worker,'claimed');await fail(()=>exclude(worker),'PT409','trash_processing_active');
 const changed=await seed('revision-protected');await exclude(changed);e=await entry(changed);
 await q("update machimoa_review.source_items set revision_hash=repeat('c',64) where id=$1",[changed]);eq((await entry(changed)).blockReason,'source_changed');await fail(()=>restore(e),'PT409','trash_source_changed');
 const expired=await seed('expiry-protected');await exclude(expired);e=await entry(expired);
 await q(`with t as(select clock_timestamp() stamp) update machimoa_review.admin_exclusion_episodes set excluded_at=t.stamp-interval '72 hours',expires_at=t.stamp from t where id=$1`,[e.id]);eq(await entry(expired),undefined);await fail(()=>restore(e),'PT409','trash_expired');
 for(const role of ['anon','authenticated']){
  await f.db.exec(`set role ${role}`);await fail(()=>q('select public.admin_review_trash(0,25)'),'42501');await f.db.exec('reset role');
 }
 for(const role of ['anon','authenticated','service_role'])eq((await q(`select has_function_privilege($1,'machimoa_review.admin_trash_publication_ids(uuid)','EXECUTE') allowed`,[role]))[0].allowed,false);
 const changedFunctions=new Set(['machimoa_review.admin_trash_lock(uuid,text,uuid)','admin_review_trash(integer,integer)','machimoa_review.apply_ingest_review_decision(uuid,text,text,text,text,text[],text[],text,text,text)']);
 let preserved=0;
 for(const fn of beforeFunctions){
  const current=(await q('select pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where oid=$1::regprocedure',[fn.signature]))[0];
  eq(current.acl,fn.acl);
  if(!changedFunctions.has(fn.signature)){eq(current.definition,fn.definition);preserved++;}
 }
 console.log(JSON.stringify({result:'pass',checks,preservedFunctions:preserved,environment:'new isolated in-memory PostgreSQL; synthetic content/admin only',operationalWrites:false,independentConnectionConcurrency:false}));
}finally{await f.db.close();}
