// Fresh in-memory PostgreSQL; no connection strings, network, claim, publish or AI.
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { pathToFileURL, fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
const modulePath = process.env.MACHIMOA_PGLITE_MODULE;
const python = process.env.MACHIMOA_TEST_PYTHON;
if (!modulePath || !python) throw new Error("Set local installed PGlite module and Python paths (no DB URL).");
const { PGlite } = await import(pathToFileURL(modulePath).href);
const db = new PGlite();
const root = new URL("../supabase/migrations/", import.meta.url);
const samples = JSON.parse(execFileSync(python, ["-X", "utf8", "test_program_db.py", "--fixtures"], { cwd: fileURLToPath(new URL("./", import.meta.url)), encoding: "utf8" }));
const actor = "00000000-0000-4000-8000-000000000001";
let checks = 0;
const query = async (sql, args = []) => (await db.query(sql, args)).rows;
const rpc = (name, args) => db.transaction(async (tx) => {
  await tx.exec("set local role service_role");
  return (await tx.query(`select public.${name}(${args.map((_, i) => `$${i + 1}`).join(",")}) as value`, args)).rows[0].value;
});
async function fails(action, code) { await assert.rejects(action, (e) => e.code === code); checks++; }
try {
  // Existing explicit synthetic pre-P0 bootstrap, not a Production schema clone.
  await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;
  create table public.curations(id uuid primary key default gen_random_uuid(),slug text not null unique,category text,
  title text not null,summary text,content text not null,created_at timestamptz not null default now());
  alter table public.curations enable row level security;
  insert into public.curations(slug,title,summary,content) values('baseline-one','one','one','one'),('baseline-two','two','two','two');`);
  const files = (await readdir(root)).filter((n) => n.endsWith(".sql") &&
    (n >= "20260827022301" && n < "20260903" || n >= "20260913" && n <= "20261001000000_seoul_program_contract.sql")).sort();
  let sourceBefore,legacyFns;
  const legacyQuery=`select p.oid,pg_get_functiondef(p.oid) definition,has_function_privilege('service_role',p.oid,'EXECUTE') service
    from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_review'
    and p.proname in ('upsert_source_observations_v4','publish_curation_candidate','canonical_source_id') order by p.oid`;
  for (const name of files) {
    if(name==='20261001000000_seoul_program_contract.sql') {
      sourceBefore=await query("select * from machimoa_review.ingest_sources where source_id like 'youthcenter%'");
      legacyFns=await query(legacyQuery);
    }
    try { await db.exec(await readFile(new URL(name, root), "utf8")); }
    catch (e) { console.error(`SQL migration failed: ${name}, ${e.code}, ${e.message}, position=${e.position}, context=${e.where}`); throw e; }
    if (name.startsWith("20260827022301")) await db.exec(`insert into machimoa_review.curation_candidates
    (source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status)
    select 'youthcenter','baseline-'||n,repeat('a',64),'baseline-candidate-'||n,'title','summary','content','{}','success' from generate_series(1,4) n;`);
  }
  if (process.argv.includes('--review-fixes')) {
    for (const f of samples.reviewFixtures) {
      const actual=(await query('select machimoa_review.program_evaluate($1,$2) result',[JSON.stringify(f.facts),samples.now]))[0].result;
      assert.deepEqual(actual,f.expected);checks++;
    }
    await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='seoul_reservation'");
    const run=(await query("select * from public.start_ingest_run('seoul_reservation',120)"))[0].run_id;
    const missing=samples.storageFixtures.find(f=>f.name==='missing_venue').item;
    const pid=(await rpc('observe_seoul_program',[run,JSON.stringify([missing]),null]))[0].id;
    let detail=await rpc('admin_program_detail',[pid]);
    for (const patch of [{delivery_mode:'offline',activity_region:'not_applicable',activity_evidence:[]},
                         {delivery_mode:'offline',activity_region:'capital',activity_evidence:[]},
                         {delivery_mode:'online',activity_region:'not_applicable',activity_evidence:[]},
                         {residence_scope:'nationwide',residence_evidence:[]}]) {
      detail=await rpc('admin_program_save',[pid,detail.revision,detail.version,JSON.stringify(patch),[],'합성 공식 사실 입력',actor]);
      assert.equal(detail.status,'open');assert.equal(detail.aiStatus,'blocked');checks++;
    }
    detail=await rpc('admin_program_save',[pid,detail.revision,detail.version,JSON.stringify({residence_evidence:['전국 거주자 온라인 참여 가능']}),[],'전국 대상 공식 근거',actor]);
    assert.equal(detail.aiStatus,'queued');checks++;
    const dateItem=structuredClone(samples.storageFixtures.find(f=>f.name==='personal').item);
    dateItem.external_key='period_fix';dateItem.revision_hash='c'.repeat(64);
    dateItem.program_facts.periods.RCPTENDDT={raw:null,value:null,status:'missing',precision:null};dateItem.program_facts.missing=['period_missing_or_unparsed'];
    const dateId=(await rpc('observe_seoul_program',[run,JSON.stringify([dateItem]),null]))[0].id;
    detail=await rpc('admin_program_detail',[dateId]);
    const periods=structuredClone(detail.facts.periods);
    periods.RCPTBGNDT={raw:'2036-12-31 10:00:00',value:'2036-12-31T10:00:00+09:00',precision:'second',status:'ok'};
    periods.RCPTENDDT={raw:'2036-12-31',value:'2036-12-31',precision:'day',status:'ok'};
    const fixed=await rpc('admin_program_save',[dateId,detail.revision,detail.version,JSON.stringify({periods}),['period_missing_or_unparsed'],'동일 날짜 종료, 당일 포함 확인',actor]);
    assert.ok(!fixed.result.reasons.includes('period_order_conflict'));assert.ok(!fixed.result.reasons.includes('period_missing_or_unparsed'));checks++;
    // Removing flags must not hide another missing date in structured facts.
    const facts=structuredClone(samples.fixtures[0].item.program_facts);facts.periods.SVCOPNENDDT={raw:null,value:null,status:'missing',precision:null};facts.missing=[];
    assert.ok((await query('select machimoa_review.program_evaluate($1,$2) result',[JSON.stringify(facts),samples.now]))[0].result.reasons.includes('period_missing_or_unparsed'));checks++;
    for(const [mode,region,residence,evidence] of [['offline','not_applicable','not_stated',[]],['online','not_applicable','not_stated',[]],['online','not_applicable','nationwide',[]]]) {
      const f=structuredClone(samples.fixtures[0].item.program_facts);Object.assign(f,{delivery_mode:mode,activity_region:region,activity_evidence:[],residence_scope:residence,residence_evidence:evidence});
      assert.equal((await query('select machimoa_review.program_evaluate($1,$2) result',[JSON.stringify(f),samples.now]))[0].result.decision,'review_required');checks++;
    }
    console.log(`Independent-review regression SQL checks passed: ${checks}. Fresh isolated DB; no AI.`);
  } else {
  for (const f of samples.fixtures) {
    const actual = (await query("select machimoa_review.program_evaluate($1::jsonb,$2::timestamptz) value", [JSON.stringify(f.item.program_facts), samples.now]))[0].value;
    assert.deepEqual(actual, f.expected, f.name); checks++;
  }
  const acl = await query(`select n.nspname,p.proname,has_function_privilege('anon',p.oid,'EXECUTE') anon,
  has_function_privilege('authenticated',p.oid,'EXECUTE') authenticated,has_function_privilege('service_role',p.oid,'EXECUTE') service
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.proname like 'program_%' or p.proname like 'admin_program_%' or p.proname='observe_seoul_program'`);
  assert.equal(acl.length, 9);
  for (const a of acl) { assert.equal(a.anon,false);assert.equal(a.authenticated,false);assert.equal(a.service,a.nspname==='public');checks++; }
  for (const role of ["anon","authenticated"]) {
    await db.exec(`set role ${role}`);await fails(()=>query("select public.admin_program_list(0,25)"),"42501");await db.exec("reset role");
  }
  assert.equal((await query("select * from public.start_ingest_run('seoul_reservation',120)"))[0].skip_reason,"source_disabled");checks++;
  // Owner enables only this ephemeral test source. Never reads .env.local.
  await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='seoul_reservation'");
  const run = (await query("select * from public.start_ingest_run('seoul_reservation',120)"))[0].run_id;
  const items = samples.storageFixtures.map((f)=>f.item);
  const first = await rpc("observe_seoul_program",[run,JSON.stringify(items),null]);
  const ids = Object.fromEntries(first.map((r,i)=>[items[i].external_key,r.id]));
  assert.ok(first.every((r)=>r.outcome==='new'));checks++;
  const get=(id)=>rpc('admin_program_detail',[id]);
  const pass=await get(ids.personal);
  assert.ok(pass.source.title.includes('공원'));checks++;
  assert.equal(pass.aiStatus,'queued');assert.equal(pass.status,'resolved');checks++;
  assert.equal((await get(ids.family_paid)).aiStatus,'queued');assert.equal((await get(ids.school)).status,'excluded');checks++;
  assert.equal((await get(ids.closed)).aiStatus,'blocked');checks++;
  const repeat=await rpc('observe_seoul_program',[run,JSON.stringify(items),null]);assert.ok(repeat.every((r)=>r.outcome==='unchanged'));checks++;
  assert.equal((await query("select count(*)::int n from machimoa_review.processing_jobs where source_item_id=$1 and processing_stage='ai_enrichment'",[ids.personal]))[0].n,1);checks++;
  let detail=await get(ids.missing_venue);assert.equal(detail.status,'open');assert.ok(detail.editableFields.includes('activity_region'));checks++;
  const original=(await query('select normalized_payload from machimoa_review.source_items where id=$1',[ids.missing_venue]))[0].normalized_payload;
  const patch={delivery_mode:'offline',activity_region:'capital',activity_evidence:['공식 상세에서 서울 용산 개최 확인']};
  const args=[ids.missing_venue,detail.revision,detail.version,JSON.stringify(patch),['delivery_mode_unknown'],'합성 장소 확인 근거',actor];
  const saved=await rpc('admin_program_save',args);assert.equal(saved.status,'resolved');assert.equal(saved.aiStatus,'queued');assert.equal(saved.history[0].actor,actor);checks++;
  await fails(()=>rpc('admin_program_save',args),'PT409');
  assert.deepEqual((await query('select normalized_payload from machimoa_review.source_items where id=$1',[ids.missing_venue]))[0].normalized_payload,original);checks++;
  await rpc('observe_seoul_program',[run,JSON.stringify([items.find((i)=>i.external_key==='missing_venue')]),null]);
  assert.equal((await get(ids.missing_venue)).facts.activity_region,'capital');checks++;
  detail=await get(ids.status_conflict);
  await fails(()=>rpc('admin_program_save',[detail.id,detail.revision,detail.version,JSON.stringify({fee_kind:'paid'}),[],'무관한 필드',actor]),'PT422');
  assert.deepEqual(await get(detail.id),detail);checks++;
  // Fault after facts/event changes must roll the entire command back.
  await db.exec(`create function machimoa_review.test_fail_program() returns trigger language plpgsql as $$begin raise exception 'synthetic_write_failure';end$$;
  create trigger test_fail_program before update on machimoa_review.source_items for each row execute function machimoa_review.test_fail_program();`);
  await fails(()=>rpc('admin_program_save',[detail.id,detail.revision,detail.version,JSON.stringify({source_status:'reservation_closed'}),['source_status_conflict'],'상태 대조',actor]),'P0001');
  await db.exec('drop trigger test_fail_program on machimoa_review.source_items;drop function machimoa_review.test_fail_program()');
  assert.deepEqual(await get(detail.id),detail);checks++;
  const excluded=await rpc('admin_program_exclude',[detail.id,detail.revision,detail.version,'서비스 범위상 제외',actor]);
  assert.equal(excluded.status,'excluded');assert.equal(excluded.facts.application_actor,detail.facts.application_actor);assert.equal(excluded.history[0].fields[0],'service_scope');checks++;
  await fails(()=>rpc('admin_program_exclude',[detail.id,detail.revision,detail.version,'중복 제외',actor]),'PT409');
  const changed=structuredClone(items.find((i)=>i.external_key==='missing_venue'));
  changed.revision_hash='b'.repeat(64);changed.normalized_payload.title='변경 원문';changed.normalized_payload.source_body_html='<p>비실행 변경 원문</p>';
  assert.equal((await rpc('observe_seoul_program',[run,JSON.stringify([changed]),null]))[0].outcome,'changed');checks++;
  await fails(()=>rpc('admin_program_save',args),'PT409');
  assert.equal((await query('select count(*)::int n from machimoa_review.source_item_program_facts where source_item_id=$1',[changed.id??ids.missing_venue]))[0].n,2);checks++;
  assert.equal((await query("select status from machimoa_review.processing_jobs where source_item_id=$1 and revision_hash=$2 and processing_stage='ai_enrichment'",[ids.missing_venue,saved.revision]))[0].status,'cancelled');checks++;
  const invalid=structuredClone(items[0]);invalid.external_key='bad_batch';invalid.program_facts.fee_kind='invalid';
  await fails(()=>rpc('observe_seoul_program',[run,JSON.stringify([invalid]),null]),'PT422');
  assert.equal((await query("select count(*)::int n from machimoa_review.source_items where external_key='bad_batch'"))[0].n,0);checks++;
  const list=await rpc('admin_program_list',[0,25]);assert.ok(list.every((r)=>!('raw_payload' in r)));checks++;
  const openId=ids.weekday;
  await query("update machimoa_review.processing_jobs set status='completed' where source_item_id=$1 and processing_stage='content_review'",[openId]);
  assert.ok(!(await rpc('admin_program_list',[0,25])).some(r=>r.id===openId));checks++;
  assert.ok(!JSON.stringify(await get(ids.personal)).includes('source_body_html'));checks++;
  assert.deepEqual(await query("select * from machimoa_review.ingest_sources where source_id like 'youthcenter%'"),sourceBefore);checks++;
  assert.deepEqual(await query(`select p.oid,pg_get_functiondef(p.oid) definition,has_function_privilege('service_role',p.oid,'EXECUTE') service
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_review'
  and p.proname in ('upsert_source_observations_v4','publish_curation_candidate','canonical_source_id') order by p.oid`),legacyFns);checks++;
  assert.equal((await query("select count(*)::int n from machimoa_review.processing_jobs where status='claimed'"))[0].n,0);checks++;
  const archive=await query('select count(*)::int n from machimoa_review.source_item_program_facts');
  await db.exec(await readFile(new URL('../supabase/rollback/20261001000000_seoul_program_contract_down.sql',import.meta.url),'utf8'));
  assert.deepEqual(await query('select count(*)::int n from machimoa_review.source_item_program_facts'),archive);checks++;
  assert.equal((await query("select enabled from machimoa_review.ingest_sources where source_id='seoul_reservation'"))[0].enabled,false);checks++;
  assert.equal((await query("select count(*)::int n from machimoa_review.processing_jobs where status='queued'"))[0].n,0);checks++;
  console.log(`Isolated PostgreSQL checks passed: ${checks}; Python/SQL parity: ${samples.fixtures.length}. No network/AI/publication.`);
  }
} catch(e) {
  console.error(`Local SQL test failed: ${e.code??'assertion'}; ${e.message}; context=${e.where??''}`);
  process.exitCode=1;
} finally { await db.close(); }
