// Same synthetic contract checks against PGlite or an explicitly verified,
// already-running, network-none Docker PostgreSQL. No service startup or .env.
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { pathToFileURL, fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
const root = new URL("../supabase/migrations/", import.meta.url);
const scripts = fileURLToPath(new URL("./", import.meta.url));
const python = process.env.MACHIMOA_TEST_PYTHON;
if (!python) throw new Error("Explicit local test Python required");
const samples = JSON.parse(execFileSync(python,["-X","utf8","test_myseoul_ai.py","--fixtures"],{cwd:scripts,encoding:"utf8"}));
const pg = process.argv.includes("--postgres");
let db, databaseName, sqlExec;
if (pg) {
  const docker = process.argv[process.argv.indexOf("--docker")+1];
  const container = process.argv[process.argv.indexOf("--container")+1];
  if (!process.argv.includes("--docker") || !process.argv.includes("--container") || !/^machimoa-program-ai-[a-f0-9]{8}$/.test(container)) throw new Error("Explicit isolated Docker required");
  const info=JSON.parse(execFileSync(docker,["inspect",container],{encoding:"utf8"}))[0];
  const h=info.HostConfig;
  if (!info.State.Running || h.NetworkMode!=="none" || Object.keys(h.PortBindings??{}).length || h.Binds?.length || h.Mounts?.length || info.Mounts?.length || info.Config.Labels?.["machimoa.purpose"]!=="isolated-program-ai-concurrency") throw new Error("Isolation/running verification failed");
  const context=JSON.parse(execFileSync(docker,["context","inspect"],{encoding:"utf8"}))[0];
  if (context.Endpoints.docker.Host!=="npipe:////./pipe/dockerDesktopLinuxEngine") throw new Error("Local engine required");
  databaseName="machimoa_myseoul_"+randomUUID().replaceAll("-","").slice(0,12);
  execFileSync(docker,["exec",container,"createdb","-U","postgres",databaseName],{stdio:"pipe"});
  sqlExec=(sql)=>{
    try {return execFileSync(docker,["exec","-i",container,"psql","-X","-qAt","-U","postgres","-d",databaseName,"-v","ON_ERROR_STOP=1","-v","VERBOSITY=sqlstate"],{input:sql,encoding:"utf8",timeout:15000,stdio:["pipe","pipe","pipe"]}).trim();}
    catch(e){const code=/ERROR:\s+([A-Z0-9]{5})/.exec(String(e.stderr))?.[1]??"local_sql_error";const err=new Error(code);err.code=code;throw err;}
  };
  const lit=v=>v===null?"NULL":typeof v==="number"?String(v):typeof v==="boolean"?String(v):"'"+(typeof v==="object"?JSON.stringify(v):String(v)).replaceAll("'","''")+"'";
  db={exec:async sql=>sqlExec(sql),query:async(sql,args=[])=>({rows:JSON.parse(sqlExec("select coalesce(json_agg(q),'[]'::json) from ("+sql.replace(/\$(\d+)/g,(_,n)=>lit(args[Number(n)-1]))+") q;"))}),close:async()=>{}};
} else {
  const modulePath=process.env.MACHIMOA_PGLITE_MODULE;if(!modulePath)throw new Error("Explicit existing PGlite required");
  const {PGlite}=await import(pathToFileURL(modulePath).href);db=new PGlite();
}
const query=async(sql,args=[]) => (await db.query(sql,args)).rows;
const literal=v=>v===null?"NULL":typeof v==="number"?String(v):"'"+(typeof v==="object"?JSON.stringify(v):String(v)).replaceAll("'","''")+"'";
const rpc=async(name,args)=>{
  if(pg){
    // PostgREST accepts JSON resolve arrays; direct PostgreSQL needs text[].
    const sqlArgs=args.map((value,index)=>(name==='admin_myseoul_program_save' && index===4 || name==='myseoul_collection_state' && index===1)
      ? 'ARRAY['+value.map(literal).join(',')+']::text[]' : literal(value));
    return JSON.parse(sqlExec("begin;set local role service_role;select public."+name+"("+sqlArgs.join(",")+")::text;commit;"));
  }
  return db.transaction(async tx=>{await tx.exec("set local role service_role");return (await tx.query(`select public.${name}(${args.map((_,i)=>`$${i+1}`).join(",")}) value`,args)).rows[0].value;});
};
const actor="00000000-0000-4000-8000-000000000001";
let checks=0;const ok=(v)=>{assert.ok(v);checks++;};const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const fails=async(fn,code)=>{await assert.rejects(fn,e=>e.code===code);checks++;};
let run;
try{
  await db.exec(`do $$ begin
    if not exists(select 1 from pg_roles where rolname='anon') then create role anon;end if;
    if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated;end if;
    if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role bypassrls;end if;
  end $$;
  create table public.curations(id uuid primary key default gen_random_uuid(),slug text not null unique,category text,title text not null,summary text,content text not null,created_at timestamptz not null default now());
  alter table public.curations enable row level security;
  insert into public.curations(slug,title,summary,content) values('baseline-one','one','one','one'),('baseline-two','two','two','two');`);
  const files=(await readdir(root)).filter(n=>n.endsWith(".sql")&&(n>="20260827022301"&&n<"20260903"||n>="20260913"&&n<="20261001000001_seoul_program_ai.sql")).sort();
  for(const name of files){await db.exec(await readFile(new URL(name,root),"utf8"));if(name.startsWith("20260827022301"))await db.exec(`insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) select 'youthcenter','baseline-'||n,repeat('a',64),'candidate-'||n,'title','summary','content','{}','success' from generate_series(1,4)n;`);}
  const legacySql=`select n.nspname,p.proname,pg_get_functiondef(p.oid) definition,p.proacl::text acl from pg_proc p join pg_namespace n on n.oid=p.pronamespace where (n.nspname='machimoa_review' and p.proname in ('program_validate','program_evaluate','program_refresh','claim_processing_jobs','canonical_source_id','upsert_source_observations_v4')) or (n.nspname='public' and p.proname in ('observe_seoul_program','admin_program_save','admin_program_exclude')) order by n.nspname,p.proname`;
  const before=await query(legacySql),oldSources=await query("select * from machimoa_review.ingest_sources order by source_id");
  // Main admin contracts precede the renumbered My pair; test that actual order.
  for (const name of ['20261002000000_admin_review_ai_queue.sql','20261002000100_admin_review_trash.sql','20261002000200_admin_review_trash_publication.sql']) {
    await db.exec(await readFile(new URL(name,root),'utf8'));
  }
  await db.exec(await readFile(new URL("20261002000300_myseoul_program_contract.sql",root),"utf8"));

  await db.exec(await readFile(new URL('20261002000400_myseoul_program_ai.sql',root),'utf8'));
  const retainedLegacy=await query(legacySql);
  const previousAcl=await query("select oid::regprocedure::text name,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'machimoa_review'::regnamespace) order by 1");
  await db.exec(await readFile(new URL('20261003000001_myseoul_change_collection.sql',root),'utf8'));
  const afterAcl=await query("select oid::regprocedure::text name,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'machimoa_review'::regnamespace) order by 1");
  eq(await query(legacySql),retainedLegacy);
  eq(afterAcl.filter(a=>previousAcl.some(b=>a.name===b.name)),previousAcl);
  for(const role of ['anon','authenticated']) await fails(()=>db.exec(`set role ${role};select public.myseoul_collection_state('${actor}',array[]::text[])`),'42501');
  await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program'");
  run=(await query("select * from public.start_ingest_run('myseoul_program',3600)"))[0].run_id;
  const packet=structuredClone(samples.packets[0]),observe=p=>rpc('observe_myseoul_program',[run,[p],null]);
  // Distinct application/operation carry conflicts remain independently editable.
  const observed=structuredClone(packet.myseoul_facts),operator=structuredClone(observed),changedSource=structuredClone(observed);
  operator.periods.application[0].endpoints.at(-1).value='2099-10-30'+operator.periods.application[0].endpoints.at(-1).value.slice(10);
  operator.periods.operation[0].endpoints.at(-1).value='2099-11-29'+operator.periods.operation[0].endpoints.at(-1).value.slice(10);
  changedSource.periods.application[0].endpoints.at(-1).value='2099-10-29'+changedSource.periods.application[0].endpoints.at(-1).value.slice(10);
  changedSource.periods.operation[0].endpoints.at(-1).value='2099-11-28'+changedSource.periods.operation[0].endpoints.at(-1).value.slice(10);
  const merged=(await query('select machimoa_review.myseoul_merge_facts($1,$2,$3) f',[changedSource,observed,operator]))[0].f;
  ok(merged.issues.some(x=>x.code==='source_change_conflict:application'));
  ok(merged.issues.some(x=>x.code==='source_change_conflict:operation'));
  const first=(await observe(packet))[0],id=first.id;
  eq((await observe(packet))[0].outcome,'unchanged');
  const claim=(await rpc('claim_myseoul_program_ai',[id,first.revision,'synthetic',300]))[0];ok(claim);
  const candidate=(await rpc('finish_myseoul_program_ai',[claim.jobId,claim.revision,claim.factsVersion,claim.claimedAt,claim.leaseUntil,claim.workerId,samples.outputs[0]])).candidateId;
  const provenance=await query('select * from machimoa_review.program_candidate_inputs where candidate_id=$1',[candidate]);
  await db.query("update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{qualification_note}',to_jsonb('이전 운영자 확인 근거'::text)),facts_version=2 where source_item_id=$1",[id]);
  const next=structuredClone(packet);next.revision_hash='b'.repeat(64);next.myseoul_facts.source_revision=next.revision_hash;
  next.myseoul_facts.description+=' 원문 추가 안내';next.normalized_payload.description=next.myseoul_facts.description;
  eq((await observe(next))[0].outcome,'changed');
  let detail=await rpc('admin_review_detail',['candidates',candidate]);
  ok(detail.programInfo.inputChanged);eq(detail.programInfo.canPublish,false);
  eq((await rpc('admin_review_list',['candidates',0,25])).filter(x=>x.id===candidate).length,1);
  eq((await rpc('admin_myseoul_program_detail',[id])).facts.qualification_note,'이전 운영자 확인 근거');
  eq((await query("select count(*)::int n from machimoa_review.processing_jobs where source_item_id=$1 and revision_hash=$2 and processing_stage='ai_enrichment' and status='queued'",[id,next.revision_hash]))[0].n,0);
  await fails(()=>rpc('admin_review_publish',[candidate,detail.revision,detail.version,actor]),'PT409');
  detail=await rpc('admin_myseoul_review_change',[candidate,detail.revision,detail.version,'no_impact','새 설명은 기존 요약에 영향을 주지 않음을 확인',null,actor]);
  eq(detail.programInfo.changeReviewed,true);eq(detail.programInfo.canPublish,true);
  eq(await query('select * from machimoa_review.program_candidate_inputs where candidate_id=$1',[candidate]),provenance);
  await db.exec("update machimoa_review.ingest_sources set enabled=false where source_id='myseoul_program'");
  eq((await rpc('admin_review_detail',['candidates',candidate])).programInfo.canPublish,false);
  await db.exec("update machimoa_review.ingest_sources set enabled=true where source_id='myseoul_program'");
  const previous=detail;
  await db.query('update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id=$1 and revision_hash=$2',[id,next.revision_hash]);
  await fails(()=>rpc('admin_myseoul_review_change',[candidate,previous.revision,previous.version,'no_impact','오래된 확인',null,actor]),'PT409');
  detail=await rpc('admin_review_detail',['candidates',candidate]);eq(detail.programInfo.canPublish,false);
  detail=await rpc('admin_myseoul_review_change',[candidate,detail.revision,detail.version,'no_impact','최신 사실도 내용 영향 없음을 확인',null,actor]);
  // Synthetic publication only: verifies the existing locked guard.
  detail=await rpc('admin_review_publish',[candidate,detail.revision,detail.version,actor]);eq(detail.status,'published');ok(detail.publishedSlug);
  const publicBefore=await query('select * from public.curations where id=$1',[detail.publishedId]);
  const again=structuredClone(next);again.revision_hash='c'.repeat(64);again.myseoul_facts.source_revision=again.revision_hash;again.myseoul_facts.description+=' 두 번째 변경';again.normalized_payload.description=again.myseoul_facts.description;
  await observe(again);
  eq(await query('select * from public.curations where id=$1',[detail.publishedId]),publicBefore);
  eq((await rpc('admin_review_list',['candidates',0,25])).some(x=>x.id===candidate),true);
  detail=await rpc('admin_review_detail',['candidates',candidate]);
  const edited={...detail.content,contentKo:detail.content.contentKo+' 확인한 새 안내',contentJa:detail.content.contentJa+' 確認済みの新しい案内'};
  await db.exec("update machimoa_review.ingest_sources set enabled=false where source_id='myseoul_program'");
  await fails(()=>rpc('admin_myseoul_review_change',[candidate,detail.revision,detail.version,'edited','비활성 source 공개 수정 차단',edited,actor]),'PT409');
  eq(await query('select * from public.curations where id=$1',[detail.publishedId]),publicBefore);
  await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='testing_only' where source_id='myseoul_program'");
  await fails(()=>rpc('admin_myseoul_review_change',[candidate,detail.revision,detail.version,'no_impact','미승인 permission 확인 차단',null,actor]),'PT409');
  eq(await query('select * from public.curations where id=$1',[detail.publishedId]),publicBefore);
  await db.exec("update machimoa_review.ingest_sources set permission_status='approved_noncommercial' where source_id='myseoul_program'");
  detail=await rpc('admin_review_detail',['candidates',candidate]);
  detail=await rpc('admin_myseoul_review_change',[candidate,detail.revision,detail.version,'edited','새 안내를 두 언어에 직접 반영',edited,actor]);
  const publicAfter=(await query('select * from public.curations where id=$1',[detail.publishedId]))[0];
  eq(publicAfter.content_ko,edited.contentKo);eq(publicAfter.is_published,true);eq(detail.status,'published');
  eq((await rpc('admin_review_list',['candidates',0,25])).some(x=>x.id===candidate),false);
  // Public metadata/content may have been edited through an existing pathway.
  await db.query("update public.curations set application_deadline_on=application_deadline_on+1,content_ko=content_ko||' 기존 공개 편집' where id=$1",[detail.publishedId]);
  const publicChanged=await rpc('admin_review_detail',['candidates',candidate]);
  ok(publicChanged.content.contentKo.endsWith(' 기존 공개 편집'));
  eq(publicChanged.programInfo.changeReviewed,false);
  await fails(()=>rpc('admin_myseoul_review_change',[candidate,publicChanged.revision,publicChanged.version,'no_impact','실제 공개 기간 차이를 무시하지 않음',null,actor]),'PT422');
  await db.query('update public.curations set application_deadline_on=application_deadline_on-1 where id=$1',[detail.publishedId]);
  // A failed history insert rolls back both the candidate and public edit.
  detail=await rpc('admin_review_detail',['candidates',candidate]);
  const beforeFailure=await query('select * from public.curations where id=$1',[detail.publishedId]);
  await db.exec("create function public.synthetic_history_failure() returns trigger language plpgsql as $$ begin if NEW.note='synthetic rollback' then raise exception 'synthetic';end if;return NEW;end $$;create trigger synthetic_history_failure before insert on machimoa_review.admin_review_events for each row execute function public.synthetic_history_failure()");
  await fails(()=>rpc('admin_myseoul_review_change',[candidate,detail.revision,detail.version,'edited','synthetic rollback',{...detail.content,contentKo:detail.content.contentKo+' 실패 시험'},actor]),'P0001');
  eq(await query('select * from public.curations where id=$1',[detail.publishedId]),beforeFailure);
  const conflict=structuredClone(again);conflict.revision_hash='d'.repeat(64);conflict.myseoul_facts.source_revision=conflict.revision_hash;conflict.myseoul_facts.qualification_note='새 원문 자격 안내';
  await observe(conflict);const cf=await rpc('admin_myseoul_program_detail',[id]);
  ok(cf.result.reasons.includes('source_change_conflict:qualification_note'));ok(cf.editableFields.includes('qualification_note'));
  detail=await rpc('admin_review_detail',['candidates',candidate]);
  await fails(()=>rpc('admin_myseoul_review_change',[candidate,detail.revision,detail.version,'no_impact','충돌을 무시할 수 없음',null,actor]),'PT409');
  // A superseded active claim is not forcibly reset; expired one cannot block human work.
  await db.query("update machimoa_review.processing_jobs set status='claimed',claim_lease_until=clock_timestamp()+interval '10 minutes' where id=$1",[claim.jobId]);
  const activeNext=structuredClone(conflict);activeNext.revision_hash='e'.repeat(64);activeNext.myseoul_facts.source_revision=activeNext.revision_hash;activeNext.myseoul_facts.description+=' 세 번째 변경';
  await observe(activeNext);
  eq((await query('select status from machimoa_review.processing_jobs where id=$1',[claim.jobId]))[0].status,'claimed');
  await fails(()=>rpc('finish_myseoul_program_ai',[claim.jobId,claim.revision,claim.factsVersion,claim.claimedAt,claim.leaseUntil,claim.workerId,samples.outputs[0]]),'PT409');
  let current=await rpc('admin_myseoul_program_detail',[id]);
  const patch={qualification_note:'새 원문 자격 안내를 운영자가 확인했습니다'};
  await fails(()=>rpc('admin_myseoul_program_save',[id,current.revision,current.version,patch,['source_change_conflict:qualification_note'],'새 자격 근거 확인',actor]),'PT409');
  await db.query("update machimoa_review.processing_jobs set claim_lease_until=clock_timestamp()-interval '1 second' where id=$1",[claim.jobId]);
  current=await rpc('admin_myseoul_program_detail',[id]);
  current=await rpc('admin_myseoul_program_save',[id,current.revision,current.version,patch,['source_change_conflict:qualification_note'],'새 자격 근거 확인',actor]);
  eq(current.status,'resolved');eq((await query('select status from machimoa_review.processing_jobs where id=$1',[claim.jobId]))[0].status,'cancelled');
  // Source reversion preserves human exclusion and the existing revision's facts.
  await db.query("update machimoa_review.source_item_program_facts set manual_excluded=true where source_item_id=$1 and revision_hash=$2",[id,activeNext.revision_hash]);
  await observe(packet);eq((await rpc('admin_myseoul_program_detail',[id])).status,'excluded');
  eq((await query('select count(*)::int n from machimoa_review.curation_candidates where id=$1',[candidate]))[0].n,1);
  const state=await rpc('myseoul_collection_state',[run,[packet.external_key]]);ok(state.known.includes(packet.external_key));
  const summary={coverage:'homepage_education_only',source_complete:false,homepage_scope_complete:false,discovered:10,selected:8,processed:8,homepage_processed:6,omitted:4,failed:0,new_selected:6,recheck_selected:2,stop_reason:'discovery_budget_limit'};
  eq((await rpc('finish_myseoul_collection',[run,summary,9,packet.external_key,packet.external_key])).status,'incomplete');
  eq((await query("select bootstrap_complete from machimoa_review.source_sync_state where source_id='myseoul_program'"))[0].bootstrap_complete,false);
  await db.exec("update machimoa_review.ingest_sources set enabled=false where source_id='myseoul_program'");
  const auditCount=(await query('select count(*)::int n from machimoa_review.myseoul_change_reviews'))[0].n;
  await db.exec(await readFile(new URL('../rollback/20261003000001_myseoul_change_collection_down.sql',root),'utf8'));
  eq((await query('select count(*)::int n from machimoa_review.myseoul_change_reviews'))[0].n,auditCount);
  eq((await query("select count(*)::int n from machimoa_review.myseoul_change_function_backup where pg_get_functiondef(name::regprocedure)<>definition"))[0].n,0);
  console.log(JSON.stringify({checks,mode:pg?'isolated_postgresql':'pglite',scope:'new My source-change and collection contracts only'}));
} catch(e){console.error(JSON.stringify({checks,code:e.code??e.name,message:e.code?e.message:'test_assertion_failed'}));process.exitCode=1;} finally {await db.close();}
