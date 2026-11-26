// Isolated PostgreSQL WASM. Queue, source and trash services are synthetic.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(process.env.PGLITE_MODULE ? pathToFileURL(process.env.PGLITE_MODULE).href : '@electric-sql/pglite');
const db=new PGlite();
const scalar=async(sql,args=[])=>Object.values((await db.query(sql,args)).rows[0])[0];
const run=()=>crypto.randomUUID(), actor=run(), rev='a'.repeat(64), hash='b'.repeat(64);
const id=n=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0');
const job=n=>'10000000-0000-4000-8000-'+String(n).padStart(12,'0');
const move=(rid,item)=>scalar('select public.suitability_exclude($1,$2,$3,$4)',[rid,item,actor,run()]);
const freeze=async(rid,key=hash)=>{
 await scalar('select public.suitability_freeze($1)',[rid]);
 assert.equal(await scalar("select public.suitability_start($1,'1.0',$2,now())",[rid,key]),true);
};
const report=rid=>scalar('select public.suitability_report($1)',[rid]);
const claim=rid=>scalar('select public.suitability_claim($1)',[rid]);
const save=(rid,item)=>scalar('select public.suitability_save($1,$2,$3)',[rid,item,JSON.stringify({group:'keep',quote:'성곽 답사',clause:'K02',reason:'지역 역사',question:'',note:''})]);
try {
 await db.exec(`
 create role service_role;create role anon;create role authenticated;
 create schema machimoa_review;
 set search_path=machimoa_review,public;
 create table source_items(id uuid primary key,source_id text,external_key text,revision_hash text,version text,
  facts boolean,ai boolean,body text);
 create table processing_jobs(id uuid,source_item_id uuid,revision_hash text,processing_stage text,status text,claim_lease_until timestamptz);
 create table ingest_review_decisions(source_item_id uuid,revision_hash text,revoked_at timestamptz,review_type text,decision text,reviewer text,reason_codes text[]);
 create table admin_exclusion_episodes(source_item_id uuid,restored_at timestamptz,
  revision_hash text default repeat('a',64),note text);
 create table curation_candidates(source text,source_item_id text,source_revision_hash text);
 create function canonical_source_id(text) returns text language sql immutable as $$select $1$$;
 create function ai_queue_executable(uuid) returns boolean language sql stable as $$
 select exists(select from machimoa_review.processing_jobs j join machimoa_review.source_items s on s.id=j.source_item_id
 where j.id=$1 and s.ai and j.status='queued' and s.revision_hash=j.revision_hash) $$;
 create function public.admin_review_list(text,int,int) returns jsonb language sql stable as $$
 select coalesce(jsonb_agg(to_jsonb(p)),'[]') from(select id,source_id "sourceName" from machimoa_review.source_items where facts order by id offset $2 limit $3)p $$;
 create function public.admin_review_ai_queue(int,int,uuid[]) returns jsonb language sql stable as $$
 select jsonb_build_object('items',coalesce(jsonb_agg(to_jsonb(p)),'[]')) from(select j.id "jobId",s.source_id "sourceName",
 j.status,true "currentRevision" from machimoa_review.processing_jobs j join machimoa_review.source_items s on j.source_item_id=s.id
 where s.ai order by j.id offset $1 limit $2)p $$;
 create function public.admin_program_detail(uuid) returns jsonb language sql stable as $$
 select jsonb_build_object('id',id,'status',case when facts then 'open' else 'resolved' end,'revision',revision_hash,'version',version,
 'source',jsonb_build_object('title',external_key,'body',body)) from machimoa_review.source_items where id=$1 $$;
 create function public.admin_myseoul_program_detail(uuid) returns jsonb language sql stable as $$select public.admin_program_detail($1)$$;
 create function public.admin_ai_queue_review_detail(uuid) returns jsonb language sql stable as $$
 select jsonb_build_object('status',j.status,'canExclude',j.status='queued','version',s.version,'review',public.admin_program_detail(s.id))
 from machimoa_review.processing_jobs j join machimoa_review.source_items s on s.id=j.source_item_id where j.id=$1 $$;
 create function public.admin_review_exclude_reason(uuid,text,text,text,text,uuid,uuid) returns jsonb language plpgsql as $$
 begin update machimoa_review.source_items set facts=false where id=$1 and facts and revision_hash=$2 and version=$3 and $4 in ('service_not_suitable','custom');
 if not found then raise sqlstate 'PT409';end if;
 insert into machimoa_review.admin_exclusion_episodes values($1,null,$2,$5);
 return jsonb_build_object('episodeId',gen_random_uuid(),'item',jsonb_build_object('id',$1));end $$;
 create function public.admin_ai_queue_exclude(uuid,text,text,uuid,text,uuid) returns jsonb language plpgsql as $$
 declare sid uuid; begin update machimoa_review.processing_jobs j set status='cancelled' from machimoa_review.source_items s
 where j.id=$1 and j.status='queued' and s.id=j.source_item_id and s.version=$3 and s.revision_hash=$2 and $5='service_not_suitable' returning s.id into sid;
 if not found then raise sqlstate 'PT409';end if;
 insert into machimoa_review.admin_exclusion_episodes values(sid,null);
 return jsonb_build_object('sourceItemId',sid,'status','cancelled');end $$;
 `);
 await db.exec(readFileSync(new URL('../supabase/migrations/20261125032553_content_suitability_review.sql',import.meta.url),'utf8'));
 async function seed(n){
  await db.query('insert into machimoa_review.source_items values($1,$2,$3,$4,$5,$6,$7,$8)',[id(n),n%2?'seoul_reservation':'myseoul_program','key'+n,rev,hash,n<=27,n>=27,'성곽 답사']);
  if(n>=27)await db.query("insert into machimoa_review.processing_jobs values($1,$2,$3,'ai_enrichment','queued')",[job(n),id(n),rev]);
 }
 for(let n=1;n<=56;n++)await seed(n);
 await db.query('insert into machimoa_review.admin_exclusion_episodes values($1,null)',[id(9)]);
 await db.query('insert into machimoa_review.curation_candidates values($1,$2,$3)',['myseoul_program','key8',rev]);
 const decide=item=>db.query("insert into machimoa_review.ingest_review_decisions values($1,$2,null,'relevance','approve_ai',$3,'{}')",[item,rev,actor]);
 await decide(id(7));
 const first=run();await freeze(first);
 await seed(57);
 const snap=await report(first);
 assert.equal(snap.items.length,53);
 assert.equal(snap.items.filter(x=>x.key==='key27').length,1);
 assert.ok(!snap.items.some(x=>['key7','key8','key9','key57'].includes(x.key)));
 const reserved=await claim(first); // simulate lost response; never reclaim this decision
 let item,completed=0;
 while(item=await claim(first)){assert.equal(await save(first,item.id),true);completed++;}
 assert.equal(completed,52);
 const second=run();await freeze(second);
 const onlyNew=await claim(second);
 assert.equal(onlyNew.id,id(57));await save(second,onlyNew.id);
 assert.equal(await claim(second),null);
 assert.equal((await report(second)).items.filter(x=>x.reused).length,52);
 await decide(id(5));assert.equal(await move(first,id(5)),'skipped');
 assert.equal(await move(first,reserved.id),'skipped');
 assert.equal(await move(first,id(1)),'moved');
 assert.equal(await move(first,id(1)),'moved');
 assert.equal(await move(first,id(28)),'moved');
 assert.equal(await scalar('select status from machimoa_review.processing_jobs where id=$1',[job(28)]),'cancelled');
 await db.query("update machimoa_review.processing_jobs set status='claimed' where id=$1",[job(29)]);
 assert.equal(await move(first,id(29)),'skipped');
 await db.query("update machimoa_review.source_items set version='changed' where id=$1",[id(3)]);
 assert.equal(await move(first,id(3)),'skipped');
 assert.equal(await scalar('select facts from machimoa_review.source_items where id=$1',[id(4)]),true);
 assert.equal(await scalar('select status from machimoa_review.processing_jobs where id=$1',[job(30)]),'queued');
 assert.equal((await report(first)).items.filter(x=>x.moved).length,2);
 await db.query('update machimoa_review.source_items set revision_hash=$1 where id=$2',['d'.repeat(64),id(4)]);
 const changed=run();await freeze(changed);
 let changedItem=await claim(changed);assert.equal(changedItem.id,id(4));assert.equal(await claim(changed),null);
 await scalar('select public.suitability_release_unsent($1,$2)',[changed,changedItem.id]);
 assert.equal((await claim(changed)).id,id(4));
 const third=run();await freeze(third,'c'.repeat(64));assert.ok(await claim(third));
 for(const role of ['anon','authenticated'])assert.equal(await scalar("select has_function_privilege($1,'public.suitability_exclude(uuid,uuid,uuid,uuid)','execute')",[role]),false);
 // The report already exists when the new reader is installed.
 const before=(await report(first)).items.find(row=>row.id===id(12));
 await db.exec(readFileSync(new URL('../supabase/migrations/20261126060135_suitability_current_stage.sql',import.meta.url),'utf8'));
 const stage=async()=> (await report(first)).items.find(row=>row.id===id(12));
 assert.equal((await stage()).currentStage,'facts');
 await db.query('update machimoa_review.source_items set facts=false,ai=true where id=$1',[id(12)]);
 await db.query("insert into machimoa_review.processing_jobs values($1,$2,$3,'ai_enrichment','queued')",[job(12),id(12),rev]);
 assert.equal((await stage()).currentStage,'ai');
 await db.query("update machimoa_review.processing_jobs set status='claimed',claim_lease_until=now()-interval '1 hour' where id=$1",[job(12)]);
 assert.equal((await stage()).currentStage,'unknown');
 await db.query("update machimoa_review.processing_jobs set claim_lease_until=now()+interval '1 hour' where id=$1",[job(12)]);
 for(const [status,expected] of [['claimed','processing'],['completed','unknown']]){
  await db.query('update machimoa_review.processing_jobs set status=$1 where id=$2',[status,job(12)]);
  assert.equal((await stage()).currentStage,expected);
 }
 for(const [source,key,revision] of [['seoul_reservation','key12',rev],['myseoul_program','key11',rev],['myseoul_program','key12','old']]){
  await db.query('insert into machimoa_review.curation_candidates values($1,$2,$3)',[source,key,revision]);
  assert.equal((await stage()).currentStage,'unknown');
 }
 await db.query('insert into machimoa_review.curation_candidates values($1,$2,$3)',['myseoul_program','key12',rev]);
 const {currentStage,...history}=await stage();
 assert.equal(currentStage,'candidate');assert.deepEqual(history,before);
 assert.equal((await report(second)).items.find(r=>r.id===id(12)).reused,true);
 assert.equal((await report(first)).items.find(r=>r.id===id(4)).currentStage,'unknown');
 const itemRow=async n=>(await report(first)).items.find(r=>r.id===id(n));
 const prior=await itemRow(6);
 await scalar("select public.admin_review_exclude_reason($1,$2,$3,'custom','중복',$4,$5)",[id(6),rev,hash,actor,run()]);
 assert.equal((await itemRow(6)).currentStage,'unknown');
 await db.exec(readFileSync(new URL('../supabase/migrations/20261126142306_suitability_active_exclusion_stage.sql',import.meta.url),'utf8'));
 assert.deepEqual(await itemRow(6),{...prior,currentStage:'excluded'});
 assert.equal((await itemRow(12)).currentStage,'candidate');
 assert.equal((await itemRow(1)).currentStage,'excluded');
 assert.equal((await itemRow(1)).moved,true);
 await db.query("insert into machimoa_review.admin_exclusion_episodes values($1,null,'other revision','다른 원문')",[id(10)]);
 assert.equal((await itemRow(10)).currentStage,'facts');
 await db.query("update machimoa_review.source_items set revision_hash='changed' where id=$1",[id(6)]);
 assert.equal((await itemRow(6)).currentStage,'unknown');
 await db.query("update machimoa_review.source_items set revision_hash=$1 where id=$2",[rev,id(6)]);
 await db.query('update machimoa_review.admin_exclusion_episodes set restored_at=now() where source_item_id in ($1,$2)',[id(1),id(6)]);
 await db.query('update machimoa_review.source_items set facts=true where id in ($1,$2)',[id(1),id(6)]);
 assert.deepEqual(await itemRow(6),prior);
 assert.equal((await itemRow(1)).currentStage,'facts');
 assert.equal((await itemRow(1)).moved,true);
 assert.equal(await scalar('select note from machimoa_review.admin_exclusion_episodes where source_item_id=$1 and restored_at is not null',[id(6)]),'중복');
 await db.query('update machimoa_review.source_items set facts=false,ai=true where id=$1',[id(6)]);
 await db.query("insert into machimoa_review.processing_jobs values($1,$2,$3,'ai_enrichment','queued')",[job(6),id(6),rev]);
 assert.equal((await itemRow(6)).currentStage,'ai');
 console.log('PASS existing custom exclusion and restoration to facts/AI, mismatched revision, retained decision, note and bulk receipt');
 for(const role of ['anon','authenticated'])assert.equal(await scalar("select has_function_privilege($1,'public.suitability_report(uuid)','execute')",[role]),false);
 console.log('PASS historical report: facts -> AI -> processing -> unconfirmed -> matching candidate; history, identity, revision and privileges');
 console.log('PASS multi-page snapshot, source identity, pending claim, reuse, new policy, selected trash, conflict, active job, permissions');
} finally { await db.close(); }
