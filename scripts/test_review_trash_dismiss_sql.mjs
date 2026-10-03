// New isolated in-memory PostgreSQL per run; no URLs, providers or shared DB.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
const f=await reviewDatabase(),q=f.query,rpc=f.rpc;
const actor=randomUUID(),other=randomUUID();let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const fail=async(fn,code)=>{await assert.rejects(fn,e=>e.code===code);checks++;};
const list=()=>rpc('admin_review_trash',[0,25]);
const preview=()=>rpc('admin_review_trash_dismiss_preview',[]);
const dismiss=(e,request=randomUUID(),who=actor)=>rpc('admin_review_trash_dismiss',['dismiss',e.id,e.dismissVersion,who,request]);
const empty=(p,request=randomUUID())=>rpc('admin_review_trash_dismiss',['empty',null,p.version,actor,request]);
async function seed(key,origin='youthcenter_policy') {
 const id=await f.source(key,origin);
 await q(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes) values($1,$2,'content_review','queued',now(),now(),array['policy_lifecycle_uncertain'])`,[id,f.revision]);
 const i=await rpc('admin_review_detail',['facts',id]);
 await rpc('admin_review_exclude_reason',[id,i.revision,i.version,'service_not_suitable','',actor,randomUUID()]);
 return (await list()).items.find(e=>e.sourceItemId===id);
}
try {
 for(const n of ['20261002000100_admin_review_trash.sql','20261002000200_admin_review_trash_publication.sql','20261003000500_admin_review_trash_dismiss.sql']) await f.db.exec(await readFile(new URL('../supabase/migrations/'+n,import.meta.url),'utf8'));
 eq((await preview()).count,0);await fail(async()=>empty(await preview()),'PT409');
 const a=await seed('single'),req=randomUUID();
 const preserved=await q(`select to_jsonb(s) source,(select jsonb_agg(to_jsonb(j) order by j.id) from machimoa_review.processing_jobs j where source_item_id=s.id) jobs,(select jsonb_agg(to_jsonb(e) order by e.id) from machimoa_review.admin_review_events e where source_item_id=s.id) history from machimoa_review.source_items s where id=$1`,[a.sourceItemId]);
 eq(await dismiss(a,req),{action:'dismiss',count:1,episodeId:a.id});
 eq((await list()).items,[]);eq((await preview()).count,0);
 eq(await dismiss(a,req),{action:'dismiss',count:1,episodeId:a.id});
 await fail(()=>dismiss(a),'PT409');await fail(()=>dismiss(a,req,other),'PT422');
 await fail(()=>rpc('admin_review_restore',[a.id,a.revision,a.version,actor,randomUUID()]),'PT409');
 eq(await q(`select to_jsonb(s) source,(select jsonb_agg(to_jsonb(j) order by j.id) from machimoa_review.processing_jobs j where source_item_id=s.id) jobs,(select jsonb_agg(to_jsonb(e) order by e.id) from machimoa_review.admin_review_events e where source_item_id=s.id) history from machimoa_review.source_items s where id=$1`,[a.sourceItemId]),preserved);
 eq((await q('select count(*)::int n from machimoa_review.admin_trash_dismissals'))[0].n,1);
 const b=await seed('blocked','youthcenter_content');
 await q('update machimoa_review.source_items set revision_hash=repeat(\'b\',64) where id=$1',[b.sourceItemId]);
 eq((await list()).items[0].canRestore,false);eq((await dismiss(b)).count,1);
 const working=await seed('worker-blocked');await f.job(working.sourceItemId,'claimed');
 eq((await list()).items[0].canRestore,false);const jobs=await q('select to_jsonb(j) value from machimoa_review.processing_jobs j where source_item_id=$1 order by id',[working.sourceItemId]);
 eq((await dismiss(working)).count,1);eq(await q('select to_jsonb(j) value from machimoa_review.processing_jobs j where source_item_id=$1 order by id',[working.sourceItemId]),jobs);
 const samples=JSON.parse(execFileSync(process.env.MACHIMOA_TEST_PYTHON,['-X','utf8','scripts/test_program_db.py','--fixtures'],{encoding:'utf8'}));
 const facts=structuredClone(samples.storageFixtures.find(x=>x.name==='personal').item.program_facts);
 for(const [key,p] of Object.entries(facts.periods)){p.value=key.endsWith('BGNDT')?'2020-01-01':'2099-12-31';p.raw=p.value;p.precision='day';p.status='ok';}
 facts.activity_region='unknown';facts.activity_evidence=[];
 const pg=await f.source('seoul-dismiss','seoul_reservation');
 await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[pg,JSON.stringify({title:'서울 합성 제외',source_url:facts.official_url,program_text:'합성 개최지 원문',provider_fields:{MAXCLASSNM:'문화체험'}})]);
 await q(`insert into machimoa_review.source_item_program_facts(source_item_id,revision_hash,source_snapshot,observed_facts,facts) values($1,$2,'{}',$3,$3)`,[pg,f.revision,JSON.stringify(facts)]);
 await q('select machimoa_review.program_refresh($1)',[pg]);const pi=await rpc('admin_program_detail',[pg]);
 await rpc('admin_review_exclude_reason',[pg,pi.revision,pi.version,'service_not_suitable','',actor,randomUUID()]);
 const pe=(await list()).items.find(x=>x.sourceItemId===pg),programBefore=await q('select to_jsonb(p) value from machimoa_review.source_item_program_facts p where source_item_id=$1',[pg]);
 eq(pe.sourceName,'seoul_reservation');eq((await dismiss(pe)).count,1);
 eq(await q('select to_jsonb(p) value from machimoa_review.source_item_program_facts p where source_item_id=$1',[pg]),programBefore);
 const c=await seed('restored');await rpc('admin_review_restore',[c.id,c.revision,c.version,actor,randomUUID()]);await fail(()=>dismiss(c),'PT409');
 const current=await rpc('admin_review_detail',['facts',c.sourceItemId]);await rpc('admin_review_exclude_reason',[current.id,current.revision,current.version,'region_not_suitable','',actor,randomUUID()]);
 const second=(await list()).items[0];assert.notEqual(second.id,c.id);checks++;await fail(()=>dismiss(c),'PT409');eq((await list()).items[0].id,second.id);
 const old=await preview();const extra=await seed('new-after-confirmation');await fail(()=>empty(old),'PT409');eq((await preview()).count,2);
 const exp=await preview();await q(`update machimoa_review.admin_exclusion_episodes set excluded_at=clock_timestamp()-interval '73 hours',expires_at=clock_timestamp()-interval '1 hour' where id=$1`,[extra.id]);
 await fail(()=>empty(exp),'PT409');await fail(()=>dismiss(extra),'PT409');
 // Multi-page full set, including recovery-blocked entries. No browser ID list.
 for(let i=0;i<27;i++)await seed('multi-'+i);
 eq((await list()).items.length,25);const all=await preview();eq(all.count,28);
 const bulkRequest=randomUUID();eq((await empty(all,bulkRequest)).count,28);eq((await preview()).count,0);eq((await list()).items,[]);
 eq((await empty(all,bulkRequest)).count,28);eq((await q('select count(*)::int n from machimoa_review.admin_trash_dismissals'))[0].n,32);
 await fail(()=>rpc('admin_review_restore',[second.id,second.revision,second.version,actor,randomUUID()]),'PT409');
 const restoredDuringConfirmation=await seed('restored-after-preview'),restorePreview=await preview();
 await rpc('admin_review_restore',[restoredDuringConfirmation.id,restoredDuringConfirmation.revision,restoredDuringConfirmation.version,other,randomUUID()]);
 await fail(()=>empty(restorePreview),'PT409');eq((await preview()).count,0);
 const boundary=await seed('exact-72h');await q(`with stamp as(select clock_timestamp() t) update machimoa_review.admin_exclusion_episodes set excluded_at=stamp.t-interval '72 hours',expires_at=stamp.t from stamp where id=$1`,[boundary.id]);
 eq((await list()).items,[]);await fail(()=>dismiss(boundary),'PT409');await fail(()=>rpc('admin_review_restore',[boundary.id,boundary.revision,boundary.version,actor,randomUUID()]),'PT409');
 // Failed transaction cannot leave partial dismissals or a success request record.
 const atomic=await seed('atomic');await seed('atomic-second');await seed('atomic-third');
 await f.db.exec(`create function public.test_dismiss_failure() returns trigger language plpgsql as $$begin if exists(select 1 from machimoa_review.admin_trash_dismissals where request_id=new.request_id) then raise exception 'synthetic second-row failure';end if;return new;end$$;create trigger test_dismiss_failure before insert on machimoa_review.admin_trash_dismissals for each row execute function public.test_dismiss_failure();`);
 const failed=randomUUID();await fail(async()=>empty(await preview(),failed),'P0001');eq((await preview()).count,3);eq((await q('select count(*)::int n from machimoa_review.admin_trash_dismiss_requests where request_id=$1',[failed]))[0].n,0);eq((await q('select count(*)::int n from machimoa_review.admin_trash_dismissals where request_id=$1',[failed]))[0].n,0);
 await f.db.exec('drop trigger test_dismiss_failure on machimoa_review.admin_trash_dismissals;drop function public.test_dismiss_failure();');
 // Bound the full-set lock/write operation without accepting partial processing.
 await q(`with stamp as(select clock_timestamp() t) insert into machimoa_review.admin_exclusion_episodes(source_item_id,revision_hash,source_name,title,reason_code,note,actor,excluded_at,expires_at,prior_jobs,prior_decisions) select gen_random_uuid(),$1,'youthcenter_policy','bulk-limit-fixture','service_not_suitable','합성 제한 확인',$2,stamp.t,stamp.t+interval '72 hours','[]','[]' from generate_series(1,5001),stamp`,[f.revision,actor]);
 const oversized=await preview(),oversizedRequest=randomUUID();eq(oversized.count,5004);await fail(()=>empty(oversized,oversizedRequest),'PT422');
 eq((await preview()).count,5004);eq((await q('select count(*)::int n from machimoa_review.admin_trash_dismiss_requests where request_id=$1',[oversizedRequest]))[0].n,0);
 await q(`with stamp as(select clock_timestamp() t) update machimoa_review.admin_exclusion_episodes set excluded_at=stamp.t-interval '72 hours',expires_at=stamp.t from stamp where title='bulk-limit-fixture'`);
 for(const role of ['anon','authenticated']){await f.db.exec(`set role ${role}`);await fail(()=>q('select public.admin_review_trash_dismiss_preview()'),'42501');await fail(()=>q('select * from machimoa_review.admin_trash_dismissals'),'42501');await f.db.exec('reset role');}
 const acl=await q(`select n.nspname,p.proname,has_function_privilege('anon',p.oid,'execute') a,has_function_privilege('authenticated',p.oid,'execute') u,has_function_privilege('service_role',p.oid,'execute') s from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.proname like 'admin_trash_%dismiss%' or p.proname in ('admin_review_trash_dismiss','admin_review_trash_dismiss_preview')`);
 for(const r of acl){eq(r.a,false);eq(r.u,false);eq(r.s,r.nspname==='public');}
 await f.db.exec(await readFile(new URL('../supabase/rollback/20261003000500_admin_review_trash_dismiss_down.sql',import.meta.url),'utf8'));
 eq((await list()).items.length,3);await fail(()=>rpc('admin_review_restore',[a.id,a.revision,a.version,actor,randomUUID()]),'PT409');await fail(()=>preview(),'42501');
 console.log(JSON.stringify({result:'pass',checks,environment:'new isolated PGlite only',atomicId:atomic.id}));
} finally {await f.db.close();}


