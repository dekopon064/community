import assert from 'node:assert/strict';
import { readFile,readdir } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
export async function fakeDatabase() {
 const modulePath=process.env.MACHIMOA_PGLITE_MODULE;
 if(!modulePath) throw Error('Existing local PGlite module path required');
 const {PGlite}=await import(pathToFileURL(modulePath).href);const db=new PGlite();
 const migrationName='20261001000100_saved_information.sql',migrationRoot=new URL('../supabase/migrations/',import.meta.url);
 const userA='00000000-0000-4000-8000-000000000001',userB='00000000-0000-4000-8000-000000000002';
 const query=async(sql,args=[]) => (await db.query(sql,args)).rows;
 const currentContent=async()=> (await query("select md5(coalesce(string_agg(row_to_json(c)::text,'|' order by id),'')) value from public.curations c"))[0].value;
 const existingAccess=async()=>query("select polname,polroles,polcmd,pg_get_expr(polqual,polrelid) predicate from pg_policy where polrelid='public.curations'::regclass order by polname");
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


  await query('insert into auth.users(id) values($1),($2)', [userA, userB]);


 await db.exec(await readFile(new URL('20261001000200_saved_information_resume.sql',migrationRoot),'utf8'));
 await db.exec(await readFile(new URL('20261001000300_saved_information_order.sql',migrationRoot),'utf8'));
 assert.equal(await currentContent(),baselineContent);assert.deepEqual(await existingAccess(),baselineAccess);
 const asRole=(role,uid,action)=>db.transaction(async tx=>{assert.ok(['anon','authenticated'].includes(role));await tx.exec(`set local role ${role}`);await tx.query("select set_config('request.jwt.claim.sub',$1,true)",[uid??'']);return action(tx)});
 const rpc=(name,args=[],uid=userA,role='authenticated')=>asRole(role,uid,async tx=>(await tx.query(`select public.${name}(${args.map((_,i)=>`$${i+1}`).join(',')}) value`,args)).rows[0].value);
 async function seed(slug,category='policy',published=true) {
  return (await query(`insert into public.curations(slug,category,title,summary,content,user_category,is_published,title_ko,summary_ko,content_ko,title_ja,summary_ja,content_ja,application_deadline_kind,event_start_on,event_end_on)
  values($1,'policy','synthetic','synthetic','synthetic',$2,$3,'로컬 테스트 정책','합성 요약','## 한 줄 요약\n합성 테스트 정보입니다.','ローカルテスト政策','合成の概要','## 一行要約\n合成テスト情報です。',$4,$5,$6) returning id`,[slug,category,published,['policy','program'].includes(category)?'none':null,category==='event'?'2026-10-10':null,category==='event'?'2026-10-11':null]))[0].id;
 }
 const post=await seed('local-policy'),program=await seed('local-program','program'),hidden=await seed('local-private','policy',false),wrong=await seed('local-event','event');
 return {db,query,rpc,asRole,userA,userB,post,program,hidden,wrong,seed};
}
