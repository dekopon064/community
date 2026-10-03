// Same synthetic contract checks against PGlite or an explicitly verified,
// already-running, network-none Docker PostgreSQL. No service startup or .env.
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { execFileSync, spawn } from "node:child_process";
import { pathToFileURL, fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
const root = new URL("../supabase/migrations/", import.meta.url);
const scripts = fileURLToPath(new URL("./", import.meta.url));
const python = process.env.MACHIMOA_TEST_PYTHON;
if (!python) throw new Error("Explicit local test Python required");
const samples = JSON.parse(execFileSync(python,["-X","utf8","test_myseoul_ai.py","--fixtures"],{cwd:scripts,encoding:"utf8"}));
const pg = process.argv.includes("--postgres");
if (!pg) throw new Error("This new suite requires explicitly isolated PostgreSQL");
let db, databaseName, sqlExec, docker, container;
if (pg) {
  docker = process.argv[process.argv.indexOf("--docker")+1];
  container = process.argv[process.argv.indexOf("--container")+1];
  if (!process.argv.includes("--docker") || !process.argv.includes("--container") || !/^machimoa-program-ai-[a-f0-9]{8}$/.test(container)) throw new Error("Explicit isolated Docker required");
  const info=JSON.parse(execFileSync(docker,["inspect",container],{encoding:"utf8"}))[0];
  const h=info.HostConfig;
  if (!info.State.Running || h.NetworkMode!=="none" || Object.keys(h.PortBindings??{}).length || h.Binds?.length || h.Mounts?.length || info.Mounts?.length || info.Config.Labels?.["machimoa.purpose"]!=="isolated-program-ai-concurrency") throw new Error("Isolation/running verification failed");
  const context=JSON.parse(execFileSync(docker,["context","inspect"],{encoding:"utf8"}))[0];
  if (context.Endpoints.docker.Host!=="npipe:////./pipe/dockerDesktopLinuxEngine") throw new Error("Local engine required");
  databaseName="machimoa_myseoul_ai_"+randomUUID().replaceAll("-","").slice(0,12);
  execFileSync(docker,["exec",container,"createdb","-U","postgres",databaseName],{stdio:"pipe"});
  console.log(JSON.stringify({isolatedTestDatabase:databaseName}));
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
    const sqlArgs=args.map((value,index)=>name==='admin_myseoul_program_save' && index===4
      ? 'ARRAY['+value.map(literal).join(',')+']::text[]'
      : name==='admin_review_ai_queue' && index===2 ? 'ARRAY['+value.map(literal).join(',')+']::uuid[]' : literal(value));
    return JSON.parse(sqlExec("begin;set local role service_role;select to_jsonb(public."+name+"("+sqlArgs.join(",")+"))::text;commit;"));
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
  // Main admin contracts precede the renumbered My pair; test that actual order.
  for (const name of ['20261002000000_admin_review_ai_queue.sql','20261002000100_admin_review_trash.sql','20261002000200_admin_review_trash_publication.sql']) {
    await db.exec(await readFile(new URL(name,root),'utf8'));
  }
  await db.exec(await readFile(new URL('20261002000300_myseoul_program_contract.sql',root),'utf8'));
  const otherSources=await query("select * from machimoa_review.ingest_sources where source_id<>'myseoul_program' order by source_id");
  const previousAcl=await query("select oid::regprocedure::text name,proacl::text acl from pg_proc where pronamespace in ('machimoa_review'::regnamespace,'public'::regnamespace) order by 1");
  await db.exec(await readFile(new URL('20261002000400_myseoul_program_ai.sql',root),'utf8'));
  eq(await query("select * from machimoa_review.ingest_sources where source_id<>'myseoul_program' order by source_id"),otherSources);
  const afterAcl=await query("select oid::regprocedure::text name,proacl::text acl from pg_proc where pronamespace in ('machimoa_review'::regnamespace,'public'::regnamespace) order by 1");
  eq(afterAcl.filter(a=>previousAcl.some(b=>b.name===a.name)),previousAcl);
  const acl=await query("select n.nspname,p.proname,has_function_privilege('anon',p.oid,'execute') anon,has_function_privilege('authenticated',p.oid,'execute') auth,has_function_privilege('service_role',p.oid,'execute') service from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.proname in ('myseoul_ai_check','claim_myseoul_program_ai','finish_myseoul_program_ai','fail_myseoul_program_ai')");
  eq(acl.length,4);for(const a of acl)eq([a.anon,a.auth,a.service],[false,false,a.nspname==='public']);
  for(const role of ['anon','authenticated'])await fails(()=>db.exec(`set role ${role};select public.claim_myseoul_program_ai('${actor}',repeat('a',64),'test',300)`),'42501');
  eq((await query("select enabled,permission_status from machimoa_review.ingest_sources where source_id='myseoul_program'"))[0],{enabled:false,permission_status:'testing_only'});
  await db.exec("update machimoa_review.ingest_sources set enabled=true where source_id='myseoul_program'");
  run=(await query("select * from public.start_ingest_run('myseoul_program',3600)"))[0].run_id;
  const add=async(n,cat=0)=>{
    const p=structuredClone(samples.packets[cat]),program=n.toString(16).toUpperCase().padStart(32,'0');
    p.external_key=p.external_key.split(':')[0]+':'+program;p.revision_hash=n.toString(16).padStart(64,'0');
    p.normalized_payload.program_id=program;p.myseoul_facts.source_revision=p.revision_hash;
    p.myseoul_facts.official_url=p.myseoul_facts.official_url.replace(/prgrm_no=[A-F0-9]{32}/,'prgrm_no='+program);
    p.normalized_payload.official_url=p.myseoul_facts.official_url;p.min_fields.source_url=p.myseoul_facts.official_url;
    const id=(await rpc('observe_myseoul_program',[run,[p],null]))[0].id;
    return {id,revision:p.revision_hash,packet:p};
  };
  const claim=t=>rpc('claim_myseoul_program_ai',[t.id,t.revision,'synthetic-worker',600]);
  const finish=(c,out=samples.outputs[0])=>rpc('finish_myseoul_program_ai',[c.jobId,c.revision,c.factsVersion,c.claimedAt,c.leaseUntil,c.workerId,out]);
  const holding=(sql)=>{
    const p=spawn(docker,['exec','-i',container,'psql','-X','-qAt','-U','postgres','-d',databaseName,'-v','ON_ERROR_STOP=1','-v','VERBOSITY=sqlstate']);
    let output='',errors='';let notify,notReady;let marked=false;
    const ready=new Promise((resolve,reject)=>{notify=resolve;notReady=reject;});p.stdout.on('data',v=>{output+=v;if(output.includes('LOCK_READY')){marked=true;notify();}});p.stderr.on('data',v=>errors+=v);
    const done=new Promise((resolve,reject)=>{p.on('error',()=>{const e=Error('local_process_failed');notReady(e);reject(e);});p.on('close',code=>{const e=Error(/ERROR:\s+([A-Z0-9]{5})/.exec(errors)?.[1]??'local_sql_error');if(!marked)notReady(e);code===0?resolve(output):reject(e);});});
    done.catch(()=>{});
    const timer=setTimeout(()=>{p.kill();notReady(Error("local_timeout"));},12000);done.finally(()=>clearTimeout(timer)).catch(()=>{});
    p.stdin.end(sql);return {ready,done};
  };
  if(process.argv.includes('--main-integration')) {
    // Narrow integration only; do not rerun the prior My 73/104 suites.
    const t=await add(801);
    await db.exec("update machimoa_review.ingest_sources set permission_status='approved_noncommercial' where source_id='myseoul_program'");
    await db.exec(`select machimoa_review.myseoul_refresh('${t.id}')`);
    let queue=await rpc('admin_review_ai_queue',[0,25,[]]);
    const entry=queue.items.find(x=>x.sourceItemId===t.id);ok(entry);eq(entry.sourceName,'myseoul_program');eq(entry.status,'queued');
    const c=(await claim(t))[0],done=await finish(c);
    eq((await rpc('admin_review_ai_queue',[0,25,[c.jobId]])).observed[0].resultState,'ready');
    let candidate=await rpc('admin_review_detail',['candidates',done.candidateId]);
    eq(candidate.programInfo.canPublish,true);
    candidate=await rpc('admin_review_save_candidate',[done.candidateId,candidate.revision,candidate.version,{...candidate.content,summaryKo:candidate.content.summaryKo+' 합성 통합 수정'},actor]);
    eq(candidate.status,'pending');
    await db.exec(`update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='${t.id}'`);
    eq((await rpc('admin_review_ai_queue',[0,25,[c.jobId]])).observed[0].resultState,'input_changed');
    eq((await rpc('admin_review_detail',['candidates',done.candidateId])).programInfo.canPublish,false);
    await fails(()=>rpc('admin_review_publish',[done.candidateId,candidate.revision,candidate.version,actor]),'PT409');
    // My exclusion remains its own contract, not the legacy trash/11-field path.
    const x=await add(802);
    await db.exec(`update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{application_methods}','[]') where source_item_id='${x.id}';select machimoa_review.myseoul_refresh('${x.id}')`);
    const xi=await rpc('admin_myseoul_program_detail',[x.id]);eq(xi.status,'open');
    await fails(()=>rpc('admin_review_exclude_reason',[x.id,xi.revision,xi.version,'custom','합성 제외',actor,'00000000-0000-4000-8000-000000000080']),'PT422');
    const excluded=await rpc('admin_myseoul_program_exclude',[x.id,xi.revision,xi.version,'합성 My 제외',actor]);eq(excluded.status,'excluded');
    eq((await rpc('admin_review_trash',[0,25])).items.some(e=>e.sourceItemId===x.id),false);
    // Main youth exclusion -> restoration -> confirmation survives My item override.
    const key='main-integration-youth';
    const y=sqlExec(`insert into machimoa_review.source_items(source_id,external_key,revision_hash,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload,has_source_url,body_usable)
      values('youthcenter_policy',${literal(key)},repeat('a',64),now(),now(),'missing','missing','target','{"title":"합성 청년"}','{"plcyNm":"합성 청년","plain_text":"합성 본문"}',true,true) returning id;`);
    await db.exec(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes) values('${y}',repeat('a',64),'content_review','queued',clock_timestamp(),clock_timestamp(),array['policy_lifecycle_uncertain'])`);
    let yi=await rpc('admin_review_detail',['facts',y]);eq(yi.restoredReviewPending,false);
    await rpc('admin_review_exclude_reason',[y,yi.revision,yi.version,'service_not_suitable','',actor,'00000000-0000-4000-8000-000000000081']);
    let e=(await rpc('admin_review_trash',[0,25])).items.find(e=>e.sourceItemId===y);ok(e);eq(e.canRestore,true);
    const restored=await rpc('admin_review_restore',[e.id,e.revision,e.version,actor,'00000000-0000-4000-8000-000000000082']);
    yi=restored.item;eq(yi.restoredReviewPending,true);ok(yi.reasons.includes('restored_review_pending'));
    yi=await rpc('admin_review_save_restored',[y,yi.revision,yi.version,{...yi.facts,productType:'policy_reference',scope:'nationwide',foreignEligibility:'eligible',evidence:'합성 원문 전국 참여'},actor]);
    eq(yi.restoredReviewPending,false);ok(!yi.reasons.includes('restored_review_pending'));
    // Existing read queue remains available, neither REST nor provider runs here.
    ok((await rpc('admin_review_ai_queue',[0,25,[]])).items.every(e=>['myseoul_program','youthcenter_policy','youthcenter_content','seoul_reservation'].includes(e.sourceName)));
    const before=(await query('select count(*)::int n from machimoa_review.program_candidate_inputs'))[0].n;
    await db.exec(await readFile(new URL('../rollback/20261002000400_myseoul_program_ai_down.sql',root),'utf8'));
    eq((await query('select count(*)::int n from machimoa_review.program_candidate_inputs'))[0].n,before);
    eq((await rpc('admin_review_detail',['facts',y])).restoredReviewPending,false);
    console.log(JSON.stringify({checks,databaseName,scope:'main-first migration order, My queue/current facts, legacy trash restoration, ACL and safe rollback',transport:'direct PostgreSQL',provider_calls:0}));
  } else if(process.argv.includes('--review-fixes')) {
    await db.exec("update machimoa_review.ingest_sources set permission_status='approved_noncommercial' where source_id='myseoul_program'");
    const t=await add(701),c=(await claim(t))[0];
    await rpc('fail_myseoul_program_ai',[c.jobId,c.claimedAt,c.leaseUntil,c.workerId,'ai_schema_error']);
    const retry=()=>query('select status,retry_count,next_retry_at from machimoa_review.processing_jobs where id=$1',[c.jobId]);
    const before=await retry();await db.exec(`select machimoa_review.myseoul_refresh('${t.id}')`);eq(await retry(),before);
    await db.exec(`update machimoa_review.processing_jobs set status='failed',retry_count=3,next_retry_at=null where id='${c.jobId}'`);
    const failed=await retry();await db.exec(`select machimoa_review.myseoul_refresh('${t.id}')`);eq(await retry(),failed);
    const event=await add(702,1),ec=(await claim(event))[0];
    const adapter=JSON.parse(execFileSync(python,['-X','utf8','test_myseoul_ai.py','--context-check'],{cwd:scripts,encoding:'utf8',input:JSON.stringify(ec)}));
    eq(adapter.source,'myseoul_program');eq(adapter.category,'event');
    const candidate=await finish(ec,samples.outputs[1]);
    await db.exec(`insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes) values('${event.id}','${event.revision}','content_review','queued',clock_timestamp(),clock_timestamp(),array['synthetic_open_review'])`);
    eq((await rpc('admin_review_detail',['candidates',candidate.candidateId])).programInfo.canPublish,false);
    const broken=holding('select missing_synthetic_function();');
    await assert.rejects(broken.ready);await assert.rejects(broken.done);checks+=2;
    console.log(JSON.stringify({checks,databaseName,scope:'narrow corrections: retry state, SQL-to-Python input, open-review read gate, pre-marker failure'}));
  } else {
  const t=await add(101);
  eq(await claim(t),[]);eq((await rpc('admin_myseoul_program_detail',[t.id])).aiStatus,'blocked');
  await db.exec("update machimoa_review.ingest_sources set permission_status='approved_noncommercial' where source_id='myseoul_program'");
  await db.exec(`select machimoa_review.myseoul_refresh('${t.id}')`);
  eq((await rpc('admin_myseoul_program_detail',[t.id])).aiStatus,'queued');
  eq(await query("select * from public.claim_processing_jobs('ai_enrichment',10,'legacy-worker',300)"),[]);
  eq(await rpc('claim_myseoul_program_ai',[actor,t.revision,'synthetic-worker',600]),[]);
  const c=(await claim(t))[0];eq(c.source,'myseoul_program');eq(c.publicCategory,'program');
  eq(await claim(t),[]);
  const done=await finish(c);eq(done.outcome,'inserted');
  eq((await finish(c)).candidateId,done.candidateId);
  eq((await query('select count(*)::int n from machimoa_review.program_candidate_inputs where job_id=$1',[c.jobId]))[0].n,1);
  let item=await rpc('admin_review_detail',['candidates',done.candidateId]);
  eq(item.source.name,'myseoul_program');eq(item.category,'program');eq(item.status,'pending');eq(item.programInfo.canPublish,true);
  const meta=(await query('select input_facts,api_category from machimoa_review.program_candidate_inputs where candidate_id=$1',[done.candidateId]))[0];
  eq(meta.input_facts.fees,t.packet.myseoul_facts.fees);eq(meta.input_facts.periods,t.packet.myseoul_facts.periods);
  const candidate=(await query('select application_deadline_kind,event_start_on,event_end_on,raw_payload from machimoa_review.curation_candidates where id=$1',[done.candidateId]))[0];
  eq(candidate.application_deadline_kind,'fixed');eq(candidate.event_start_on,null);ok(!('input_facts' in candidate.raw_payload));
  const edited={...item.content,summaryKo:item.content.summaryKo+' 합성 수정'};
  item=await rpc('admin_review_save_candidate',[done.candidateId,item.revision,item.version,edited,actor]);eq(item.content.summaryKo,edited.summaryKo);
  await db.exec(`update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='${t.id}'`);
  item=await rpc('admin_review_detail',['candidates',done.candidateId]);eq(item.programInfo.inputChanged,true);eq(item.programInfo.canPublish,false);
  await fails(()=>rpc('admin_review_publish',[done.candidateId,item.revision,item.version,actor]),'PT409');
  await fails(()=>db.exec(`select machimoa_review.publish_curation_candidate('${done.candidateId}','${actor}',null,false)`),'PT409');
  item=await rpc('admin_review_reject',[done.candidateId,item.revision,item.version,'합성 시험 반려',actor]);eq(item.status,'rejected');
  const ev=await add(102,1),ec=(await claim(ev))[0],ed=await finish(ec,samples.outputs[1]);
  const er=(await query('select user_category,application_deadline_kind,event_start_on,event_end_on from machimoa_review.curation_candidates where id=$1',[ed.candidateId]))[0];
  eq(er.user_category,'event');eq(er.application_deadline_kind,null);ok(er.event_start_on&&er.event_end_on);
  // All completion fences tested on new synthetic targets, no provider involved.
  for(const mode of ['facts','revision','closed','excluded','permission','lease']){
    const x=await add(200+checks),xc=(await claim(x))[0];ok(xc);
    if(mode==='facts')await db.exec(`update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='${x.id}'`);
    if(mode==='revision')await db.exec(`update machimoa_review.source_items set revision_hash=repeat('f',64) where id='${x.id}'`);
    if(mode==='closed')await db.exec(`update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{source_status}','["신청마감"]') where source_item_id='${x.id}'`);
    if(mode==='excluded')await db.exec(`update machimoa_review.source_item_program_facts set manual_excluded=true where source_item_id='${x.id}'`);
    if(mode==='permission')await db.exec("update machimoa_review.ingest_sources set enabled=false where source_id='myseoul_program'");
    if(mode==='lease')await db.exec(`update machimoa_review.processing_jobs set claim_lease_until=clock_timestamp()-interval '1 second' where id='${xc.jobId}'`);
    await fails(()=>finish(xc),'PT409');
    eq((await query('select count(*)::int n from machimoa_review.program_candidate_inputs where job_id=$1',[xc.jobId]))[0].n,0);
    await db.exec(`update machimoa_review.processing_jobs set status='cancelled' where id='${xc.jobId}';update machimoa_review.ingest_sources set enabled=true where source_id='myseoul_program'`);
  }
  const attempt=await add(400),a=(await claim(attempt))[0];
  await db.exec(`update machimoa_review.processing_jobs set claim_lease_until=clock_timestamp()-interval '1 second' where id='${a.jobId}'`);
  const b=(await claim(attempt))[0];ok(b.claimedAt!==a.claimedAt);
  await fails(()=>finish(a),'PT409');
  await fails(()=>rpc('fail_myseoul_program_ai',[a.jobId,a.claimedAt,a.leaseUntil,a.workerId,'ai_schema_error']),'PT409');
  await db.exec(`update machimoa_review.processing_jobs set claim_lease_until=clock_timestamp()-interval '1 second' where id='${b.jobId}';update machimoa_review.ingest_sources set enabled=false where source_id='myseoul_program'`);
  eq(await claim(attempt),[]);eq((await query('select status from machimoa_review.processing_jobs where id=$1',[b.jobId]))[0].status,'queued');
  await db.exec(`select machimoa_review.myseoul_refresh('${attempt.id}')`);
  eq((await query('select status from machimoa_review.processing_jobs where id=$1',[b.jobId]))[0].status,'cancelled');
  await db.exec("update machimoa_review.ingest_sources set enabled=true where source_id='myseoul_program'");
  const failt=await add(500),fc=(await claim(failt))[0];
  await db.exec("create function machimoa_review.synthetic_abort() returns trigger language plpgsql as $$begin raise exception using errcode='PT999',message='synthetic_abort';end$$;create trigger synthetic_abort before insert on machimoa_review.program_candidate_inputs for each row execute function machimoa_review.synthetic_abort();");
  await fails(()=>finish(fc),'PT999');
  eq((await query('select count(*)::int n from machimoa_review.curation_candidates where source_item_id=$1',[failt.packet.external_key]))[0].n,0);
  eq((await query('select status from machimoa_review.processing_jobs where id=$1',[fc.jobId]))[0].status,'claimed');
  await db.exec('drop trigger synthetic_abort on machimoa_review.program_candidate_inputs;drop function machimoa_review.synthetic_abort()');
  eq(await rpc('fail_myseoul_program_ai',[fc.jobId,fc.claimedAt,fc.leaseUntil,fc.workerId,'ai_schema_error']),'queued');
  // Independent PostgreSQL processes; wait for first connection's row-lock marker.
  const race=await add(600);
  const first=holding(`begin;select public.claim_myseoul_program_ai('${race.id}','${race.revision}','synthetic-worker',600);select 'LOCK_READY';select pg_sleep(1);commit;`);
  await first.ready;eq(await claim(race),[]);await first.done;
  const rc=(await query(`select jsonb_build_object('jobId',id,'revision',revision_hash,'factsVersion',1,'claimedAt',claimed_at,'leaseUntil',claim_lease_until,'workerId',claimed_by) c from machimoa_review.processing_jobs where source_item_id=$1 and processing_stage='ai_enrichment'`,[race.id]))[0].c;
  const fs=`select public.finish_myseoul_program_ai(${[rc.jobId,rc.revision,1,rc.claimedAt,rc.leaseUntil,rc.workerId,samples.outputs[0]].map(literal).join(',')})`;
  const completed=holding(`begin;${fs};select 'LOCK_READY';select pg_sleep(1);commit;`);
  await completed.ready;eq((await finish(rc)).outcome,'duplicate');await completed.done;
  eq((await query('select count(*)::int n from machimoa_review.program_candidate_inputs where job_id=$1',[rc.jobId]))[0].n,1);
  // Facts update wins a controlled lock race: stale finish waits, then fails.
  const race2=await add(601),r2=(await claim(race2))[0];
  const updating=holding(`begin;select id from machimoa_review.source_items where id='${race2.id}' for update;update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='${race2.id}';select 'LOCK_READY';select pg_sleep(1);commit;`);
  await updating.ready;await fails(()=>finish(r2),'PT409');await updating.done;
  await db.exec(`update machimoa_review.processing_jobs set status='cancelled' where id='${r2.jobId}'`);
  const savedCount=(await query("select count(*)::int n from machimoa_review.program_candidate_inputs where schema_version='myseoul-program-facts-v1-local'"))[0].n;
  await db.exec(await readFile(new URL('../rollback/20261002000400_myseoul_program_ai_down.sql',root),'utf8'));
  eq((await query("select count(*)::int n from machimoa_review.program_candidate_inputs where schema_version='myseoul-program-facts-v1-local'"))[0].n,savedCount);
  eq((await query("select enabled from machimoa_review.ingest_sources where source_id='myseoul_program'"))[0].enabled,false);
  console.log(JSON.stringify({checks,transport:'direct PostgreSQL',independent_connection_races:3,databaseName,postgrest:'not tested',provider_calls:0,rollback:'references preserved'}));
  }
} finally {await db.close();}
