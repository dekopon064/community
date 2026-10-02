// Fresh in-memory PostgreSQL (PGlite), synthetic users/content only.
// No connection string, network, .env or existing DB is used by this test.
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const modulePath = process.env.MACHIMOA_PGLITE_MODULE;
if (!modulePath) throw new Error('Set MACHIMOA_PGLITE_MODULE to an existing local PGlite dist/index.js');
const { PGlite } = await import(pathToFileURL(modulePath).href);
const db = new PGlite(); // No dataDir: this process owns a new disposable memory DB.
const migrationName = '20261001000100_saved_information.sql';
const migrationRoot = new URL('../supabase/migrations/', import.meta.url);
const userA = '00000000-0000-4000-8000-000000000001';
const userB = '00000000-0000-4000-8000-000000000002';
let checks = 0;
const query = async (sql, args = []) => (await db.query(sql, args)).rows;
const check = (actual, expected) => { assert.deepEqual(actual, expected); checks++; };
const fails = async (action, code) => { await assert.rejects(action, e => e.code === code); checks++; };
const asRole = (role, uid, action) => db.transaction(async tx => {
  assert.ok(['authenticated', 'anon', 'service_role'].includes(role));
  await tx.exec(`set local role ${role}`);
  await tx.query("select set_config('request.jwt.claim.sub', $1, true)", [uid ?? '']);
  return action(tx);
});
const rpc = (name, args = [], uid = userA, role = 'authenticated') => asRole(role, uid,
  async tx => (await tx.query(`select public.${name}(${args.map((_, i) => `$${i + 1}`).join(',')}) as value`, args)).rows[0].value);
const count = async uid => (await query('select count(*)::int n from machimoa_saved.information where user_id=$1', [uid]))[0].n;
const currentContent = async () => (await query("select md5(coalesce(string_agg(row_to_json(c)::text, '|' order by id), '')) value from public.curations c"))[0].value;
const existingAccess = async () => query(`select
  (select array_agg(acl::text order by acl::text) from unnest(
    (select relacl from pg_class where oid='public.curations'::regclass)) acl) as content_acl,
  (select jsonb_agg(row_to_json(p) order by p.polname) from
    (select polname, polroles, polcmd, pg_get_expr(polqual,polrelid) predicate
     from pg_policy where polrelid='public.curations'::regclass) p) as content_policies,
  (select md5(string_agg(pg_get_functiondef(p.oid)||coalesce(p.proacl::text,''), '|' order by p.oid))
   from pg_proc p join pg_namespace n on n.oid=p.pronamespace
   where n.nspname='machimoa_review') as review_contract,
  (select jsonb_agg(row_to_json(r) order by r.rolname) from
    (select rolname, rolsuper, rolbypassrls from pg_roles
     where rolname in ('anon','authenticated','service_role')) r) as roles`);

