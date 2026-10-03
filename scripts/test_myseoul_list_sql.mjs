// New discovery/backlog RPCs only. Existing PGlite; no DB/network/provider credentials.
import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
const modulePath=process.env.MACHIMOA_PGLITE_MODULE;
const python=process.env.MACHIMOA_TEST_PYTHON;
if(!modulePath||!python)throw new Error('Explicit existing local test dependencies required');
const {PGlite}=await import(pathToFileURL(modulePath).href),db=new PGlite();
const root=new URL('../supabase/migrations/',import.meta.url);
const sample=JSON.parse(execFileSync(python,['-X','utf8','test_myseoul_ai.py','--fixtures'],{cwd:fileURLToPath(new URL('./',import.meta.url)),encoding:'utf8'})).packets[0];
let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const ok=v=>{assert.ok(v);checks++;};
const q=async(sql,args=[]) => (await db.query(sql,args)).rows;
const rpc=async(name,args)=>db.transaction(async tx=>{await tx.exec('set local role service_role');return (await tx.query(`select public.${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) v`,args)).rows[0].v;});
const denied=async(fn,code)=>{await assert.rejects(fn,e=>e.code===code);checks++;};
const center='30E1281B51FF476FB48B60B83D2581C1';
const entry=(n,state='unknown')=>{const p=n.toString(16).toUpperCase().padStart(32,'0');return {key:center+':'+p,url:`https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmDetail.do?cntr_no=${center}&prgrm_no=${p}&lang=ko`,state};};
const entries=(from,to)=>Array.from({length:to-from+1},(_,i)=>entry(from+i));
let run;
const start=async()=>{run=(await q("select * from public.start_ingest_run('myseoul_program',600)"))[0].run_id;return run;};
const observe=async e=>{const packet=structuredClone(sample);packet.external_key=e.key;packet.normalized_payload.center_id=center;packet.normalized_payload.program_id=e.key.split(':')[1];packet.normalized_payload.official_url=e.url;packet.myseoul_facts.official_url=e.url;return rpc('observe_myseoul_program',[run,[packet],null]);};
const finish=(requests,failed=false)=>rpc('finish_myseoul_list_collection',[run,requests,failed]);
try{
 await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;
 create table public.curations(id uuid primary key default gen_random_uuid(),slug text not null unique,category text,title text not null,summary text,content text not null,created_at timestamptz not null default now());
 alter table public.curations enable row level security;
 insert into public.curations(slug,title,summary,content) values('baseline-one','one','one','one'),('baseline-two','two','two','two');`);
 // Reuse the same minimal schema preparation as the previous checks, not their assertions.
 for(const name of (await readdir(root)).filter(n=>n.endsWith('.sql')&&(n>='20260827022301'&&n<'20260903'||n>='20260913'&&n<='20261001000001_seoul_program_ai.sql')).sort()){
  await db.exec(await readFile(new URL(name,root),'utf8'));
  if(name.startsWith('20260827022301'))await db.exec(`insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) select 'youthcenter','baseline-'||n,repeat('a',64),'candidate-'||n,'title','summary','content','{}','success' from generate_series(1,4)n;`);
 }
 for(const name of ['20261002000000_admin_review_ai_queue.sql','20261002000100_admin_review_trash.sql','20261002000200_admin_review_trash_publication.sql','20261002000300_myseoul_program_contract.sql','20261002000400_myseoul_program_ai.sql','20261003000001_myseoul_change_collection.sql'])await db.exec(await readFile(new URL(name,root),'utf8'));
 const previous=await q("select oid::regprocedure::text name,pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'machimoa_review'::regnamespace) order by 1");
 const sources=await q('select * from machimoa_review.ingest_sources order by source_id');
 await db.exec(await readFile(new URL('20261003000100_myseoul_list_discovery.sql',root),'utf8'));
 const after=await q("select oid::regprocedure::text name,pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'machimoa_review'::regnamespace) order by 1");
 eq(after.filter(x=>previous.some(y=>x.name===y.name)),previous);eq(await q('select * from machimoa_review.ingest_sources order by source_id'),sources);
 const wrappers=['discover_myseoul_list_page(uuid,integer,integer,jsonb)','myseoul_pending_details(uuid)','record_myseoul_detail_attempt(uuid,text,text)','finish_myseoul_list_collection(uuid,integer,boolean)'];
 for(const signature of wrappers){
  const acl=(await q("select has_function_privilege('anon',$1,'EXECUTE') a,has_function_privilege('authenticated',$1,'EXECUTE') u,has_function_privilege('service_role',$1,'EXECUTE') s",['public.'+signature]))[0];
  eq(acl,{a:false,u:false,s:true});
 }
 for(const role of ['anon','authenticated']){
  await denied(()=>db.transaction(async tx=>{await tx.exec('set local role '+role);await tx.exec("select public.myseoul_pending_details('00000000-0000-4000-8000-000000000001')");}),'42501');
  await denied(()=>db.transaction(async tx=>{await tx.exec('set local role '+role);await tx.exec('select * from machimoa_review.myseoul_list_discoveries');}),'42501');
 }
 await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program'");
 await start();
 await denied(()=>rpc('discover_myseoul_list_page',[run,1,20,entries(1,9)]),'PT422');
 await denied(()=>rpc('discover_myseoul_list_page',[run,2,20,entries(11,20)]),'PT409');
 const first=await rpc('discover_myseoul_list_page',[run,1,20,entries(1,10)]);eq(first.allNew,true);
 eq((await q('select count(*)::int n from machimoa_review.source_items'))[0].n,0); // discovery is NOT observation
 await denied(()=>rpc('myseoul_pending_details',[run]),'PT409');
 await rpc('discover_myseoul_list_page',[run,2,20,entries(11,20)]);
 await denied(()=>rpc('discover_myseoul_list_page',[run,3,20,[]]),'PT422');
 const selected=await rpc('myseoul_pending_details',[run]);eq(selected.length,10);
 await denied(()=>rpc('record_myseoul_detail_attempt',[run,entry(11).key,'detail_failed']),'PT409');
 await denied(()=>rpc('record_myseoul_detail_attempt',[run,selected[0].key,'processed']),'PT409');
 for(const e of selected){await observe(e);await rpc('record_myseoul_detail_attempt',[run,e.key,'processed']);}
 await denied(()=>rpc('record_myseoul_detail_attempt',[run,selected[0].key,'processed']),'PT409');
 await denied(()=>finish(13),'PT422');
 let result=await finish(12);eq(result.summary.pending_remaining,10);eq(result.summary.processed,10);eq(result.summary.source_complete,false);
 eq((await q("select bootstrap_complete from machimoa_review.source_sync_state where source_id='myseoul_program'"))[0].bootstrap_complete,false);
 const factsBefore=await q('select * from machimoa_review.source_item_program_facts order by source_item_id');
 await start();
 const mixed=[entry(1),...entries(31,39)];eq((await rpc('discover_myseoul_list_page',[run,1,10,mixed])).allNew,false);
 await denied(()=>rpc('discover_myseoul_list_page',[run,2,10,[]]),'PT409');
 const carried=await rpc('myseoul_pending_details',[run]);eq(carried.map(x=>x.key),entries(11,20).map(x=>x.key));
 for(const e of carried)await rpc('record_myseoul_detail_attempt',[run,e.key,'detail_failed']);
 result=await finish(11);eq(result.summary.carried_selected,10);eq(result.summary.failed,10);eq(result.summary.pending_remaining,19);
 eq(await q('select * from machimoa_review.source_item_program_facts order by source_item_id'),factsBefore);
 await start();
 const closed=await rpc('discover_myseoul_list_page',[run,1,2,[entry(40,'closed'),entry(41)]]);eq(closed.allNew,false);
 const next=await rpc('myseoul_pending_details',[run]);ok(!next.some(x=>x.key===entry(40).key));ok(next.length===10);
 // Successful observation with an ambiguous response is reconciled in the next run.
 await observe(next[0]);
 result=await finish(2,true);eq(result.status,'failed');
 await start();
 await rpc('discover_myseoul_list_page',[run,1,0,[]]);
 const recovered=await rpc('myseoul_pending_details',[run]);ok(!recovered.some(x=>x.key===next[0].key));
 eq((await q('select state from machimoa_review.myseoul_list_discoveries where external_key=$1',[next[0].key]))[0].state,'processed');
 for(const e of recovered)await rpc('record_myseoul_detail_attempt',[run,e.key,'detail_failed']);
 await finish(1+recovered.length);
 // Invalid URL and duplicate identity roll back the entire page registration.
 await start();
 const count=(await q('select count(*)::int n from machimoa_review.myseoul_list_discoveries'))[0].n;
 await denied(()=>rpc('discover_myseoul_list_page',[run,1,2,[entry(70),{...entry(71),url:'https://example.invalid/'}]]),'PT422');
 eq((await q('select count(*)::int n from machimoa_review.myseoul_list_discoveries'))[0].n,count);
 await denied(()=>rpc('discover_myseoul_list_page',[run,1,2,[entry(70),entry(70)]]),'PT422');
 await finish(1,true);
 eq((await q("select count(*)::int n from machimoa_review.curation_candidates where source='myseoul_program'"))[0].n,0);
 await db.exec("update machimoa_review.ingest_sources set enabled=false where source_id='myseoul_program'");
 const retained=(await q('select count(*)::int n from machimoa_review.myseoul_list_discoveries'))[0].n;
 await db.exec(await readFile(new URL('../rollback/20261003000100_myseoul_list_discovery_down.sql',root),'utf8'));
 eq((await q('select count(*)::int n from machimoa_review.myseoul_list_discoveries'))[0].n,retained);
 eq((await q("select to_regprocedure('public.myseoul_pending_details(uuid)') f"))[0].f,null);
 console.log(`My list discovery PGlite: ${checks} checks passed; independent PostgreSQL/PostgREST not exercised.`);
}catch(e){console.error('My list SQL check failed:',e.code??'assertion',e.message);process.exitCode=1;}finally{await db.close();}
