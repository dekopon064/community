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
const samples = JSON.parse(execFileSync(python,["-X","utf8","test_myseoul_db.py","--fixtures"],{cwd:scripts,encoding:"utf8"}));
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
    const sqlArgs=args.map((value,index)=>name==='admin_myseoul_program_save' && index===4
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
  eq(await query(legacySql),before);eq(await query("select * from machimoa_review.ingest_sources where source_id<>'myseoul_program' order by source_id"),oldSources);
  if(process.argv.includes('--coverage-only')) {
    await db.exec("update machimoa_review.ingest_sources set enabled=true where source_id='myseoul_program'");
    const r=(await query("select * from public.start_ingest_run('myseoul_program',120)"))[0].run_id;
    const summary={coverage:'homepage_education_only',source_complete:false,homepage_scope_complete:true,discovered:0,processed:0,omitted:0,stop_reason:'homepage_scope_complete'};
    eq((await rpc('finish_myseoul_run',[r,summary,1,0])).status,'complete');
    eq((await query("select bootstrap_complete from machimoa_review.source_sync_state where source_id='myseoul_program'"))[0].bootstrap_complete,false);
    console.log(JSON.stringify({checks,transport:pg?'verified PostgreSQL':'PGlite',scope:'complete partial coverage only'}));
  } else if(process.argv.includes('--review-fixes')) {
    const base=samples.fixtures[0].item.myseoul_facts;
    for(const [object,key] of [['period','status'],['period','origin'],['endpoint','precision']]) {
      const f=structuredClone(base),p=f.periods.application[0];
      (object==='period'?p:p.endpoints[0])[key]=null;
      await fails(()=>query('select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz)',[f,samples.now]),'PT422');
    }
    for(const component of ['tuition','admission','materials']) {
      const f=structuredClone(base);f.fees=[{component,evidence:['무료','5,000원 (표기 정리)']}];
      ok((await query('select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz) result',[f,samples.now]))[0].result.reasons.includes('source_fact_conflict:'+component));
    }
    const period=structuredClone(base);period.periods.application.push(structuredClone(period.periods.application[0]));
    period.periods.application[1].endpoints[1].value='2099-10-16T18:00:00+09:00';
    const expected=(await query('select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz) result',[period,samples.now]))[0].result;
    eq(expected.application,'unknown');ok(expected.reasons.includes('source_fact_conflict:application'));
    const status=structuredClone(base);status.source_status=['신청중','신청마감'];
    eq((await query('select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz) result',[status,samples.now]))[0].result.application,'unknown');
    for(const k of ['evidence','conflicts']) {
      const f=structuredClone(base);f[k]=[{raw_payload:'must not become admin facts'}];
      await fails(()=>query('select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz)',[f,samples.now]),'PT422');
    }
    // Known narrow same-component equivalence is retained.
    const same=structuredClone(base);same.fees=[{component:'admission',evidence:['3,000원','3,000원 (입장료)']}];
    eq((await query('select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz) result',[same,samples.now]))[0].result.decision,'in_scope');
    await db.exec("update machimoa_review.ingest_sources set enabled=true where source_id='myseoul_program'");
    run=(await query("select * from public.start_ingest_run('myseoul_program',3600)"))[0].run_id;
    const packet=structuredClone(samples.fixtures.find(x=>x.name==='two_conflicts').item);
    const id=(await rpc('observe_myseoul_program',[run,[packet],null]))[0].id;
    const current=await rpc('admin_myseoul_program_detail',[id]);
    await fails(()=>rpc('admin_myseoul_program_save',[id,current.revision,current.version,{fees:[{component:'tuition',evidence:['무료','5,000원 (표기 정리)']}]},['source_fact_conflict:tuition'],'외형 변경으로 모순 유지 합성 시험',actor]),'PT422');
    eq((await rpc('admin_myseoul_program_detail',[id])).factsVersion,1);
    console.log(JSON.stringify({checks,transport:pg?'verified PostgreSQL':'PGlite',scope:'independent-review regressions only'}));
  } else {
  for(const f of samples.fixtures){const result=(await query("select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz) result",[f.item.myseoul_facts,samples.now]))[0].result;eq(result,f.expected);}
  for(const [now,want] of [["2026-10-02T23:59:00+09:00","open"],["2026-10-03T00:00:00+09:00","closed"]]){
    const f=structuredClone(samples.fixtures[0].item.myseoul_facts);f.periods.application=[{raw:"2026-10-01 ~ 2026-10-02",status:"ok",origin:"operator",label:"신청기간",endpoints:[{value:"2026-10-01",precision:"day"},{value:"2026-10-02",precision:"day"}]}];
    eq((await query("select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz) result",[f,now]))[0].result.application,want);
  }
  const acl=await query(`select n.nspname,p.proname,has_function_privilege('anon',p.oid,'execute') anon,has_function_privilege('authenticated',p.oid,'execute') auth,has_function_privilege('service_role',p.oid,'execute') service from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_review' and p.proname like 'myseoul_%' or n.nspname='public' and p.proname in ('observe_myseoul_program','finish_myseoul_run','admin_myseoul_program_detail','admin_myseoul_program_save','admin_myseoul_program_exclude')`);
  eq(acl.length,14);for(const a of acl){eq([a.anon,a.auth,a.service],[false,false,a.nspname==='public']);}
  for(const role of ["anon","authenticated"]){await fails(()=>db.exec(`set role ${role};select public.admin_myseoul_program_detail('${actor}');`),"42501");if(!pg)await db.exec("reset role");}
  eq((await query("select * from public.start_ingest_run('myseoul_program',120)"))[0].skip_reason,"source_disabled");
  await db.exec("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program'");
  run=(await query("select * from public.start_ingest_run('myseoul_program',3600)"))[0].run_id;
  const first=await rpc("observe_myseoul_program",[run,samples.fixtures.map(f=>f.item),null]);eq(first.length,14);
  const ids=Object.fromEntries(samples.fixtures.map((f,i)=>[f.name,first[i].id]));
  eq((await query("select count(*)::int n from machimoa_review.processing_jobs where processing_stage='ai_enrichment' and source_item_id in(select id from machimoa_review.source_items where source_id='myseoul_program')"))[0].n,0);
  eq((await rpc("admin_myseoul_program_detail",[ids.personal])).aiStatus,"blocked");
  let current=await rpc("admin_myseoul_program_detail",[ids.two_conflicts]);
  eq(current.result.reasons.filter(r=>r.startsWith("source_fact_conflict:")).length,2);
  const original=structuredClone(current.observedFacts),originalVersion=current.version;
  current=await rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,current.version,{application_methods:["인터넷과 방문 병행, 공식 안내 대조"]},["source_fact_conflict:application_method"],"합성 근거: 두 신청 방식 병행 확인",actor]);
  ok(current.result.reasons.includes("source_fact_conflict:tuition"));ok(!current.result.reasons.includes("source_fact_conflict:application_method"));eq(current.observedFacts,original);eq(current.factsVersion,2);eq(current.history[0].actor,actor);
  const after=await rpc("observe_myseoul_program",[run,samples.fixtures.map(f=>f.item),null]);eq(after.every(x=>x.outcome==="unchanged"),true);
  const reread=await rpc("admin_myseoul_program_detail",[ids.two_conflicts]);eq(reread.facts,current.facts);eq(reread.factsVersion,2);eq(reread.history.length,1);
  const list=await rpc("admin_review_list",["facts",0,25]);eq(list.filter(x=>x.id===ids.two_conflicts).length,1);
  await fails(()=>rpc("admin_review_detail",["facts",ids.two_conflicts]),"PT409");
  await fails(()=>rpc("admin_review_save_facts",[ids.two_conflicts,current.revision,current.version,{},actor]),"PT409");
  await fails(()=>rpc("admin_review_exclude",[ids.two_conflicts,current.revision,current.version,"bad path",actor]),"PT409");
  await fails(()=>rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,originalVersion,{fees:[{component:"tuition",evidence:["무료 확인"]}]},[],"stale",actor]),"PT409");
  await fails(()=>rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,current.version,{issues:[]},[],"forged",actor]),"PT422");
  await fails(()=>rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,current.version,{target:"다른 대상"},[],"read only",actor]),"PT422");
  await fails(()=>rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,current.version,{fees:current.facts.fees},[],"no actual change",actor]),"PT422");
  const historyCount=(await query("select count(*)::int n from machimoa_review.admin_review_events where source_item_id=$1",[ids.two_conflicts]))[0].n;
  await db.exec(`create function machimoa_review.synthetic_abort() returns trigger language plpgsql as $$begin raise exception using errcode='PT999',message='synthetic_abort';end$$;
    create trigger synthetic_abort before insert on machimoa_review.admin_review_events for each row execute function machimoa_review.synthetic_abort();`);
  await fails(()=>rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,current.version,{fees:[{component:"tuition",evidence:["무료"]}]},["source_fact_conflict:tuition"],"합성 무료 확인 근거",actor]),"PT999");
  eq((await rpc("admin_myseoul_program_detail",[ids.two_conflicts])).factsVersion,2);eq((await query("select count(*)::int n from machimoa_review.admin_review_events where source_item_id=$1",[ids.two_conflicts]))[0].n,historyCount);
  await db.exec("drop trigger synthetic_abort on machimoa_review.admin_review_events;drop function machimoa_review.synthetic_abort()");
  await db.exec(`update machimoa_review.processing_jobs set status='claimed' where source_item_id='${ids.two_conflicts}' and processing_stage='content_review'`);
  current=await rpc("admin_myseoul_program_detail",[ids.two_conflicts]);
  await fails(()=>rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,current.version,{fees:[{component:"tuition",evidence:["무료"]}]},["source_fact_conflict:tuition"],"active",actor]),"PT409");
  await fails(()=>rpc("admin_myseoul_program_exclude",[ids.two_conflicts,current.revision,current.version,"active",actor]),"PT409");
  await db.exec(`update machimoa_review.processing_jobs set status='queued' where source_item_id='${ids.two_conflicts}' and processing_stage='content_review'`);
  current=await rpc("admin_myseoul_program_detail",[ids.two_conflicts]);
  current=await rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,current.version,{fees:[{component:"tuition",evidence:["무료"]}]},["source_fact_conflict:tuition"],"합성 공식 근거 무료 확정",actor]);
  eq(current.status,"resolved");eq(current.result.decision,"in_scope");eq(current.aiStatus,"blocked");
  await fails(()=>rpc("admin_myseoul_program_save",[ids.two_conflicts,current.revision,current.version,{fees:[{component:"tuition",evidence:["무료 확인"]}]},[],"processed",actor]),"PT409");
  const changed=structuredClone(samples.fixtures.find(f=>f.name==="two_conflicts").item);changed.revision_hash="f".repeat(64);changed.myseoul_facts.source_revision=changed.revision_hash;changed.normalized_payload.description+=" 변경된 공식 안내";
  const newRev=await rpc("observe_myseoul_program",[run,[changed],{kind:"synthetic_checkpoint"}]);eq(newRev[0].outcome,"changed");
  const latest=await rpc("admin_myseoul_program_detail",[ids.two_conflicts]);eq(latest.factsVersion,1);eq(latest.observedFacts,changed.myseoul_facts);
  await fails(()=>rpc("admin_myseoul_program_exclude",[ids.two_conflicts,current.revision,current.version,"old revision",actor]),"PT409");
  const excluded=await rpc("admin_myseoul_program_exclude",[ids.two_conflicts,latest.revision,latest.version,"서비스 범위상 제외 합성 시험",actor]);eq(excluded.status,"excluded");eq(excluded.result.reasons,["manual_service_scope_excluded"]);eq(excluded.facts.target,latest.facts.target);
  const bad=structuredClone(samples.fixtures[0].item);bad.normalized_payload.parser_version="other-parser";await fails(()=>rpc("observe_myseoul_program",[run,[bad],null]),"PT422");
  const p=structuredClone(samples.fixtures[0].item.myseoul_facts);p.periods.application[0].endpoints[0].precision="second";await fails(()=>query("select machimoa_review.myseoul_evaluate($1::jsonb,$2::timestamptz)",[p,samples.now]),"PT422");
  eq((await query("select count(*)::int n from machimoa_review.source_items where source_id='myseoul_program'"))[0].n,14);
  const checkpointBefore=(await query("select committed_checkpoint from machimoa_review.source_sync_state where source_id='myseoul_program'"))[0].committed_checkpoint;
  const summary={coverage:"homepage_education_only",source_complete:false,homepage_scope_complete:false,discovered:16,processed:14,omitted:2,stop_reason:"discovery_budget_limit"};
  await fails(()=>rpc("finish_myseoul_run",[run,{...summary,source_complete:true},15,1]),"PT422");
  eq((await rpc("finish_myseoul_run",[run,summary,15,1])).status,"incomplete");
  const state=(await query("select * from machimoa_review.source_sync_state where source_id='myseoul_program'"))[0];eq(state.bootstrap_complete,false);eq(state.committed_checkpoint,checkpointBefore);
  eq((await query("select run_summary from machimoa_review.ingest_runs where id=$1",[run]))[0].run_summary,summary);
  const completeRun=(await query("select * from public.start_ingest_run('myseoul_program',120)"))[0].run_id;
  const emptyHome={coverage:'homepage_education_only',source_complete:false,homepage_scope_complete:true,discovered:0,processed:0,omitted:0,stop_reason:'homepage_scope_complete'};
  eq((await rpc('finish_myseoul_run',[completeRun,emptyHome,1,0])).status,'complete');
  eq((await query("select bootstrap_complete from machimoa_review.source_sync_state where source_id='myseoul_program'"))[0].bootstrap_complete,false);
  eq(await query(legacySql),before);eq((await query("select count(*)::int n from public.curations"))[0].n,2);
  const preserved=(await query("select count(*)::int n from machimoa_review.source_item_program_facts"))[0].n;
  await db.exec(await readFile(new URL("../rollback/20261002000300_myseoul_program_contract_down.sql",root),"utf8"));
  eq((await query("select count(*)::int n from machimoa_review.source_item_program_facts"))[0].n,preserved);
  eq((await query("select enabled from machimoa_review.ingest_sources where source_id='myseoul_program'"))[0].enabled,false);
  eq(await query(legacySql),before);
  console.log(JSON.stringify({checks,transport:pg?"verified network-none PostgreSQL":"PGlite",database:databaseName??"in memory",postgrest:"not tested",AI:"not executed",production:"not accessed"}));
  }
} finally {await db.close();}
