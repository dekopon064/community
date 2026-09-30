// Real PostgreSQL 17 (PGlite), synthetic data only; no network/Production access.
// The repository does not contain the original curations CREATE statement.
// A minimal synthetic pre-P0 table is explicit below; all review/ingest functions
// and subsequent schemas come from the canonical migration files unchanged.
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";
const runtime = process.env.MACHIMOA_PGLITE_MODULE;
if (!runtime) throw new Error("Set MACHIMOA_PGLITE_MODULE to an installed PGlite index.js (local test only)");
const { PGlite } = await import(pathToFileURL(runtime).href);
const db = new PGlite();
const root = new URL("../supabase/migrations/", import.meta.url);
const actor = "00000000-0000-4000-8000-000000000001";
let checks = 0;
const query = async (sql, args = []) => (await db.query(sql, args)).rows;
const rpc = async (name, args) => (await query(`select public.${name}(${args.map((_, i) => `$${i + 1}`).join(",")}) as value`, args))[0].value;
async function fails(action, code) { await assert.rejects(action, (e) => e.code === code); checks++; }
try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create table public.curations(id uuid primary key default gen_random_uuid(), slug text not null unique,
    category text, title text not null, summary text, content text not null, created_at timestamptz not null default now());
    alter table public.curations enable row level security;
    insert into public.curations(slug,title,summary,content) values('baseline-one','one','one','one'),('baseline-two','two','two','two');`);
  const files = (await readdir(root)).filter((n) => n.endsWith(".sql") &&
    (n >= "20260827022301" && n < "20260903" || n >= "20260913")).sort();
  for (const name of files) {
    try { await db.exec(await readFile(new URL(name, root), "utf8")); }
    catch (e) { console.error(`Migration failed: ${name}, SQLSTATE ${e.code}, ${e.message}`); throw e; }
    if (name.startsWith("20260827022301")) await db.exec(`insert into machimoa_review.curation_candidates
      (source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status)
      select 'youthcenter','baseline-'||n,repeat('a',64),'baseline-candidate-'||n,'title','summary','content','{}','success' from generate_series(1,4) n;`);
    console.log(`Applied in isolated PostgreSQL: ${name}`);
  }
  console.log("All relevant canonical migrations applied locally.");
  const acl = await query(`select n.nspname,p.proname,
    has_function_privilege('anon',p.oid,'EXECUTE') anon,
    has_function_privilege('authenticated',p.oid,'EXECUTE') authenticated,
    has_function_privilege('service_role',p.oid,'EXECUTE') service
    from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where p.proname like 'admin_review_%' order by n.nspname,p.proname`);
  assert.equal(acl.length,12);
  for (const row of acl) { assert.equal(row.anon,false); assert.equal(row.authenticated,false); assert.equal(row.service,row.nspname==='public'); checks++; }
  for (const role of ["anon", "authenticated"]) {
    await db.exec(`set role ${role}`);
    await fails(() => rpc("admin_review_list", ["facts",0,25]), "42501");
    await db.exec("reset role");
  }
  const legacyAcl = await query(`select has_function_privilege('service_role','machimoa_review.publish_curation_candidate(uuid,text,text,boolean)','EXECUTE') publish,
    has_function_privilege('service_role','machimoa_review.reject_curation_candidate(uuid,text,text)','EXECUTE') reject,
    has_table_privilege('service_role','machimoa_review.admin_review_events','SELECT') events`);
  assert.deepEqual(legacyAcl[0],{publish:false,reject:false,events:false}); checks++;
  await db.exec("set role service_role"); assert.deepEqual(await rpc("admin_review_list",["facts",0,25]),[]); await db.exec("reset role"); checks++;

  // From here every wrapper call runs as service_role. Fixture setup stays owner-only.
  const service = async (name,args) => db.transaction(async(tx) => {
    await tx.exec('set local role service_role');
    return (await tx.query(`select public.${name}(${args.map((_,i)=>`$${i+1}`).join(',')}) as value`,args)).rows[0].value;
  });
  const get = (kind,id) => service('admin_review_detail',[kind,id]);
  await db.exec("update machimoa_review.ingest_sources set permission_status='approved_noncommercial'");
  async function seed(key,reasons=['policy_lifecycle_uncertain','user_category_unconfirmed']) {
    const [s]=await query(`insert into machimoa_review.source_items(source_id,external_key,revision_hash,first_seen_at,last_seen_at,
      source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload,has_source_url,body_usable)
      values('youthcenter_policy',$1,repeat('a',64),now(),now(),'missing','missing','observe_only','{}',$2,true,true) returning id`,
      [key,JSON.stringify({plcyNm:'합성 정책',plain_text:'합성 원문 본문',source_url:'https://example.invalid/source',provider_response:'LOCAL_DO_NOT_RETURN'})]);
    await query(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
      values($1,repeat('a',64),'content_review','queued',now(),now(),$2)`,[s.id,reasons]);
    return s.id;
  }
  const sid=await seed('facts-main'); let f=await get('facts',sid);
  assert.equal(f.source.title,'합성 정책'); assert.equal(f.source.body,'합성 원문 본문'); assert.ok(f.editableFields.includes('productType'));
  assert.equal(JSON.stringify(f).includes('LOCAL_DO_NOT_RETURN'),false); checks++;
  const initialPayload=(await query('select normalized_payload from machimoa_review.source_items where id=$1',[sid]))[0].normalized_payload;
  f=await service('admin_review_save_facts',[sid,f.revision,f.version,JSON.stringify({...f.facts,productType:'policy_reference',scope:'nationwide',foreignEligibility:'eligible',evidence:'전국 대상'}),actor]);
  assert.ok(f.reasons.includes('user_category_unconfirmed')); assert.ok(!f.editableFields.includes('productType')); assert.equal(f.status,'open'); checks++;
  const stale=f;
  f=await service('admin_review_save_facts',[sid,f.revision,f.version,JSON.stringify({...f.facts,category:'policy'}),actor]);
  assert.ok(f.reasons.includes('application_deadline_unknown')); assert.ok(f.editableFields.includes('deadlineKind')); checks++;
  await fails(()=>service('admin_review_save_facts',[sid,stale.revision,stale.version,JSON.stringify({...stale.facts,category:'living'}),actor]),'PT409');
  await fails(()=>service('admin_review_save_facts',[sid,f.revision,f.version,JSON.stringify({...f.facts,productType:'living_guide'}),actor]),'PT422');
  f=await service('admin_review_save_facts',[sid,f.revision,f.version,JSON.stringify({...f.facts,deadlineKind:'none'}),actor]);
  assert.equal(f.status,'resolved'); assert.deepEqual(f.reasons,[]); assert.equal(f.aiStatus,'queued'); assert.equal(f.history[0].actor,actor); checks++;
  assert.deepEqual((await query('select normalized_payload from machimoa_review.source_items where id=$1',[sid]))[0].normalized_payload,initialPayload); checks++;
  const excludedId=await seed('facts-exclude',['attachment_dependent']); const excludedBefore=await get('facts',excludedId);
  const excluded=await service('admin_review_exclude',[excludedId,excludedBefore.revision,excludedBefore.version,'합성 부적격 사유',actor]);
  assert.equal(excluded.status,'excluded'); assert.equal(excluded.history[0].note,'합성 부적격 사유'); checks++;
  const unsupportedId=await seed('facts-unsupported',['policy_lifecycle_uncertain','unsupported_legacy_reason']); const unsupported=await get('facts',unsupportedId);
  await fails(()=>service('admin_review_save_facts',[unsupportedId,unsupported.revision,unsupported.version,JSON.stringify({...unsupported.facts,productType:'living_guide'}),actor]),'PT422');
  assert.deepEqual(await get('facts',unsupportedId),unsupported); checks++;
  const leaseId=await seed('facts-lease'); const lease=await get('facts',leaseId);
  await query(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,claimed_at,claim_lease_until)
    values($1,repeat('a',64),'ai_enrichment','claimed',now(),now(),now(),null)`,[leaseId]);
  const leaseCurrent=await get('facts',leaseId);
  await fails(()=>service('admin_review_exclude',[leaseId,leaseCurrent.revision,leaseCurrent.version,'local reason',actor]),'PT409');
  assert.equal(lease.revision,leaseCurrent.revision); checks++;

  async function seedCandidate(key) {
    const source=await seed(key);
    const [c]=await query(`insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,category,user_category,
      title,summary,content,title_ko,summary_ko,content_ko,title_ja,summary_ja,content_ja,source_url,raw_payload,ai_status,ai_status_ko,ai_status_ja)
      values('youthcenter',$1,repeat('a',64),$1,'living','living','한국어 제목','한국어 요약','한국어 상세','한국어 제목','한국어 요약','한국어 상세',
      '日本語題名','日本語要約','日本語本文','https://example.invalid/source','{"provider_response":"LOCAL_DO_NOT_RETURN"}','success','success','success') returning id`,[key]);
    return {id:c.id,source};
  }
  const candidate=await seedCandidate('candidate-publish'); let c=await get('candidates',candidate.id);
  assert.equal(JSON.stringify(c).includes('LOCAL_DO_NOT_RETURN'),false); assert.equal(c.publishedAt,null); checks++;
  const saved=await service('admin_review_save_candidate',[c.id,c.revision,c.version,JSON.stringify({...c.content,titleKo:'수정한 한국어 제목',titleJa:'修正した日本語題名'}),actor]);
  const [legacy]=await query('select title,title_ko,review_status from machimoa_review.curation_candidates where id=$1',[c.id]);
  assert.equal(legacy.title,legacy.title_ko); assert.equal(legacy.review_status,'pending'); assert.equal(saved.history[0].actor,actor); checks++;
  await fails(()=>service('admin_review_publish',[c.id,c.revision,c.version,actor]),'PT409');
  const published=await service('admin_review_publish',[c.id,saved.revision,saved.version,actor]);
  assert.equal(published.status,'published'); assert.ok(published.publishedAt); assert.ok(published.publishedId); assert.equal(published.history[0].actor,actor); checks++;
  const [publicRow]=await query('select title,title_ko,title_ja,is_published from public.curations where id=$1',[published.publishedId]);
  assert.equal(publicRow.title,publicRow.title_ko); assert.equal(publicRow.title_ko,'수정한 한국어 제목'); assert.equal(publicRow.is_published,true); checks++;
  assert.equal((await query('select count(*)::int as n from machimoa_review.source_publication_events where candidate_id=$1',[candidate.id]))[0].n,1); checks++;
  await fails(()=>service('admin_review_publish',[c.id,saved.revision,saved.version,actor]),'PT409');
  const rejected=await seedCandidate('candidate-reject'); c=await get('candidates',rejected.id);
  c=await service('admin_review_reject',[c.id,c.revision,c.version,'합성 반려',actor]); assert.equal(c.status,'rejected'); assert.equal(c.history[0].note,'합성 반려'); checks++;
  const changedSource=await seedCandidate('candidate-new-revision'); c=await get('candidates',changedSource.id);
  await query("update machimoa_review.source_items set revision_hash=repeat('b',64) where id=$1",[changedSource.source]);
  await fails(()=>service('admin_review_publish',[c.id,c.revision,c.version,actor]),'PT409');
  await fails(()=>get('candidates',c.id),'PT409');
  const failCandidate=await seedCandidate('candidate-fail'); c=await get('candidates',failCandidate.id);
  await db.exec(`create function public.test_fail_publish() returns trigger language plpgsql as $$begin if new.slug='candidate-fail' then raise exception 'local injection'; end if; return new; end$$;
    create trigger test_fail_publish before insert on public.curations for each row execute function public.test_fail_publish();`);
  await fails(()=>service('admin_review_publish',[c.id,c.revision,c.version,actor]),'PT503');
  assert.deepEqual(await get('candidates',c.id),c); assert.equal((await query("select count(*)::int n from public.curations where slug='candidate-fail'"))[0].n,0); checks++;
  assert.equal((await query('select count(*)::int n from machimoa_review.source_publication_events where candidate_id=$1',[failCandidate.id]))[0].n,0); checks++;
  await db.exec('drop trigger test_fail_publish on public.curations; drop function public.test_fail_publish()');
  await db.exec(`create function machimoa_review.test_fail_audit() returns trigger language plpgsql as $$begin if new.action='publish' then raise exception 'local audit injection'; end if; return new; end$$;
    create trigger test_fail_audit before insert on machimoa_review.admin_review_events for each row execute function machimoa_review.test_fail_audit();`);
  await fails(()=>service('admin_review_publish',[c.id,c.revision,c.version,actor]),'P0001');
  assert.deepEqual(await get('candidates',c.id),c); assert.equal((await query("select count(*)::int n from public.curations where slug='candidate-fail'"))[0].n,0); checks++;
  await db.exec('drop trigger test_fail_audit on machimoa_review.admin_review_events; drop function machimoa_review.test_fail_audit()');
  const concurrent=await seedCandidate('candidate-same-version'); const cc=await get('candidates',concurrent.id);
  const results=await Promise.allSettled(['first','second'].map(title=>service('admin_review_save_candidate',[cc.id,cc.revision,cc.version,JSON.stringify({...cc.content,titleKo:title}),actor])));
  assert.equal(results.filter(r=>r.status==='fulfilled').length,1); assert.equal(results.find(r=>r.status==='rejected').reason.code,'PT409'); checks++;
  // This tests competing requests against one serialized PGlite session, not
  // independent network sessions or real inter-process advisory-lock contention.
  const down=await readFile(new URL('../supabase/rollback/20260930000000_admin_review_rpc_down.sql',import.meta.url),'utf8');
  await fails(()=>db.exec(down),'P0001'); await db.exec('rollback');
  assert.ok((await query("select to_regclass('machimoa_review.admin_review_events') is not null present"))[0].present); checks++;
} finally { await db.close(); }
console.log(`PASS: ${checks} isolated PostgreSQL schema/ACL checks. NO Production mutation.`);
