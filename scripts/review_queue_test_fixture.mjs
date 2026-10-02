// Fresh in-memory PostgreSQL and synthetic content only. No network/credentials.
import {readFile,readdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
export async function reviewDatabase(){
 const path=process.env.MACHIMOA_PGLITE_MODULE;if(!path)throw Error('Local PGlite module path required');
 const {PGlite}=await import(pathToFileURL(path).href);const db=new PGlite();
 const query=async(sql,args=[])=>(await db.query(sql,args)).rows;
 await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;
 create table public.curations(id uuid primary key default gen_random_uuid(),slug text not null unique,
 category text,title text not null,summary text,content text not null,created_at timestamptz not null default now());
 alter table public.curations enable row level security;
 insert into public.curations(slug,title,summary,content) values('baseline-one','one','one','one'),('baseline-two','two','two','two');`);
 const root=new URL('../supabase/migrations/',import.meta.url);
 const files=(await readdir(root)).filter(n=>n.endsWith('.sql')&&(n>='20260827022301'&&n<'20260903'||n>='20260913'&&n<='20261001000001_seoul_program_ai.sql')).sort();
 for(const n of files){
  try{await db.exec(await readFile(new URL(n,root),'utf8'));}catch(e){throw new Error(`Fixture migration ${n}: ${e.code} ${e.message}`);}
  if(n.startsWith('20260827022301'))await db.exec(`insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) select 'youthcenter','baseline-'||n,repeat('a',64),'baseline-'||n,'제목','요약','본문','{}','success' from generate_series(1,4) n;`);
 }
 const baseline=await query(`select n.nspname,p.proname,pg_get_functiondef(p.oid) definition,p.proacl::text acl
 from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('machimoa_review','public') order by p.oid`);
 await db.exec(await readFile(new URL('20261002000000_admin_review_ai_queue.sql',root),'utf8'));
 const rpc=(name,args)=>db.transaction(async tx=>{await tx.exec('set local role service_role');return (await tx.query(`select public.${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) value`,args)).rows[0].value;});
 const revision='a'.repeat(64);
 const source=async(key,origin='youthcenter_policy')=>(await query(`insert into machimoa_review.source_items(source_id,external_key,revision_hash,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload,has_source_url,body_usable)
 values($1,$2,$3,now(),now(),'missing','missing','target',$4,$5,true,true) returning id`,[origin,key,revision,JSON.stringify({title:'가상 '+key,source_url:'https://example.invalid/fixture'}),JSON.stringify({plcyNm:'가상 '+key,plain_text:'합성 원문 본문',source_url:'https://example.invalid/fixture',secret:'LOCAL_DO_NOT_ECHO'})]))[0].id;
 const job=async(sid,status='queued',extra={})=>(await query(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,retry_count,error_code,next_retry_at,claimed_at,claim_lease_until,completed_at)
 values($1,$2,'ai_enrichment',$3,clock_timestamp(),clock_timestamp(),$4,$5,$6,$7,$8,$9) returning id`,[sid,revision,status,extra.retryCount??0,extra.errorCode??null,extra.nextRetryAt??null,status==='claimed'?new Date().toISOString():null,extra.leaseUntil??null,status==='completed'?new Date().toISOString():null]))[0].id;
 const candidate=async(key,origin='youthcenter',status='pending')=>(await query(`insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,title_ko,summary_ko,content_ko,title_ja,summary_ja,content_ja,ai_status,ai_status_ko,ai_status_ja,raw_payload,review_status)
 values($1,$2,$3,$2,'제목','요약','본문','제목','요약','본문','題名','要約','本文','success','success','success','{}',$4) returning id`,[origin,key,revision,status]))[0].id;
 return {db,query,rpc,source,job,candidate,baseline,revision};
}
