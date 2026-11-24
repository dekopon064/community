// Run only in an ephemeral PGlite database. Never uses DATABASE_URL or Auth credentials.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';

const modulePath = process.env.PGLITE_MODULE || '@electric-sql/pglite';
const { PGlite } = await import(isAbsolute(modulePath) ? pathToFileURL(modulePath).href : modulePath);
const db = new PGlite();
const migration = name => readFileSync(new URL('../supabase/migrations/' + name, import.meta.url), 'utf8');
const packets = flag => JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-X','utf8','scripts/test_seoul_image_alt.py',flag], {encoding:'utf8'}));
const before = packets('--before-packets');
const after = packets('--packets');
const filters = {
  ...after.concert.filterFacts.data,
  topic:{status:'known',value:'culture_experience'}, delivery:{status:'known',value:'onsite'},
  location:{status:'known',value:{scope:'specific',venues:[{province:'11',district:null,facility:'',address:''}]}}
};
const id = '00000000-0000-4000-a000-000000000001';
const revision = 'fixture-v1';
try {
  // Minimal tables for the real filter-sync function; unrelated queue and binding
  // services are inert. The fixture starts with already confirmed mode and location.
  await db.exec(`
    create schema machimoa_review;
    set search_path=machimoa_review,public;
    create role anon; create role authenticated; create role service_role;
    create table source_items(id uuid, revision_hash text, source_id text, external_key text, normalized_payload jsonb);
    create table source_item_program_facts(source_item_id uuid, revision_hash text, facts jsonb, manual_excluded boolean default false, facts_version int default 1, updated_at timestamptz);
    create table source_item_content_filters(source_item_id uuid,revision_hash text,data jsonb,source_binding jsonb);
    create table admin_review_events(source_item_id uuid, revision_hash text, changed_fields text[]);
    create table review_classifications(source_item_id uuid,revision_hash text);
    create table processing_jobs(source_item_id uuid,status text,revision_hash text,processing_stage text);
    create table curation_candidates(source text,source_item_id text);
    create function content_filter_review_sync(uuid,text) returns void language plpgsql as $$begin end$$;
    create function program_refresh(uuid) returns void language plpgsql as $$begin end$$;
    create function canonical_source_id(text) returns text language sql as $$select $1$$;
    create function content_filter_binding(uuid,text) returns jsonb language sql as $$select '{"category":"program"}'::jsonb$$;
    create function admin_trash_pending(uuid,text) returns boolean language sql as $$select false$$;
    create function ai_recheck_pending(uuid,text) returns boolean language sql as $$select false$$;
  `);
  const contract = migration('20261001000000_seoul_program_contract.sql');
  await db.exec(contract.slice(contract.indexOf('create function machimoa_review.program_validate'),contract.indexOf('create function machimoa_review.program_reason_fields')));
  const rules = migration('20261012085122_optional_review_evidence.sql');
  let evaluateSql = rules.slice(rules.indexOf('CREATE OR REPLACE FUNCTION machimoa_review.program_evaluate_with_confirmation'),rules.indexOf('CREATE OR REPLACE FUNCTION machimoa_review.classification_validate',rules.indexOf('CREATE OR REPLACE FUNCTION machimoa_review.program_evaluate_with_confirmation')));
  const statusPatch = migration('20261015021859_seoul_review_value_link.sql').split("('machimoa_review.program_evaluate_with_confirmation(jsonb,timestamp with time zone,boolean)',")[1];
  const oldClause = statusPatch.split('$old$')[1];
  assert.ok(evaluateSql.includes(oldClause));
  evaluateSql = evaluateSql.replace(oldClause,statusPatch.split('$new$')[1]);
  await db.exec(evaluateSql);
  await db.exec(migration('20261117071728_seoul_program_purpose_from_participation.sql'));

  async function evaluate(packet, options = {}) {
    await db.exec('truncate source_items, source_item_program_facts, source_item_content_filters, admin_review_events, processing_jobs');
    const facts = {...packet.program_facts, delivery_mode:'offline', activity_region:'capital', activity_evidence:['합성 교육장 소재지'], ...options.facts};
    const data = options.filters || filters;
    await db.query("insert into source_items values ($1,$2,'seoul_reservation','fixture',$3)",[id,revision,packet.normalized_payload]);
    await db.query('insert into source_item_program_facts(source_item_id,revision_hash,facts) values($1,$2,$3)',[id,revision,facts]);
    await db.query('insert into source_item_content_filters values ($1,$2,$3,content_filter_binding($1,$2))',[id,revision,data]);
    if (options.manual) await db.query("insert into admin_review_events values ($1,$2,array['content_kind'])",[id,revision]);
    if (options.claimed) await db.query("insert into processing_jobs values ($1,'claimed',$2,'ai_enrichment')",[id,revision]);
    for (let n=0; n<2; n++) await db.query('select content_filter_review_sync($1,$2)',[id,options.wrongRevision ? 'later' : revision]);
    const result = (await db.query("select facts, facts_version, program_evaluate_with_confirmation(facts,'2026-10-01T18:00:00+09:00',true) as evaluation from source_item_program_facts")).rows[0];
    assert.deepEqual((await db.query('select data from source_item_content_filters')).rows[0].data,data);
    return result;
  }

  const previous = {};
  for (const [key,p] of Object.entries(before)) previous[key] = (await evaluate(p)).evaluation.reasons;
  await db.exec(migration('20261124002500_seoul_image_alt_participation.sql'));
  const privilege = await db.query(`select rolname,
    has_function_privilege(rolname,'machimoa_review.seoul_program_source_participation(jsonb,jsonb,jsonb,boolean)','execute') as allowed
    from pg_roles where rolname in ('anon','authenticated','service_role')`);
  assert.equal(privilege.rows.length,3);
  assert.ok(privilege.rows.every(role => !role.allowed));
  const expected = {
    concert:[], duplicate:previous.duplicate, decorative:['attachment_dependent','program_purpose_unconfirmed'],
    activity:['program_purpose_unconfirmed'], cast:['program_purpose_unconfirmed'],
    group:['individual_participation_excluded'], age:['target_conflict','program_purpose_unconfirmed'],
    actor:['application_actor_conflict','program_purpose_unconfirmed'],full_conflict:['target_conflict','program_purpose_unconfirmed'],
    missing_period:['period_missing_or_unparsed']
  };
  for (const [key,p] of Object.entries(after)) {
    assert.equal(p.revision_hash,before[key].revision_hash);
    assert.equal(p.normalized_payload.source_body_html,before[key].normalized_payload.source_body_html);
    const result = await evaluate(p);
    assert.deepEqual(new Set(result.evaluation.reasons),new Set(expected[key]),key + ': ' + JSON.stringify(result.evaluation));
    if (key === 'concert') {
      assert.deepEqual(new Set(previous[key]),new Set(['attachment_dependent','program_purpose_unconfirmed']));
      assert.equal(result.facts.content_kind,'program');
      assert.equal(result.facts_version,2);
    }
    console.log(key,previous[key].join(','),'->',result.evaluation.reasons.join(',') || 'clear');
  }
  for (const options of [{manual:true},{wrongRevision:true},{claimed:true},
    {filters:{...filters,topic:{status:'known',value:'employment_career'}}},
    {facts:{description:'운영자가 별도의 근거로 확인한 설명입니다.'}}]) {
    const result = await evaluate(after.concert,options);
    assert.equal(result.facts_version,1);
    assert.equal(result.facts.content_kind,'unknown');
  }
} finally {
  await db.close();
}
