// Isolated PostgreSQL/WASM fixture. No network, operating credentials or publications.
// PGLITE_TEST_MODULE may point to an already-installed @electric-sql/pglite module.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const {PGlite}=await import(process.env.PGLITE_TEST_MODULE || '@electric-sql/pglite');
const sql=await readFile(new URL('../supabase/migrations/20261111132015_living_checked_on_label_encoding.sql',import.meta.url),'utf8');
assert.equal(/[^\x00-\x7f]/.test(sql),false,'migration transport must be ASCII-only');
const badKo='\ufffd'.repeat(4)+' \u022e'+'\ufffd'.repeat(4)+': ',badJa='\ufffd'.repeat(10)+': ';
const goodKo='정보 확인일: ',goodJa='情報確認日: ',day='2026-11-11';
const prefixKo='본문은 그대로\n\n'+badKo+'본문 안의 예시도 그대로';
const prefixJa='本文はそのまま\n\n'+badJa+'本文内の例もそのまま';
const db=new PGlite();
const q=async s=>(await db.query(s)).rows;
let passed=0;
try{
  await db.exec(`create role service_role; create role anon; create role authenticated;
    create schema machimoa_review;
    create table public.curations(id uuid primary key,slug text,source text,source_item_id text,
      content text,content_ko text,content_ja text,title text,source_image_url text,updated_at text);
    create table machimoa_review.living_articles(id uuid primary key,published_id uuid,status text,document jsonb);
    create table machimoa_review.living_image_assets(id uuid primary key,article_id uuid,hash text);
    create function public.admin_living_write(p_id uuid,p_version text,p_request_id uuid,p_action text,p_document jsonb,p_actor uuid)
      returns jsonb language plpgsql security definer set search_path='' as $fn$
      declare ko text;ja text; begin
      ko:=p_document->'content'->>'contentKo';ja:=p_document->'content'->>'contentJa';
      ko:=ko||E'\\n\\n${badKo}';ja:=ja||E'\\n\\n${badJa}';
      return jsonb_build_object('ko',ko||(p_document->>'checkedOn'),'ja',ja||(p_document->>'checkedOn'));
      end $fn$;
    revoke all on function public.admin_living_write(uuid,text,uuid,text,jsonb,uuid) from public,anon,authenticated;
    grant execute on function public.admin_living_write(uuid,text,uuid,text,jsonb,uuid) to service_role;`);
  const document={checkedOn:day,content:{contentKo:prefixKo,contentJa:prefixJa},images:[{id:'img-1',altKo:'그림 설명',altJa:'画像の説明'}]};
  for(let n=1;n<=3;n++){
    const id=`00000000-0000-4000-8000-00000000000${n}`,ko=prefixKo+'\n\n'+(n===3?goodKo:badKo)+day,ja=prefixJa+'\n\n'+(n===3?goodJa:badJa)+day;
    await db.query('insert into machimoa_review.living_articles values($1,$1,$2,$3)',[id,'published',document]);
    await db.query('insert into public.curations values($1,$2,$3,$4,$5,$5,$6,$7,$8,$9)',[id,'living-'+id,'machimoa_living',id,ko,ja,'원래 제목','/same/image.webp','unchanged timestamp']);
    await db.query('insert into machimoa_review.living_image_assets values($1,$1,$2)',[id,'unchanged-image-hash']);
  }
  await db.exec("insert into public.curations(id,title,content,content_ko)values('00000000-0000-4000-8000-000000000004','unrelated','untouched','untouched')");
  const before=await q('select * from public.curations order by id');
  const docs=await q('select * from machimoa_review.living_articles order by id'),assets=await q('select * from machimoa_review.living_image_assets order by id');
  const properties=await q("select oid,proowner,proacl::text,prosecdef,proconfig from pg_proc where oid='public.admin_living_write(uuid,text,uuid,text,jsonb,uuid)'::regprocedure");
  await db.exec(sql);
  const after=await q('select * from public.curations order by id');
  for(let i=0;i<3;i++){
    assert.equal(after[i].content_ko,prefixKo+'\n\n'+goodKo+day);
    assert.equal(after[i].content_ja,prefixJa+'\n\n'+goodJa+day);
    assert.equal(after[i].content,after[i].content_ko);
    const omit=row=>Object.fromEntries(Object.entries(row).filter(([k])=>!['content','content_ko','content_ja'].includes(k)));
    assert.deepEqual(omit(after[i]),omit(before[i]));passed++;
  }
  assert.deepEqual(after[3],before[3]);passed++;
  assert.deepEqual(await q('select * from machimoa_review.living_articles order by id'),docs);
  assert.deepEqual(await q('select * from machimoa_review.living_image_assets order by id'),assets);passed++;
  assert.deepEqual(await q("select oid,proowner,proacl::text,prosecdef,proconfig from pg_proc where oid='public.admin_living_write(uuid,text,uuid,text,jsonb,uuid)'::regprocedure"),properties);passed++;
  const future=await db.query('select public.admin_living_write(null,null,null,null,$1::jsonb,null) value',[document]);
  assert.equal(future.rows[0].value.ko,prefixKo+'\n\n'+goodKo+day);
  assert.equal(future.rows[0].value.ja,prefixJa+'\n\n'+goodJa+day);passed++;
  // Reapplying against a changed function fails closed without changing data.
  await assert.rejects(db.exec(sql),/predecessor differs/);await db.exec('rollback');
  assert.deepEqual(await q('select * from public.curations order by id'),after);passed++;
  console.log(JSON.stringify({passed,engine:'isolated PostgreSQL/WASM',operational_db:0,publications:0}));
}finally{await db.close();}
