// In-memory SQL, synthetic rows. Run the actual terminal fence and the hold migration.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(pathToFileURL(process.env.MACHIMOA_PGLITE_MODULE).href);
const db=new PGlite();
const migration=name=>readFile(new URL('../supabase/migrations/'+name,import.meta.url),'utf8');
try {
  await db.exec(`create role anon; create role authenticated; create role service_role;
    create schema machimoa_review; set search_path=machimoa_review;
    create table source_items(id uuid,source_id text,external_key text,revision_hash text,version int);
    create table processing_jobs(id uuid,source_item_id uuid,revision_hash text,processing_stage text,
      status text,completed_at timestamptz,error_code text,claimed_at timestamptz,claimed_by text,
      claim_lease_until timestamptz,next_retry_at timestamptz,retry_count int);
    create table source_item_program_facts(source_item_id uuid,revision_hash text);
    create table ingest_sources(source_id text,enabled bool,permission_status text,legacy_curation_source text);
    create table curation_candidates(source text,source_item_id text);
    create table program_candidate_inputs(job_id uuid);
    create table review_classification_candidates(job_id uuid);
    create table seoul_ai_no_retry_attempts(job_id uuid,claimed_at timestamptz,closed_at timestamptz,
      source_item_id uuid,revision_hash text,input_context jsonb,lease_until timestamptz,worker_id text,
      attempt text,input_snapshot jsonb,error_code text);
    create function canonical_source_id(text) returns text language sql as 'select $1';
    create function ai_recheck_pending(uuid,text) returns boolean language sql as 'select false';
    create function program_no_retry_snapshot(uuid,text) returns jsonb language sql as
      'select to_jsonb(s.version) from machimoa_review.source_items s join machimoa_review.processing_jobs j on j.source_item_id=s.id where j.id=$1';
    create function ai_recheck_base_queue(integer,integer,uuid[]) returns jsonb language sql stable as $$
      select jsonb_build_object('errorCode',case when j.error_code in ('ai_or_enqueue_failed') then j.error_code else null end)
      from machimoa_review.processing_jobs j $$;`);
  const prior=await migration('20261117102024_program_ai_terminal_failure.sql');
  const begin=prior.indexOf('create function machimoa_review.fail_program_no_retry(');
  assert.ok(begin>=0);
  await db.exec(prior.slice(begin,prior.indexOf('end $$;',begin)+7));
  await db.exec(await migration('20261124150000_program_response_hold.sql'));
  const job='10000000-0000-4000-8000-000000000001', sid='20000000-0000-4000-8000-000000000001';
  const rev='a'.repeat(64), attempt='f'.repeat(64), source='myseoul_program';
  await db.exec(`insert into source_items values('${sid}','${source}','fixture','${rev}',1);
    insert into ingest_sources values('${source}',true,'approved_noncommercial','${source}');
    insert into processing_jobs values('${job}','${sid}','${rev}','ai_enrichment','claimed',null,null,
      '2026-01-01','worker','infinity',null,0);
    insert into seoul_ai_no_retry_attempts values('${job}','2026-01-01',null,'${sid}','${rev}',
      '{"source":"myseoul_program"}','infinity','worker','${attempt}','1',null,null);`);
  const ev={stage:'summary',code:'stream_missing_completed',completedSeen:false};
  const args=[source,job,rev,'2026-01-01','infinity','worker',attempt,ev];
  const hold=(params=args,role='service_role')=>db.transaction(async tx=>{
    await tx.exec('set local role '+role);
    return (await tx.query('select public.hold_program_ai_response($1,$2,$3,$4,$5,$6,$7,$8) as receipt',params)).rows[0].receipt;
  });
  const current=async()=>(await db.query('select status,retry_count,response_hold from processing_jobs join seoul_ai_no_retry_attempts on id=job_id')).rows[0];
  for (const role of ['anon','authenticated']) await assert.rejects(hold(args,role),/permission denied/);
  await assert.rejects(hold([...args.slice(0,7),{...ev,completedSeen:true}]),/invalid_response_hold/);
  await assert.rejects(hold([...args.slice(0,6),'0'.repeat(64),ev]),/attempt_conflict/);
  await db.exec('update source_items set version=2');
  await assert.rejects(hold(),/attempt_conflict/);
  await db.exec('update source_items set version=1');
  await db.exec("alter table seoul_ai_no_retry_attempts add constraint simulate_write_failure check(response_hold is null)");
  await assert.rejects(hold(),/simulate_write_failure/);
  assert.deepEqual(await current(),{status:'claimed',retry_count:0,response_hold:null});
  await db.exec('alter table seoul_ai_no_retry_attempts drop constraint simulate_write_failure');
  const receipt=await hold();
  assert.deepEqual(receipt,{outcome:'held',jobId:job,revision:rev,attempt,evidence:ev});
  assert.deepEqual(await hold(),receipt);
  await assert.rejects(hold([...args.slice(0,7),{...ev,stage:'translation'}]),/response_hold_conflict/);
  assert.deepEqual(await current(),{status:'failed',retry_count:0,response_hold:ev});
  assert.equal((await db.query("select ai_recheck_base_queue(0,25,'{}')->>'errorCode' as code")).rows[0].code,'ai_response_held');
  console.log('PASS local hold receipt, privileges, claim/version fences, rollback, replay, retry count and queue projection');
} finally {await db.close();}
