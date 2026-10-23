// Fresh in-memory PostgreSQL only. Requires an already-installed PGlite runtime;
// never opens a connection string, shared DB, container DB, or authentication file.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { reviewDatabase } from './review_queue_test_fixture.mjs';
const f=await reviewDatabase();let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++};
const actor='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002';
try {
 const {db,query:q,rpc,source,candidate}=f;
 await db.exec(await readFile(new URL('../supabase/migrations/20261003000000_source_images.sql',import.meta.url),'utf8'));
 const migration=await readFile(new URL('../supabase/migrations/20261023123507_home_card_colors.sql',import.meta.url),'utf8');
 const functionSnapshot=await q(`select p.oid,pg_get_functiondef(p.oid) definition,p.proacl::text acl from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','machimoa_review') order by p.oid`);
 const originals=await q('select to_jsonb(c) value from public.curations c order by id');
 await db.exec(migration);
 eq(await q('select to_jsonb(c) value from public.curations c order by id'),originals);
 eq(await q('select count(*)::int n from machimoa_review.home_card_colors'),[{n:0}]);
 eq(await q('select p.oid,pg_get_functiondef(p.oid) definition,p.proacl::text acl from pg_proc p where p.oid=any($1::oid[]) order by p.oid',[functionSnapshot.map(x=>x.oid)]),functionSnapshot);
 const read=async(ids)=>(await rpc('public_home_card_colors',[ids]));
 async function reject(fn){await assert.rejects(fn);checks++}
 async function published(key,image){
  const sid=await source(key,'youthcenter_content');
  await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[sid,JSON.stringify({source_image_url:image,plain_text:'합성 설명'})]);
  await q("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='youthcenter_content'");
  const cid=await candidate(key,'youthcenter_content');
  await q("update machimoa_review.curation_candidates set category='생활',user_category='living',source_url='https://www.youthcenter.go.kr/' where id=$1",[cid]);
  const pid=(await q('select machimoa_review.publish_curation_candidate($1,$2,null,false) id',[cid,actor]))[0].id;
  return {sid,cid,pid};
 }
 const a=await published('palette-one','https://images.example.org/first.png');
 const before=await q('select to_jsonb(c) value from public.curations c where id=$1',[a.pid]);
 const candidateBefore=await q('select to_jsonb(c) value from machimoa_review.curation_candidates c where id=$1',[a.cid]);
 eq((await read([a.pid]))[0],{id:a.pid,tone:'default',ready:false});
 await reject(()=>rpc('admin_home_color_claim',[a.pid,a.cid,other]));
 const claim=await rpc('admin_home_color_claim',[a.pid,a.cid,actor]);eq(claim.state,'claimed');eq(claim.url,'https://images.example.org/first.png');
 eq(await rpc('admin_home_color_claim',[a.pid,a.cid,actor]),{state:'processing'});
 await reject(()=>rpc('admin_home_color_finish',[a.pid,other,actor,'orange','completed','matched']));
 await reject(()=>rpc('admin_home_color_finish',[a.pid,claim.token,other,'orange','completed','matched']));
 await reject(()=>rpc('admin_home_color_finish',[a.pid,claim.token,actor,'unapproved','completed','matched']));
 eq(await rpc('admin_home_color_finish',[a.pid,claim.token,actor,'orange','completed','matched']),{state:'completed',tone:'orange'});
 eq(await read([a.pid]),[{id:a.pid,tone:'orange',ready:true}]);
 eq(await rpc('admin_home_color_finish',[a.pid,claim.token,actor,'orange','completed','matched']),{state:'completed',tone:'orange'});
 await reject(()=>rpc('admin_home_color_finish',[a.pid,claim.token,actor,'blue','completed','matched']));
 eq(await q('select to_jsonb(c) value from public.curations c where id=$1',[a.pid]),before);
 eq(await q('select to_jsonb(c) value from machimoa_review.curation_candidates c where id=$1',[a.cid]),candidateBefore);
 // A later image edit/publication cannot replace the first analysis record.
 await q("update public.curations set source_image_url='https://images.example.org/changed.png' where id=$1",[a.pid]);
 await q("update machimoa_review.curation_candidates set review_status='published' where id=$1",[a.cid]);
 eq(await rpc('admin_home_color_claim',[a.pid,a.cid,actor]),{state:'settled'});eq((await read([a.pid]))[0].tone,'orange');
 const b=await published('palette-noimage',null);
 eq(await rpc('admin_home_color_claim',[b.pid,b.cid,actor]),{state:'no_image'});eq((await read([b.pid]))[0],{id:b.pid,tone:'default',ready:true});
 const c=await published('palette-failed','https://images.example.org/failed.png');
 const cc=await rpc('admin_home_color_claim',[c.pid,c.cid,actor]);
 eq(await rpc('admin_home_color_finish',[c.pid,cc.token,actor,'default','failed','analysis_failed']),{state:'failed',tone:'default'});
 eq(await rpc('admin_home_color_claim',[c.pid,c.cid,actor]),{state:'settled'});eq((await read([c.pid]))[0].ready,true);
 const d=await published('palette-abandoned','https://images.example.org/abandoned.png');
 const dc=await rpc('admin_home_color_claim',[d.pid,d.cid,actor]);
 await q("update machimoa_review.home_card_colors set expires_at=clock_timestamp()-interval '1 second' where curation_id=$1",[d.pid]);
 eq((await read([d.pid]))[0],{id:d.pid,tone:'default',ready:true}); // Read has no repair/write side effect.
 eq((await q('select state from machimoa_review.home_card_colors where curation_id=$1',[d.pid]))[0].state,'processing');
 eq(await rpc('admin_home_color_finish',[d.pid,dc.token,actor,'blue','completed','matched']),{state:'failed',tone:'default'});
 const e=await published('palette-stale','https://images.example.org/old.png');
 const ec=await rpc('admin_home_color_claim',[e.pid,e.cid,actor]);
 await q("update public.curations set source_image_url='https://images.example.org/new.png' where id=$1",[e.pid]);
 eq(await rpc('admin_home_color_finish',[e.pid,ec.token,actor,'red','completed','matched']),{state:'failed',tone:'default'});
 await q('update public.curations set is_published=false where id=$1',[a.pid]);eq(await read([a.pid]),[]);
 await reject(()=>rpc('public_home_card_colors',[Array(7).fill(b.pid)]));
 for(const role of ['anon','authenticated']){
  for(const name of ['public.admin_home_color_claim(uuid,uuid,uuid)','public.admin_home_color_finish(uuid,uuid,uuid,text,text,text)'])eq((await q('select has_function_privilege($1,$2,\'execute\') ok',[role,name]))[0].ok,false);
  eq((await q("select has_function_privilege($1,'public.public_home_card_colors(uuid[])','execute') ok",[role]))[0].ok,true);
  await db.exec('set role '+role);await reject(()=>q('select * from machimoa_review.home_card_colors'));await db.exec('reset role');
 }
 eq((await q("select has_table_privilege('service_role','machimoa_review.home_card_colors','update') ok"))[0].ok,false);
 const meta=await q("select p.proname,p.prosecdef,p.proconfig,array_to_string(p.proacl,',') acl from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.proname in ('prepare_home_card_color','admin_home_color_claim','admin_home_color_finish','public_home_card_colors')");
 for(const fn of meta){eq(fn.prosecdef,true);assert(fn.proconfig.some(s=>s.startsWith('search_path=')));checks++;}
 await reject(()=>db.exec(migration));await db.exec('rollback');
 console.log(JSON.stringify({passed:checks,engine:process.env.MACHIMOA_HOME_COLOR_CONTAINER?'fresh isolated PostgreSQL':'fresh memory PostgreSQL',operational_db:0,real_image_requests:0,ai:0}));
} finally {await f.db.close();}