try {
  // The original curations CREATE is absent from this repository. Match the
  // established admin SQL test bootstrap, not a copy of Production data/schema.
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth;
    create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
    grant usage on schema auth to anon,authenticated,service_role;
    create table public.curations(id uuid primary key default gen_random_uuid(), slug text not null unique,
      category text, title text not null, summary text, content text not null,
      created_at timestamptz not null default now());
    alter table public.curations enable row level security;
    insert into public.curations(slug,title,summary,content)
      values('baseline-one','one','one','one'),('baseline-two','two','two','two');`);
  const canonical = (await readdir(migrationRoot)).filter(n => n.endsWith('.sql') && n !== migrationName &&
    (n >= '20260827022301' && n < '20260903' || n >= '20260913' && n < '20261001')).sort();
  for (const name of canonical) {
    try { await db.exec(await readFile(new URL(name, migrationRoot), 'utf8')); }
    catch (e) { throw new Error(`Canonical migration failed: ${name}`, { cause: e }); }
    if (name.startsWith('20260827022301')) await db.exec(`insert into machimoa_review.curation_candidates
      (source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status)
      select 'youthcenter','baseline-'||n,repeat('a',64),'baseline-candidate-'||n,
        'title','summary','content','{}','success' from generate_series(1,4) n;`);
  }
  console.log(`Applied ${canonical.length} unchanged canonical migrations to fresh memory PostgreSQL.`);
  const baselineAccess = await existingAccess();
  const baselineContent = await currentContent();
  await db.exec(await readFile(new URL(migrationName, migrationRoot), 'utf8'));
  check(await currentContent(), baselineContent);
  check(await existingAccess(), baselineAccess);
  await query('insert into auth.users(id) values($1),($2)', [userA, userB]);

  const signatures = ['save_information(uuid)', 'remove_saved_information(uuid)',
    'saved_information_state(uuid)', 'list_saved_information(text,integer,integer)'];
  for (const signature of signatures) {
    const [acl] = await query(`select has_function_privilege('anon',$1,'EXECUTE') anon,
      has_function_privilege('authenticated',$1,'EXECUTE') authenticated,
      has_function_privilege('service_role',$1,'EXECUTE') service`, [`public.${signature}`]);
    check(acl, { anon: false, authenticated: true, service: false });
  }
  check((await query("select relrowsecurity enabled from pg_class where oid='machimoa_saved.information'::regclass"))[0].enabled, true);
  check((await query("select has_table_privilege('authenticated','machimoa_saved.information','INSERT') i, has_table_privilege('authenticated','machimoa_saved.information','UPDATE') u"))[0], { i: false, u: false });

  async function seed(key, displayCategory = 'policy', overrides = {}) {
    const row = { slug: key, user_category: displayCategory, is_published: true,
      title_ko: `합성 ${key}`, summary_ko: `요약 ${key}`, content_ko: `본문 ${key}`,
      title_ja: `合成 ${key}`, summary_ja: `概要 ${key}`, content_ja: `本文 ${key}`, ...overrides };
    const event = row.user_category === 'event';
    const deadline = ['policy', 'program'].includes(row.user_category) ? 'none' : null;
    return (await query(`insert into public.curations(slug,category,title,summary,content,
      user_category,is_published,title_ko,summary_ko,content_ko,title_ja,summary_ja,content_ja,
      application_deadline_kind,event_start_on,event_end_on)
      values($1,'policy','synthetic','synthetic','synthetic',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) returning id`,
      [row.slug,row.user_category,row.is_published,row.title_ko,row.summary_ko,row.content_ko,
        row.title_ja,row.summary_ja,row.content_ja,deadline,event?'2026-10-10':null,event?'2026-10-11':null]))[0].id;
  }
  const policy = await seed('policy');
  const program = await seed('program', 'program');
  const hidden = await seed('hidden', 'policy', { is_published: false, title_ko: 'PRIVATE_MARKER', summary_ko: 'PRIVATE_MARKER' });
  const wrong = await seed('event', 'event');
  const unclassified = await seed('legacy-category-only', null);
  const incomplete = await seed('incomplete', 'policy', { summary_ja: null });
  const absent = '11111111-1111-4111-8111-111111111111';

  for (const [name,args] of [['save_information',[policy]], ['remove_saved_information',[policy]],
    ['saved_information_state',[policy]], ['list_saved_information',[]]]) {
    await fails(() => rpc(name, args, userA, 'anon'), '42501'); // Even with forged sub.
    await fails(() => rpc(name, args, null), '42501');
  }
  await fails(() => rpc('save_information',[policy], userA, 'service_role'), '42501');
  await fails(() => asRole('anon',userA,tx => tx.query('select * from machimoa_saved.information')), '42501');
  await fails(() => asRole('anon',userA,tx => tx.query('delete from machimoa_saved.information')), '42501');
  check(await rpc('saved_information_state',[policy]), {id:policy,saved:false});
  check(await rpc('list_saved_information'), {items:[],hasMore:false});
  const first = await rpc('save_information',[policy]);
  check(first.saved, true);
  check(await rpc('save_information',[policy]), first); // Timestamp and row are stable.
  check(await count(userA), 1);
  const ko = await rpc('list_saved_information',['ko']);
  const ja = await rpc('list_saved_information',['ja']);
  check(ko.items[0].id, ja.items[0].id);
  check(ko.items[0].information.title, '합성 policy');
  check(ja.items[0].information.title, '合成 policy');
  check(Object.hasOwn(ko.items[0].information, 'content'), false);
  check(await rpc('saved_information_state',[policy],userB), {id:policy,saved:false});
  check(await rpc('list_saved_information',[],userB), {items:[],hasMore:false});
  await rpc('save_information',[policy],userB);
  check(await count(userB), 1);
  await rpc('save_information',[program]);
  check(await count(userA), 2);
  check((await asRole('authenticated',userA,tx=>tx.query('select distinct user_id from machimoa_saved.information'))).rows, [{user_id:userA}]);
  await fails(() => asRole('authenticated',userA,tx => tx.query(
    'insert into machimoa_saved.information(user_id,original_curation_id,curation_id) values($1,$2,$2)',[userB,program])), '42501');
  await fails(() => asRole('authenticated',userA,tx => tx.query(
    'update machimoa_saved.information set user_id=$1',[userB])), '42501');
  check((await asRole('authenticated',userA,tx => tx.query(
    'delete from machimoa_saved.information where user_id=$1 returning *',[userB]))).rows, []);
  check(await count(userB), 1);
  check((await asRole('authenticated',userA,tx=>tx.query(
    'select * from machimoa_saved.information where user_id=$1',[userB]))).rows, []);

  for (const id of [hidden, wrong, unclassified, incomplete, absent]) {
    await fails(() => rpc('save_information',[id]), 'PT404');
    check(await count(userA), 2);
  }
  await fails(() => rpc('save_information',[null]), '22023');
  await fails(() => rpc('save_information',['not-a-uuid']), '22P02');
  await fails(() => rpc('remove_saved_information',[null]), '22023');
  await fails(() => rpc('saved_information_state',[null]), '22023');
  await fails(() => rpc('save_information',[policy],
    '00000000-0000-4000-8000-000000000003'), '23503');
  check((await query("select count(*)::int n from machimoa_saved.information where user_id='00000000-0000-4000-8000-000000000003'"))[0].n,0);
  for (const args of [['fr'],[null],['ko',0],['ko',101],['ko',null],['ko',1,-1],['ko',1,null],['ko',1,100001]]) {
    await fails(() => rpc('list_saved_information',args), '22023');
  }
  const pageOne = await rpc('list_saved_information',['ko',1,0]);
  const pageTwo = await rpc('list_saved_information',['ko',1,1]);
  check(pageOne.hasMore,true); check(pageTwo.hasMore,false);
  check(pageOne.items.length,1); check(pageTwo.items.length,1);
  check(pageOne.items[0].id === pageTwo.items[0].id,false);

  // Fail AFTER the insertion/deletion and prove statement rollback, not merely
  // pre-validation. The injection is local-only and is removed below.
  const atomic = await seed('atomic');
  await db.exec(`create function machimoa_saved.test_fail() returns trigger language plpgsql as $$
    begin raise exception 'synthetic rollback injection'; end $$;
    create trigger test_fail_insert after insert on machimoa_saved.information
    for each row execute function machimoa_saved.test_fail();`);
  await fails(() => rpc('save_information',[atomic]), 'P0001');
  check(await rpc('saved_information_state',[atomic]), {id:atomic,saved:false});
  check(await count(userA),2);
  await db.exec('drop trigger test_fail_insert on machimoa_saved.information');
  await db.exec(`create trigger test_fail_delete after delete on machimoa_saved.information
    for each row execute function machimoa_saved.test_fail();`);
  await fails(() => rpc('remove_saved_information',[policy]), 'P0001');
  check(await rpc('saved_information_state',[policy]), {id:policy,saved:true});
  await db.exec('drop trigger test_fail_delete on machimoa_saved.information; drop function machimoa_saved.test_fail()');

  // Nonpublic content is masked by both the existing RLS and list projection.
  await query("update public.curations set is_published=false, title_ko='PRIVATE_MARKER', summary_ja='PRIVATE_MARKER' where id=$1",[program]);
  let unavailable = (await rpc('list_saved_information')).items.find(r=>r.id===program);
  check(unavailable.availability,'unavailable'); check(unavailable.information,null);
  check(JSON.stringify(await rpc('list_saved_information',['ja'])).includes('PRIVATE_MARKER'),false);
  check((await asRole('authenticated',userA,tx=>tx.query('select id from public.curations where id=$1',[program]))).rows, []);
  check(await rpc('saved_information_state',[program]), {id:program,saved:true});
  await fails(() => rpc('save_information',[program]), 'PT404');
  await query('delete from public.curations where id=$1',[policy]);
  unavailable = (await rpc('list_saved_information')).items.find(r=>r.id===policy);
  check(unavailable.availability,'unavailable'); check(unavailable.information,null);
  check((await query('select curation_id from machimoa_saved.information where original_curation_id=$1',[policy])).map(r=>r.curation_id), [null,null]);
  check(await rpc('remove_saved_information',[policy]), {id:policy,saved:false});
  check(await rpc('remove_saved_information',[policy]), {id:policy,saved:false});
  check(await rpc('saved_information_state',[policy],userB), {id:policy,saved:true});
  check(await rpc('remove_saved_information',[program]), {id:program,saved:false});
  check(await rpc('list_saved_information'), {items:[],hasMore:false});
  await rpc('save_information',[atomic]);

  await query("update public.curations set user_category='living',application_deadline_kind=null where id=$1",[atomic]);
  check((await rpc('list_saved_information')).items[0].information,null);
  await fails(()=>rpc('save_information',[atomic]), 'PT404');
  await query("update public.curations set user_category='policy',application_deadline_kind='none',summary_ja=null where id=$1",[atomic]);
  check((await rpc('list_saved_information')).items[0].availability,'unavailable');
  await fails(()=>rpc('save_information',[atomic]), 'PT404');
  await query("update public.curations set summary_ja='概要 atomic' where id=$1",[atomic]);

  // A DB read fault is not a successful empty list or an unavailable item.
  await db.exec('revoke select on public.curations from authenticated');
  await fails(()=>rpc('list_saved_information'), '42501');
  await db.exec('grant select on public.curations to authenticated');
  check((await rpc('list_saved_information')).items[0].availability,'available');
  await query('delete from auth.users where id=$1',[userB]);
  check(await count(userB),0); check(await count(userA),1);
  check(await existingAccess(),baselineAccess);

  // Rollback removes feature access but retains relations and all current content.
  const beforeRollbackContent = await currentContent();
  const beforeRollbackSaved = await query('select * from machimoa_saved.information');
  await db.exec(await readFile(new URL('../supabase/rollback/20261001000100_saved_information_down.sql',import.meta.url),'utf8'));
  check(await query('select * from machimoa_saved.information'),beforeRollbackSaved);
  check(await currentContent(),beforeRollbackContent);
  check(await existingAccess(),baselineAccess);
  await fails(() => asRole('authenticated',userA,tx=>tx.query('select * from machimoa_saved.information')), '42501');
  for (const signature of signatures) check((await query('select to_regprocedure($1) present',[`public.${signature}`]))[0].present,null);
  console.log(`PASS: ${checks} saved information SQL assertions; isolated PostgreSQL only.`);
} catch (error) {
  console.error(`FAIL after ${checks} assertions: ${error.message}`);
  if (error.cause) console.error(`SQLSTATE ${error.cause.code}: ${error.cause.message}`);
  process.exitCode = 1;
} finally { await db.close(); }
