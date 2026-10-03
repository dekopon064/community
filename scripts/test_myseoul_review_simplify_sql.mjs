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
  for(const name of ['20261003000000_source_images.sql','20261003000001_myseoul_change_collection.sql','20261003000100_myseoul_list_discovery.sql','20261003000200_myseoul_source_images.sql','20261003000300_myseoul_candidate_images.sql']) await db.exec(await readFile(new URL(name,root),'utf8'));
  const migration=await readFile(new URL('20261003000400_myseoul_review_simplify.sql',root),'utf8');
  const legacy=await query(legacySql);
  const oldSave=await query("select pg_get_functiondef('public.admin_myseoul_program_save(uuid,text,text,jsonb,text[],text,uuid)'::regprocedure) body,proacl::text acl from pg_proc where oid='public.admin_myseoul_program_save(uuid,text,text,jsonb,text[],text,uuid)'::regprocedure");
  await db.exec(migration);
  eq(await query(legacySql),legacy);
  eq(await query("select pg_get_functiondef('public.admin_myseoul_program_save(uuid,text,text,jsonb,text[],text,uuid)'::regprocedure) body,proacl::text acl from pg_proc where oid='public.admin_myseoul_program_save(uuid,text,text,jsonb,text[],text,uuid)'::regprocedure"),oldSave);
  const down=await readFile(new URL('../rollback/20261003000400_myseoul_review_simplify_down.sql',root),'utf8');
  await db.exec(down); await db.exec(migration);
  eq((await query("select has_function_privilege('anon','public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)','execute') a,has_function_privilege('authenticated','public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)','execute') b,has_function_privilege('service_role','public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)','execute') c"))[0],{a:false,b:false,c:true});
  eq((await query("select has_table_privilege('service_role','machimoa_review.myseoul_fact_edits','select') a"))[0].a,false);
  await db.exec("update machimoa_review.ingest_sources set enabled=true where source_id='myseoul_program'");
  run=(await query("select * from public.start_ingest_run('myseoul_program',3600)"))[0].run_id;
  const packet=name=>structuredClone(samples.fixtures.find(f=>f.name===name).item);
  const observe=async p=>(await rpc('observe_myseoul_program',[run,[p],null]))[0].id;
  const detail=id=>rpc('admin_myseoul_program_detail',[id]);
  const save=(item,patch)=>rpc('admin_myseoul_program_save_v2',[item.id,item.revision,item.version,patch,actor]);
  let item=await detail(await observe(packet('two_conflicts')));
  const original=structuredClone(item.observedFacts);
  const next=await save(item,{application_methods:item.facts.application_methods});
  eq(next.factsVersion,2);eq(next.observedFacts,original);
  ok(!next.result.reasons.includes('source_fact_conflict:application_method'));
  ok(next.result.reasons.includes('source_fact_conflict:tuition'));
  await fails(()=>save(item,{application_methods:['인터넷 신청']}),'PT409');
  await fails(()=>save(next,{fees:next.facts.fees}),'PT422');
  item=await save(next,{fees:[{component:'tuition',evidence:['무료']}]});
  ok(!item.result.reasons.includes('source_fact_conflict:tuition'));
  await fails(()=>save(item,{fees:[{component:'tuition',evidence:['무료']}]}),'PT409');
  const periods=packet('personal');
  periods.myseoul_facts.issues.push({code:'source_fact_conflict:application',field:'application',evidence:['합성 상단','합성 본문']},{code:'source_fact_conflict:operation',field:'operation',evidence:['합성 상단','합성 본문']});
  item=await detail(await observe(periods));
  const op=structuredClone(item.facts.periods.operation);
  let partial=await save(item,{periods:{application:item.facts.periods.application}});
  eq(partial.facts.periods.operation,op);ok(!partial.result.reasons.includes('source_fact_conflict:application'));ok(partial.result.reasons.includes('source_fact_conflict:operation'));
  await fails(()=>save(partial,{periods:{application:partial.facts.periods.application}}),'PT422');
  await fails(()=>save(partial,{periods:{operation:[{...op[0],endpoints:[{value:'2099-13-99',precision:'day'}]}]}}),'PT422');
  const eventsBefore=(await query('select count(*)::int n from machimoa_review.admin_review_events'))[0].n;
  await db.exec("create function public.fail_my_review_audit() returns trigger language plpgsql as $$ begin raise exception 'synthetic audit failure';end $$;create trigger fail_my_review_audit before insert on machimoa_review.myseoul_fact_edits for each row execute function public.fail_my_review_audit()");
  await fails(()=>save(partial,{periods:{operation:op}}),'P0001');
  eq((await detail(partial.id)).version,partial.version);eq((await query('select count(*)::int n from machimoa_review.admin_review_events'))[0].n,eventsBefore);
  await db.exec('drop trigger fail_my_review_audit on machimoa_review.myseoul_fact_edits;drop function public.fail_my_review_audit()');
  await db.exec(`update machimoa_review.processing_jobs set status='claimed',claim_lease_until=clock_timestamp()+interval '10 minutes' where source_item_id='${partial.id}'`);
  await fails(()=>save(partial,{periods:{operation:op}}),'PT409');
  await db.exec(`update machimoa_review.processing_jobs set status='queued',claim_lease_until=null where source_item_id='${partial.id}'`);
  partial=await save(partial,{periods:{operation:op}});ok(!partial.result.reasons.includes('source_fact_conflict:operation'));
  item=await detail(await observe(packet('missing_mode')));
  item=await save(item,{delivery_mode:'online'});
  ok(!item.result.reasons.includes('delivery_mode_unknown'));ok(item.result.reasons.includes('online_residence_unknown'));eq(item.facts.activity_region,'unknown');eq(item.facts.venue,'');
  await fails(()=>save(item,{activity_evidence:['forged source evidence']}),'PT422');
  await fails(()=>rpc('admin_myseoul_program_exclude',[item.id,item.revision,item.version,'',actor]),'PT422');
  await fails(()=>rpc('admin_myseoul_program_save_v2',[item.id,item.revision,item.version,{residence_scope:'nationwide'},null]),'PT422');
  const audits=await query('select e.actor,e.note,e.changed_fields,a.before_patch,a.after_patch from machimoa_review.myseoul_fact_edits a join machimoa_review.admin_review_events e on e.id=a.event_id order by e.id');
  ok(audits.length>=4);ok(audits.every(a=>a.actor===actor&&a.note==='사실 확인 저장 · 시스템 처리 기록'));ok(audits.some(a=>a.before_patch.application_methods));
  if(pg){
    // Two independent psql connections race on the same revision/version.
    const {execFile}=await import('node:child_process');
    const racePacket=packet('two_conflicts');racePacket.external_key='F'.repeat(32)+':'+racePacket.external_key.split(':')[1];
    racePacket.normalized_payload.center_id='F'.repeat(32);racePacket.myseoul_facts.official_url=racePacket.normalized_payload.official_url=racePacket.min_fields.source_url=racePacket.myseoul_facts.official_url.replace(/cntr_no=[A-F0-9]{32}/,'cntr_no='+'F'.repeat(32));
    const raced=await detail(await observe(racePacket));
    const race=patch=>new Promise(resolve=>{
      const sql=`begin;set local role service_role;select public.admin_myseoul_program_save_v2(${[raced.id,raced.revision,raced.version,patch,actor].map(literal).join(',')});commit;`;
      const child=execFile(process.argv[process.argv.indexOf('--docker')+1],['exec','-i',process.argv[process.argv.indexOf('--container')+1],'psql','-X','-qAt','-U','postgres','-d',databaseName,'-v','ON_ERROR_STOP=1','-v','VERBOSITY=sqlstate'],{timeout:15000},(e,out,err)=>resolve(e?/ERROR:\s+([A-Z0-9]{5})/.exec(err)?.[1]:'ok'));child.stdin.end(sql);
    });
    eq((await Promise.all([race({application_methods:['인터넷 신청']}),race({fees:[{component:'tuition',evidence:['무료']}]})])).sort(),['PT409','ok'].sort());
    eq((await detail(raced.id)).factsVersion,2);
  }
  eq((await query("select count(*)::int n from machimoa_review.curation_candidates where source='myseoul_program'"))[0].n,0);
  eq((await query("select count(*)::int n from machimoa_review.processing_jobs where processing_stage='ai_enrichment' and status in ('claimed','completed')"))[0].n,0);
  await fails(()=>db.exec(down),'P0001');
  eq((await query("select to_regprocedure('public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)') is not null present"))[0].present,true);
  console.log(JSON.stringify({checks,mode:pg?'isolated_postgresql':'pglite',database:databaseName??'memory',scope:'My facts save v2 and rollback only',concurrency:pg?'two independent psql connections':'not tested'}));
} catch(e){console.error(JSON.stringify({checks,code:e.code??e.name,message:e.code?e.message:'test_assertion_failed'}));process.exitCode=1;} finally {await db.close();}
