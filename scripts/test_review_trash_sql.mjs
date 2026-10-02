// A new in-memory PostgreSQL instance only. No DB URL, OAuth, worker or AI calls.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
let checks=0;
const eq=(a,b,message)=>{assert.deepEqual(a,b,message);checks++;};
const ok=(a,message)=>{assert.ok(a,message);checks++;};
const fail=async(fn,code)=>{await assert.rejects(fn,e=>e.code===code);checks++;};
const f=await reviewDatabase(),actor='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002';
const q=f.query,rpc=f.rpc;
const get=id=>rpc('admin_review_detail',['facts',id]);
const trash=()=>rpc('admin_review_trash',[0,25]);
const exclude=(id,item,reason='service_not_suitable',note='',request=randomUUID(),who=actor)=>rpc('admin_review_exclude_reason',[id,item.revision,item.version,reason,note,who,request]);
const restore=(e,request=randomUUID(),who=actor)=>rpc('admin_review_restore',[e.id,e.revision,e.version,who,request]);
const entry=async id=>(await trash()).items.find(e=>e.sourceItemId===id);
const countEvents=async id=>(await q('select count(*)::int n from machimoa_review.admin_review_events where source_item_id=$1',[id]))[0].n;
async function seed(key,origin='youthcenter_policy'){
 const id=await f.source(key,origin);
 await q(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes) values($1,$2,'content_review','queued',clock_timestamp(),clock_timestamp(),array['policy_lifecycle_uncertain','user_category_unconfirmed'])`,[id,f.revision]);return id;
}
async function seedComplete(key){
 const id=await seed(key);let item=await get(id);
 item=await rpc('admin_review_save_facts',[id,item.revision,item.version,JSON.stringify({...item.facts,productType:'policy_reference',scope:'nationwide',foreignEligibility:'eligible',evidence:'합성 원문 전국 참여'}),actor]);
 item=await rpc('admin_review_save_facts',[id,item.revision,item.version,JSON.stringify({...item.facts,category:'policy'}),actor]);
 item=await rpc('admin_review_save_facts',[id,item.revision,item.version,JSON.stringify({...item.facts,deadlineKind:'none'}),actor]);
 eq(item.status,'resolved');
 await q(`update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp() where source_item_id=$1 and processing_stage='ai_enrichment'`,[id]);
 await q(`update machimoa_review.processing_jobs set status='queued',completed_at=null,reason_codes=array['region_scope_unknown'] where source_item_id=$1 and processing_stage='content_review'`,[id]);
 return id;
}
try{
 const legacyId=await seed('legacy-existing-exclusion');const legacyBefore=await get(legacyId);
 await rpc('admin_review_exclude',[legacyId,legacyBefore.revision,legacyBefore.version,'기존 수동 제외 기록',actor]);
 await f.db.exec(await readFile(new URL('../supabase/migrations/20261002000100_admin_review_trash.sql',import.meta.url),'utf8'));
 await f.db.exec(await readFile(new URL('../supabase/migrations/20261002000200_admin_review_trash_publication.sql',import.meta.url),'utf8'));
 await q("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial'"); // Synthetic settings only.
 eq((await trash()).items,[]);
 eq((await get(legacyId)).status,'excluded');
 // Role/ACL boundaries, no new direct grants or privileged old exclusion bypass.
 for(const role of ['anon','authenticated']){
  await f.db.exec(`set role ${role}`);await fail(()=>q('select public.admin_review_trash(0,25)'),'42501');await f.db.exec('reset role');
 }
 const acl=await q(`select n.nspname,p.proname,has_function_privilege('anon',p.oid,'EXECUTE') a,has_function_privilege('authenticated',p.oid,'EXECUTE') u,has_function_privilege('service_role',p.oid,'EXECUTE') s from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.proname like 'admin_trash_%' or p.proname in ('admin_review_trash','admin_review_exclude_reason','admin_review_restore','admin_review_save_restored','admin_program_save_restored','admin_review_exclude_before_trash','admin_program_exclude_before_trash')`);
 for(const row of acl){eq(row.a,false);eq(row.u,false);eq(row.s,row.nspname==='public');}
 eq((await q(`select has_table_privilege('service_role','machimoa_review.admin_exclusion_episodes','SELECT') a,has_table_privilege('authenticated','machimoa_review.admin_exclusion_requests','INSERT') b`))[0],{a:false,b:false});
 const id=await seed('policy-main'),before=await get(id),request=randomUUID();
 const factSnapshot=JSON.stringify(before.facts);
 let excluded=await exclude(id,before,'service_not_suitable','',request);
 eq(excluded.item.status,'excluded');eq(JSON.stringify(excluded.item.facts),factSnapshot);eq(excluded.item.history[0].note,'서비스에 적합하지 않음');
 eq((await rpc('admin_review_list',['facts',0,25])).some(x=>x.id===id),false);
 let e=await entry(id);ok(e.canRestore);eq(Date.parse(e.expiresAt)-Date.parse(e.excludedAt),72*3600000);
 const n=await countEvents(id),stamp=e.excludedAt;
 eq(await exclude(id,before,'service_not_suitable','',request),excluded);eq(await countEvents(id),n);eq((await entry(id)).excludedAt,stamp);
 await fail(()=>exclude(id,before,'region_not_suitable','',request),'PT422');
 await fail(()=>exclude(id,before,'service_not_suitable','','00000000-0000-4000-8000-000000000010',other),'PT409');
 const restoreId=randomUUID();let restored=await restore(e,restoreId);
 eq(restored.item.status,'open');eq(restored.item.restoredReviewPending,true);eq(JSON.stringify(restored.item.facts),factSnapshot);
 eq(await entry(id),undefined);eq((await rpc('admin_review_list',['facts',0,25])).some(x=>x.id===id),true);
 eq(await restore(e,restoreId),restored);await fail(()=>restore(e),'PT409');
 await fail(()=>exclude(id,before,'service_not_suitable','',request),'PT409');
 const reevaluate=async sid=>{
  const [p]=await q('select * from machimoa_review.source_item_product_types where source_item_id=$1',[sid]);
  await q('select machimoa_review.apply_source_item_evaluation($1,$2,$3,$4,$5)',[sid,f.revision,p?.product_type??null,p?.reason_codes??[],p?.gate_facts?JSON.stringify(p.gate_facts):null]);
 };
 await reevaluate(id);ok((await get(id)).restoredReviewPending);ok((await get(id)).reasons.includes('restored_review_pending'));
 eq((await q(`select count(*)::int n from machimoa_review.processing_jobs where source_item_id=$1 and processing_stage='ai_enrichment' and status in ('queued','claimed')`,[id]))[0].n,0);
 restored.item=await get(id);
 const modified=await rpc('admin_review_save_restored',[id,restored.item.revision,restored.item.version,JSON.stringify({...restored.item.facts,productType:'policy_reference',scope:'nationwide',foreignEligibility:'eligible',evidence:'합성 전국 이용 근거'}),actor]);
 eq(modified.restoredReviewPending,false);eq(modified.status,'open');ok(modified.reasons.includes('user_category_unconfirmed'));
 // Complete facts, unchanged confirmation and cancelled candidate safety.
 const fullId=await seedComplete('policy-full'),full=await get(fullId);
 const candidate=await f.candidate('policy-full');
 excluded=await exclude(fullId,full,'region_not_suitable');eq(excluded.item.history[0].note,'대상 지역이 아님');
 eq((await q('select review_status from machimoa_review.curation_candidates where id=$1',[candidate]))[0].review_status,'rejected');
 const fullEntry=await entry(fullId);restored=await restore(fullEntry);await reevaluate(fullId);
 let current=await get(fullId);eq(current.status,'open');eq(current.restoredReviewPending,true);eq(current.facts,full.facts);
 await q('select machimoa_review.ensure_ai_enrichment_job($1,$2,$3)',[fullId,f.revision,[]]);eq((await get(fullId)).aiStatus,'cancelled');
 current=await get(fullId);
 const confirmed=await rpc('admin_review_save_restored',[fullId,current.revision,current.version,JSON.stringify(current.facts),actor]);
 eq(confirmed.status,'resolved');eq(confirmed.restoredReviewPending,false);eq(confirmed.aiStatus,'queued');eq(confirmed.facts,full.facts);eq(confirmed.history[0].action,'confirm_restored');
 await fail(()=>rpc('admin_review_save_restored',[fullId,current.revision,current.version,JSON.stringify(current.facts),actor]),'PT409');
 eq((await q('select review_status from machimoa_review.curation_candidates where id=$1',[candidate]))[0].review_status,'rejected');
 await fail(()=>restore(fullEntry),'PT409');
 // A restored review can be excluded again: new cycle, old requests cannot affect it.
 const cycleId=await seed('cycle'),cycle=await get(cycleId);const firstReq=randomUUID();await exclude(cycleId,cycle,'custom','직접 입력한 사유',firstReq);
 const first=await entry(cycleId);const firstRestoreReq=randomUUID();const returned=await restore(first,firstRestoreReq);
 await exclude(cycleId,returned.item);const second=await entry(cycleId);ok(second.id!==first.id);ok(Date.parse(second.excludedAt)>Date.parse(first.excludedAt));
 await fail(()=>restore(first,firstRestoreReq),'PT409');await fail(()=>exclude(cycleId,cycle,'custom','직접 입력한 사유',firstReq),'PT409');eq((await entry(cycleId)).id,second.id);
 // Valid-before deadline then at/after deadline. The DB stores historical records unchanged.
 const expiryId=await seed('expiry');await exclude(expiryId,await get(expiryId));e=await entry(expiryId);
 await q(`with t as(select clock_timestamp() stamp) update machimoa_review.admin_exclusion_episodes set excluded_at=t.stamp-interval '72 hours'+interval '3 seconds',expires_at=t.stamp+interval '3 seconds' from t where id=$1`,[e.id]);
 e=await entry(expiryId);ok(e.canRestore);
 await q(`with t as(select clock_timestamp() stamp) update machimoa_review.admin_exclusion_episodes set excluded_at=t.stamp-interval '72 hours',expires_at=t.stamp from t where id=$1`,[e.id]);
 eq(await entry(expiryId),undefined);await fail(()=>restore(e),'PT409');
 eq((await q('select count(*)::int n from machimoa_review.admin_exclusion_episodes where id=$1',[e.id]))[0].n,1);eq((await get(expiryId)).status,'excluded');
 // Simulated elapsed time after source/job locks. Not an independent connection lock race.
 const delayId=await seed('deadline-after-lock');await exclude(delayId,await get(delayId));const delay=await entry(delayId);
 await f.db.exec(`alter function machimoa_review.admin_trash_lock(uuid,text,uuid) rename to local_trash_lock_original;
 create function machimoa_review.admin_trash_lock(p_id uuid,p_revision text,p_actor uuid) returns void language plpgsql security definer set search_path='' as $$
 declare stop_at timestamptz;begin perform machimoa_review.local_trash_lock_original(p_id,p_revision,p_actor);
 if p_id='${delayId}' then stop_at:=clock_timestamp()+interval '60 milliseconds';while clock_timestamp()<stop_at loop null;end loop;end if;end$$;
 revoke all on function machimoa_review.admin_trash_lock(uuid,text,uuid) from public,anon,authenticated,service_role;`);
 await q(`with t as(select clock_timestamp() stamp) update machimoa_review.admin_exclusion_episodes set excluded_at=t.stamp-interval '72 hours'+interval '40 milliseconds',expires_at=t.stamp+interval '40 milliseconds' from t where id=$1`,[delay.id]);
 const afterLock=(await q('select machimoa_review.admin_trash_version($1) version',[delay.id]))[0].version;
 await fail(()=>restore({...delay,version:afterLock}),'PT409');eq((await get(delayId)).status,'excluded');
 await f.db.exec('drop function machimoa_review.admin_trash_lock(uuid,text,uuid);alter function machimoa_review.local_trash_lock_original(uuid,text,uuid) rename to admin_trash_lock');
 // Revision changes block old restore; deleted sources are represented safely by LEFT JOIN.
 const changedId=await seed('changed');await exclude(changedId,await get(changedId));const old=await entry(changedId);
 await q("update machimoa_review.source_items set revision_hash=repeat('b',64) where id=$1",[changedId]);
 eq((await entry(changedId)).blockReason,'source_changed');await fail(()=>restore(old),'PT409');
 await q(`insert into machimoa_review.admin_exclusion_episodes(source_item_id,revision_hash,source_name,title,reason_code,note,actor,excluded_at,expires_at,prior_jobs,prior_decisions) select $1,$2,'youthcenter_content','삭제된 합성 원본','custom','기록',$3,t.stamp,t.stamp+interval '72 hours','[]','[]' from (select clock_timestamp() stamp)t`,[randomUUID(),f.revision,actor]);
 eq((await trash()).items.find(x=>x.title==='삭제된 합성 원본').blockReason,'source_missing');
 // Worker/published restrictions and transaction rollback on audit failure.
 const worker=await seed('worker');await f.job(worker,'claimed');await fail(async()=>exclude(worker,await get(worker)),'PT409');eq(await entry(worker),undefined);
 const published=await seed('published');const publishedCandidate=await f.candidate('published');
 await q("update machimoa_review.curation_candidates set review_status='published',published_at=clock_timestamp(),reviewed_at=clock_timestamp(),reviewed_by=$2 where id=$1",[publishedCandidate,actor]);
 await q("insert into public.curations(slug,source,source_item_id,title,content,is_published) values('published','youthcenter','published','합성 공개 제목','합성 공개 본문',true)");
 await fail(async()=>exclude(published,await get(published)),'PT409');eq(await entry(published),undefined);
 const restoreRestricted=await seed('restore-restricted');await exclude(restoreRestricted,await get(restoreRestricted));
 let restricted=await entry(restoreRestricted);await f.job(restoreRestricted,'claimed');
 eq((await entry(restoreRestricted)).blockReason,'processing_active');await fail(()=>restore(restricted),'PT409');
 await q("update machimoa_review.processing_jobs set status='cancelled' where source_item_id=$1 and processing_stage='ai_enrichment'",[restoreRestricted]);
 const restrictedCandidate=await f.candidate('restore-restricted');
 await q("update machimoa_review.curation_candidates set review_status='published',published_at=clock_timestamp(),reviewed_at=clock_timestamp(),reviewed_by=$2 where id=$1",[restrictedCandidate,actor]);
 await q("insert into public.curations(slug,source,source_item_id,title,content,is_published) values('restore-restricted','youthcenter','restore-restricted','합성 공개 제목','합성 공개 본문',true)");
 eq((await entry(restoreRestricted)).blockReason,'already_published');await fail(()=>restore(restricted),'PT409');
 eq((await get(restoreRestricted)).status,'excluded');
 const atomic=await seed('atomic'),atomicBefore=await get(atomic);
 await f.db.exec(`create function machimoa_review.local_fail_episode() returns trigger language plpgsql as $$begin raise exception 'synthetic audit failure';end$$;create trigger local_fail before insert on machimoa_review.admin_exclusion_episodes for each row execute function machimoa_review.local_fail_episode();`);
 await fail(()=>exclude(atomic,atomicBefore),'P0001');eq(await get(atomic),atomicBefore);
 await f.db.exec('drop trigger local_fail on machimoa_review.admin_exclusion_episodes;drop function machimoa_review.local_fail_episode()');
 // Seoul retains actual facts/evidence; shared refresh cannot bypass human confirmation.
 const samples=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','scripts/test_program_db.py','--fixtures'],{encoding:'utf8'}));
 const facts=structuredClone(samples.storageFixtures.find(x=>x.name==='personal').item.program_facts);
 for(const [key,p] of Object.entries(facts.periods)){p.value=key.endsWith('BGNDT')?'2020-01-01':'2099-12-31';p.raw=p.value;p.precision='day';p.status='ok';}
 async function program(key,changes={}){
  const id=await f.source(key,'seoul_reservation');const ff={...facts,...changes};
  await q(`update machimoa_review.source_items set normalized_payload=$2 where id=$1`,[id,JSON.stringify({title:key,source_url:ff.official_url,program_text:'합성 개최지 원문',provider_fields:{MAXCLASSNM:'문화체험'}})]);
  await q(`insert into machimoa_review.source_item_program_facts(source_item_id,revision_hash,source_snapshot,observed_facts,facts) values($1,$2,'{}',$3,$3)`,[id,f.revision,JSON.stringify(ff)]);
  await q('select machimoa_review.program_refresh($1)',[id]);return id;
 }
 const pg=await program('서울 장소 확인',{activity_region:'unknown',activity_evidence:[]});let pi=await rpc('admin_program_detail',[pg]);eq(pi.status,'open');
 const initialFacts=structuredClone(pi.facts);await exclude(pg,pi,'custom','서울 직접 제외');e=await entry(pg);restored=await restore(e);
 eq(restored.item.facts,initialFacts);eq(restored.item.restoredReviewPending,true);
 await q('select machimoa_review.program_refresh($1)',[pg]);pi=await rpc('admin_program_detail',[pg]);ok(pi.result.reasons.includes('restored_review_pending'));
 await fail(()=>rpc('admin_program_save_restored',[pg,pi.revision,pi.version,JSON.stringify({application_actor:'institution'}),[], '권한 밖 변경',actor]),'PT422');
 pi=await rpc('admin_program_save_restored',[pg,pi.revision,pi.version,JSON.stringify({activity_region:'capital',activity_evidence:['합성 개최지 서울 확인']}),[],'합성 원문 근거',actor]);
 eq(pi.restoredReviewPending,false);eq(pi.status,'resolved');eq(pi.aiStatus,'queued');
 // Synthetic legacy-complete program held in human review: no facts change required to confirm.
 const pgFull=await program('서울 수정 없는 확인');
 await q(`update machimoa_review.source_item_program_facts set result=jsonb_build_object('decision','review_required','disposition','observe_only','reasons',jsonb_build_array('activity_location_unknown')) where source_item_id=$1`,[pgFull]);
 await q(`update machimoa_review.processing_jobs set status='cancelled' where source_item_id=$1 and processing_stage='ai_enrichment'`,[pgFull]);
 await q(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes) values($1,$2,'content_review','queued',now(),now(),array['activity_location_unknown'])`,[pgFull,f.revision]);
 pi=await rpc('admin_program_detail',[pgFull]);const intact=pi.facts;await exclude(pgFull,pi);await restore(await entry(pgFull));await q('select machimoa_review.program_refresh($1)',[pgFull]);
 pi=await rpc('admin_program_detail',[pgFull]);eq(pi.status,'open');eq(pi.aiStatus,'cancelled');eq(pi.facts,intact);
 eq(await rpc('claim_seoul_program_ai',[pgFull,f.revision,'local-worker',300]),[]);
 await fail(()=>rpc('admin_program_save_restored',[pgFull,pi.revision,pi.version,'{}',['activity_location_unknown'],'',actor]),'PT422');
 pi=await rpc('admin_program_save_restored',[pgFull,pi.revision,pi.version,'{}',[],'복구 후 사실 재확인',actor]);eq(pi.status,'resolved');eq(pi.aiStatus,'queued');eq(pi.facts,intact);
 // Read-only list and expired visibility never delete or mutate history.
 const history=await q('select * from machimoa_review.admin_review_events order by id');await trash();await trash();eq(await q('select * from machimoa_review.admin_review_events order by id'),history);
 for(const name of ['claim_processing_jobs','claim_seoul_program_ai','finish_seoul_program_ai','fail_seoul_program_ai','observe_seoul_program','program_ai_check','publish_curation_candidate']){
  const baseline=f.baseline.filter(x=>x.proname===name);const now=await q('select pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where proname=$1 order by oid',[name]);
  eq(now,baseline.map(x=>({definition:x.definition,acl:x.acl})),name+' untouched');
 }
 console.log(JSON.stringify({result:'pass',checks,environment:'fresh in-memory PostgreSQL; synthetic facts/auth only',independentConnections:false}));
}catch(e){console.error(JSON.stringify({message:e.message,code:e.code,where:e.where,detail:e.detail,stack:e.stack?.split("\n").slice(0,12),checks}));process.exitCode=1;}finally{await f.db.close();}
