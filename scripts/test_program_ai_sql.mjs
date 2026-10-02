// New in-memory PostgreSQL + synthetic pre-P0 schema. No URL, secrets, API or provider.
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { pathToFileURL, fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
const { PGlite } = await import(pathToFileURL(process.env.MACHIMOA_PGLITE_MODULE).href);
const python = process.env.MACHIMOA_TEST_PYTHON;
if (!python) throw new Error("Local test Python path required; no DB connection accepted.");
const db = new PGlite();
const root = new URL("../supabase/migrations/", import.meta.url);
const samples = JSON.parse(execFileSync(python,["-X","utf8","test_program_db.py","--fixtures"],{cwd:fileURLToPath(new URL("./",import.meta.url)),encoding:"utf8"}));
const q=async(sql,args=[]) => (await db.query(sql,args)).rows;
const rpc=(name,args) => db.transaction(async tx=> {
  await tx.exec("set local role service_role");
  return (await tx.query(`select public.${name}(${args.map((_,i)=>`$${i+1}`).join(",")}) value`,args)).rows[0].value;
});
let checks=0;
const check=(value)=> {assert.ok(value);checks++;};
const fail=async(action,code)=> {await assert.rejects(action,e=>e.code===code);checks++;};
const actor="00000000-0000-4000-8000-000000000001";
const worker="ingest-program-worker";
const packet=(c)=> JSON.parse(execFileSync(python,["-X","utf8","test_program_ai.py","--packet"],{
  cwd:fileURLToPath(new URL("./",import.meta.url)),input:JSON.stringify(c),encoding:"utf8"}));
const finish=(p)=>rpc("finish_seoul_program_ai",[p.p_job_id,p.p_revision,p.p_facts_version,p.p_claimed_at,p.p_lease_until,p.p_worker_id,JSON.stringify(p.p_output)]);
const claim=async id=> {
 const revision=(await q("select revision_hash from machimoa_review.source_items where id=$1",[id]))[0].revision_hash;
 return rpc("claim_seoul_program_ai",[id,revision,worker,600]);
};
let run;
async function seed(name,change=(x)=>x,fixture="personal") {
 const item=structuredClone(samples.storageFixtures.find(f=>f.name===fixture).item);
 item.external_key=name;item.revision_hash=createHash("sha256").update(name).digest("hex");
 item.normalized_payload.provider_fields.SVCID=name;
 item.normalized_payload.source_url=item.program_facts.official_url=`https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=${name}`;
 change(item);
 return (await rpc("observe_seoul_program",[run,JSON.stringify([item]),null]))[0].id;
}
try {
 await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;
 create table public.curations(id uuid primary key default gen_random_uuid(),slug text not null unique,category text,
 title text not null,summary text,content text not null,created_at timestamptz not null default now());
 alter table public.curations enable row level security;
 insert into public.curations(slug,title,summary,content) values('baseline-one','one','one','one'),('baseline-two','two','two','two');`);
 const files=(await readdir(root)).filter(n=>n.endsWith(".sql") &&
 (n>="20260827022301"&&n<"20260903"||n>="20260913"&&n<="20261001000001_seoul_program_ai.sql")).sort();
 const defsSql=`select p.proname,pg_get_functiondef(p.oid) definition,p.proacl::text acl from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='machimoa_review' and p.proname in ('claim_processing_jobs','enqueue_curation_candidate','publish_curation_candidate','fail_processing_job','complete_processing_job') order by p.proname`;
 let legacyDefs;
 for(const name of files) {
  if(name==='20261001000001_seoul_program_ai.sql')legacyDefs=await q(defsSql);
  await db.exec(await readFile(new URL(name,root),'utf8'));
  if(name.startsWith('20260827022301'))await db.exec(`insert into machimoa_review.curation_candidates
  (source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status)
  select 'youthcenter','baseline-'||n,repeat('a',64),'baseline-candidate-'||n,'title','summary','content','{}','success' from generate_series(1,4)n;`);
 }
 assert.deepEqual(await q(defsSql),legacyDefs);checks++;
 check((await q("select enabled,permission_status from machimoa_review.ingest_sources where source_id='seoul_reservation'"))[0].enabled===false);
 // Verify clean rollback before any new references, then restore only the new migration.
 const rollback=await readFile(new URL('../supabase/rollback/20261001000001_seoul_program_ai_down.sql',import.meta.url),'utf8');
 await db.exec(rollback);check((await q("select machimoa_review.canonical_source_id('seoul_reservation') value"))[0].value===null);
 await db.exec(await readFile(new URL('20261001000001_seoul_program_ai.sql',root),'utf8'));
 for(const role of ['anon','authenticated'])for(const name of ['claim_seoul_program_ai','finish_seoul_program_ai','fail_seoul_program_ai']) {
  check((await q('select has_function_privilege($1,p.oid,\'execute\') allowed from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname=\'public\' and p.proname=$2',[role,name]))[0].allowed===false);
 }
 check((await q("select has_table_privilege('service_role','machimoa_review.program_candidate_inputs','select') allowed"))[0].allowed===false);
 check((await q("select machimoa_review.canonical_source_id('seoul_reservation') v"))[0].v==='seoul_reservation');
 check((await q("select machimoa_review.canonical_source_id('unknown') v"))[0].v===null);
 // Activation is test-only data inside this disposable memory DB, never an env/operating source change.
 await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='seoul_reservation'");
 run=(await q("select * from public.start_ingest_run('seoul_reservation',120)"))[0].run_id;
 if(process.argv.includes('--review-fix')) {
  let targeted=0;
  for(const reason of ['closed','disabled']) {
   const id=await seed('review_'+reason);const c=(await claim(id))[0];const p=packet(c);
   await q("update machimoa_review.processing_jobs set claim_lease_until=clock_timestamp()-interval '1 second' where id=$1",[c.jobId]);
   if(reason==='closed')await q("update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{source_status}','\"reservation_closed\"') where source_item_id=$1",[id]);
   else await db.exec("update machimoa_review.ingest_sources set enabled=false where source_id='seoul_reservation'");
   assert.equal((await claim(id)).length,0);targeted++;
   assert.equal((await q('select status from machimoa_review.processing_jobs where id=$1',[c.jobId]))[0].status,'queued');targeted++;
   await q('select machimoa_review.program_refresh($1)',[id]);
   assert.equal((await q('select status from machimoa_review.processing_jobs where id=$1',[c.jobId]))[0].status,'cancelled');targeted++;
   await assert.rejects(()=>finish(p),e=>e.code==='PT409');targeted++;
   await db.exec("update machimoa_review.ingest_sources set enabled=true where source_id='seoul_reservation'");
  }
  console.log(`Program AI review-fix checks passed: ${targeted}. Expired attempt recovery only; no provider/publication.`);
 } else {
 const id=await seed('ai_personal',undefined,'family_paid');
 for(const setting of ["enabled=false","permission_status='testing_only'"]) {
  await db.exec(`update machimoa_review.ingest_sources set ${setting} where source_id='seoul_reservation'`);
  check((await claim(id)).length===0);
  await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='seoul_reservation'");
 }
 const nonculture=await seed('ai_education',x=>x.normalized_payload.provider_fields.MAXCLASSNM='교육');
 check((await claim(nonculture)).length===0);
 const school=await seed('ai_school',undefined,'school');check((await claim(school)).length===0);
 const c=(await claim(id))[0];check(c.sourceItemId===id&&c.factsVersion===1&&c.apiCategory==='문화체험');
 check(!JSON.stringify(c).includes('source_body_html'));
 check((await claim(id)).length===0);
 const p=packet(c);
 await fail(()=>finish({...p,p_facts_version:2}),'PT409');
 // Expired/reclaimed same worker ID must fence out old responses and failure reports.
 await q("update machimoa_review.processing_jobs set claim_lease_until=clock_timestamp()-interval '1 second' where id=$1",[c.jobId]);
 const c2=(await claim(id))[0];check(c2.claimedAt!==c.claimedAt);const p2=packet(c2);
 await fail(()=>finish(p),'PT409');
 await fail(()=>rpc('fail_seoul_program_ai',[c.jobId,c.claimedAt,c.leaseUntil,worker,'ai_schema_error']),'PT409');
 const result=await finish(p2);check(result.outcome==='inserted');
 const duplicate=await finish(p2);check(duplicate.outcome==='duplicate'&&duplicate.candidateId===result.candidateId);
 check((await claim(id)).length===0);
 const stored=(await q('select * from machimoa_review.curation_candidates where id=$1',[result.candidateId]))[0];
 check(stored.user_category==='program'&&stored.category==='문화체험'&&stored.review_status==='pending');
 check(stored.title===stored.title_ko&&stored.summary===stored.summary_ko&&stored.content===stored.content_ko);
 check(stored.raw_payload.apiCategory==='문화체험'&&!JSON.stringify(stored.raw_payload).includes('source_body_html'));
 check((await q("select status from machimoa_review.processing_jobs where id=$1",[c.jobId]))[0].status==='completed');
 const detail=await rpc('admin_review_detail',['candidates',result.candidateId]);
 check(detail.programInfo.canPublish&&!detail.programInfo.inputChanged&&detail.programInfo.operatingPeriod.includes('2036'));
 check((await rpc('admin_review_list',['candidates',0,25])).some(x=>x.id===result.candidateId));
 const edited={...detail.content,titleJa:'新しい題名'};
 const saved=await rpc('admin_review_save_candidate',[result.candidateId,detail.revision,detail.version,JSON.stringify(edited),actor]);
 check(saved.content.titleJa==='新しい題名'&&saved.history[0].actor===actor);
 await fail(()=>rpc('admin_review_save_candidate',[result.candidateId,detail.revision,detail.version,JSON.stringify(edited),actor]),'PT409');
 // Same-revision facts modification cannot silently authorize publication or regeneration.
 await q('update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id=$1',[id]);
 const changed=await rpc('admin_review_detail',['candidates',result.candidateId]);
 check(changed.programInfo.inputChanged&&!changed.programInfo.canPublish&&changed.version!==saved.version);
 await fail(()=>rpc('admin_review_publish',[result.candidateId,changed.revision,changed.version,actor]),'PT409');
 check((await claim(id)).length===0);
 const rejected=await rpc('admin_review_reject',[result.candidateId,changed.revision,changed.version,'합성 입력 변경 확인',actor]);
 check(rejected.status==='rejected'&&rejected.history[0].actor===actor);
 // Human supplementation can repair missing original URL without changing raw flags.
 const repair=await seed('ai_repaired_url',x=> {x.normalized_payload.source_url=null;x.has_source_url=false;x.program_facts.official_url='';});
 const before=await rpc('admin_program_detail',[repair]);
 const repaired=await rpc('admin_program_save',[repair,before.revision,before.version,JSON.stringify({official_url:'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=ai_repaired_url'}),[],'공식 링크 보완',actor]);
 check((await q('select has_source_url from machimoa_review.source_items where id=$1',[repair]))[0].has_source_url===false);
 const repairClaim=(await claim(repair))[0];check(repairClaim.factsVersion===repaired.factsVersion&&repairClaim.facts.official_url.includes('ai_repaired_url'));
 // Review correction: expiry + blocked gate must not permanently block refresh.
 await q("update machimoa_review.processing_jobs set claim_lease_until=clock_timestamp()-interval '1 second' where id=$1",[repairClaim.jobId]);
 await q("update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{source_status}','\"reservation_closed\"') where source_item_id=$1",[repair]);
 check((await claim(repair)).length===0);
 check((await q('select status from machimoa_review.processing_jobs where id=$1',[repairClaim.jobId]))[0].status==='queued');
 await q('select machimoa_review.program_refresh($1)',[repair]);
 check((await q('select status from machimoa_review.processing_jobs where id=$1',[repairClaim.jobId]))[0].status==='cancelled');
 // A partial transaction must not leave a candidate/input or mark a job complete.
 const rollbackId=await seed('ai_rollback');const rollbackC=(await claim(rollbackId))[0];const rollbackP=packet(rollbackC);
 await db.exec(`create function machimoa_review.test_ai_abort() returns trigger language plpgsql as $$begin raise exception using errcode='PT999',message='synthetic_abort';end$$;
 create trigger synthetic_abort before insert on machimoa_review.program_candidate_inputs for each row execute function machimoa_review.test_ai_abort();`);
 await fail(()=>finish(rollbackP),'PT999');
 check((await q("select count(*)::int n from machimoa_review.curation_candidates where source_item_id='ai_rollback'"))[0].n===0);
 check((await q('select status from machimoa_review.processing_jobs where id=$1',[rollbackC.jobId]))[0].status==='claimed');
 await db.exec('drop trigger synthetic_abort on machimoa_review.program_candidate_inputs;drop function machimoa_review.test_ai_abort()');
 // Gate is re-evaluated at finish, independent of stored queue eligibility.
 await q("update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{source_status}','\"reservation_closed\"') where source_item_id=$1",[rollbackId]);
 await fail(()=>finish(rollbackP),'PT409');
 await q("update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{source_status}','\"open\"') where source_item_id=$1",[rollbackId]);
 await q('update machimoa_review.source_items set revision_hash=repeat(\'b\',64) where id=$1',[rollbackId]);
 await fail(()=>finish(rollbackP),'PT409');
 // Attempt-fenced provider failure reuses retry without creating candidates.
 const retryId=await seed('ai_retry');const retryC=(await claim(retryId))[0];
 check(['queued','failed'].includes(await rpc('fail_seoul_program_ai',[retryC.jobId,retryC.claimedAt,retryC.leaseUntil,worker,'ai_http_429'])));
 check((await q("select count(*)::int n from machimoa_review.curation_candidates where source_item_id='ai_retry'"))[0].n===0);
 await assert.rejects(db.exec(rollback),/program_ai_rollback_has_references/);await db.exec('rollback');checks++;
 check((await q('select count(*)::int n from public.curations'))[0].n===2);
 assert.deepEqual(await q(defsSql),legacyDefs);checks++;
 console.log(`Program AI isolated PostgreSQL checks passed: ${checks}. Synthetic claim/candidates only; no external provider/publication.`);
 }
} catch(e) {
 console.error(`Program AI local SQL failed: ${e.code??'assertion'}; ${e.message}; ${e.where??''}`);process.exitCode=1;
} finally {await db.close();}
