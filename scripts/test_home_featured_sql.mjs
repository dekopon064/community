// Synthetic PostgreSQL only, isolated transport driver required. No operational credentials.
import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {execFile} from 'node:child_process';import {randomUUID} from 'node:crypto';
import {syncBuiltinESMExports} from 'node:module';import net from 'node:net';import https from 'node:https';import http from 'node:http';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
globalThis.fetch=net.Socket.prototype.connect=https.request=https.get=http.request=http.get=()=>{throw Error('network_forbidden');};syncBuiltinESMExports();
const f=await reviewDatabase(),{db,query:q,rpc,source,candidate}=f;
const actor='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002';
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=a=>{assert.ok(a);checks++;},reject=async fn=>{await assert.rejects(fn);checks++;};
const read=n=>readFile(new URL('../supabase/migrations/'+n,import.meta.url),'utf8');
const detail=cid=>rpc('admin_review_home_featured',[cid]);
const save=(cid,d,target,position,request=randomUUID(),who=actor)=>rpc('admin_review_set_home_featured',[cid,d.revision,d.version,target,position,request,who]);
const endpoint=(value,precision='day')=>({value,precision}),known=value=>({status:'known',value}),na={status:'not_applicable',value:null},unknown={status:'unknown',value:null};
function filters(category='program'){
 return {schema:'content-filters-v1',category,topic:known(category==='program'?'culture_experience':'culture_arts'),location:unknown,
 delivery:category==='program'?known('onsite'):na,audience:category==='program'?known('other'):na,foreignerProgram:category==='program'?unknown:na,spaceKind:na,
 application:category==='program'?known({deadlineKind:'fixed',start:endpoint('2000-01-01'),end:endpoint('2099-12-31'),sourceStatus:'open'}):na,
 schedule:category==='event'?known({kind:'continuous',recurrence:null,occurrences:[{start:endpoint('2099-01-01'),end:endpoint('2099-01-02')}]}):na};
}
const fingerprint=()=>q(`select (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from public.curations c) content,
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from machimoa_review.curation_candidates c) candidates,
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from machimoa_review.source_items c) source,
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from machimoa_review.processing_jobs c) jobs,
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from machimoa_review.admin_review_events c) events,
 (select md5(string_agg(to_jsonb(c)::text,'' order by curation_id)) from machimoa_review.home_card_colors c) colors`);
async function published(key){
 await source(key,'youthcenter_content');await q("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='youthcenter_content'");
 const cid=await candidate(key,'youthcenter_content');await q("update machimoa_review.curation_candidates set category='프로그램',user_category='program',application_deadline_kind='none',source_url='https://www.youthcenter.go.kr/' where id=$1",[cid]);
 const pid=(await q('select machimoa_review.publish_curation_candidate($1,$2,null,false) id',[cid,other]))[0].id;
 await q('update public.curations set content_filters=$2 where id=$1',[pid,JSON.stringify(filters())]);return {cid,pid};
}
try{
 await db.exec(await read('20261003000000_source_images.sql'));await db.exec(await read('20261023123507_home_card_colors.sql'));
 // Minimal fixture dependencies: exact canonical function bodies, not a replay or guessed historical schema.
 const contract=await read('20261007090144_content_filter_contract.sql');
 for(const name of ['district','day','endpoint','recurrence','validate']){
  // All these functions use $$ bodies; capture exactly through their closing delimiter.
  const start=contract.indexOf('create function machimoa_review.content_filter_'+name+'(');assert(start>=0);
  const open=contract.indexOf('$$',start),close=contract.indexOf('$$;',open+2);assert(close>open);
  let definition=contract.slice(start,close+3);if(name==='validate')definition=definition.replace('content_filter_validate(','foreigner_filter_legacy_validate(');
  await db.exec(definition);
 }
 const foreign=await read('20261012114647_foreigner_program_filter.sql'),start=foreign.indexOf('create or replace function machimoa_review.content_filter_validate('),open=foreign.indexOf('$$',start),close=foreign.indexOf('$$;',open+2);
 await db.exec(foreign.slice(start,close+3));await db.exec('alter table public.curations add column content_filters jsonb');
 const before=await fingerprint(),funcs=await q("select oid,pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where pronamespace in ('public'::regnamespace,'machimoa_review'::regnamespace) order by oid");
 await db.exec(await read('20261024013711_home_featured_pins.sql'));eq(await fingerprint(),before);
 const textFix=await read('20261024020322_home_featured_utf8_text.sql');
 const originalDetail=(await q("select pg_get_functiondef('machimoa_review.home_featured_detail(uuid)'::regprocedure) definition"))[0].definition;
 const normalized=value=>value.replace(/\r\n?/g,'\n');
 await db.exec(textFix);eq(normalized((await q("select pg_get_functiondef('machimoa_review.home_featured_detail(uuid)'::regprocedure) definition"))[0].definition),normalized(originalDetail));
 const transported=originalDetail.replace('공개 글을 확인할 수 없습니다.','���� ���� Ȯ���� �� �����ϴ�.');assert.notEqual(transported,originalDetail);
 await db.exec(transported);await db.exec(textFix);eq(normalized((await q("select pg_get_functiondef('machimoa_review.home_featured_detail(uuid)'::regprocedure) definition"))[0].definition),normalized(originalDetail));eq(await fingerprint(),before);
 eq(await q('select oid,pg_get_functiondef(oid) definition,proacl::text acl from pg_proc where oid=any($1::oid[]) order by oid',[funcs.map(x=>x.oid)]),funcs);
 eq(await rpc('public_home_featured_pins',[]),[]);
 const a=await published('pin-a'),b=await published('pin-b'),c=await published('pin-c');let d=await detail(a.cid);eq(d.position,null);eq(d.stateVersion,0);eq(d.eligible,true);ok(!/PRIVATE|token|worker|content_ko/.test(JSON.stringify(d)));
 const unchanged=await fingerprint(),request=randomUUID(),first=await save(a.cid,d,a.pid,1,request);
 eq(first.position,1);eq(first.stateVersion,1);ok(first.version!==d.version);eq(await fingerprint(),unchanged);eq(await save(a.cid,d,a.pid,1,request),first);
 await reject(()=>save(a.cid,d,a.pid,1));await reject(()=>save(a.cid,d,a.pid,2,request));await reject(()=>save(a.cid,d,a.pid,1,request,other));
 eq(await save(a.cid,first,a.pid,1),first);eq((await q('select count(*)::int n from machimoa_review.home_featured_history'))[0].n,1);
 let bd=await detail(b.cid);const second=await save(b.cid,bd,b.pid,2);eq(second.position,2);eq(second.pins.map(x=>x.id),[a.pid,b.pid]);
 await reject(async()=>save(c.cid,await detail(c.cid),c.pid,1));await reject(()=>save(a.cid,d,a.pid,1,request));
 const reordered=await save(b.cid,second,b.pid,1);eq(reordered.pins.map(x=>x.id),[b.pid,a.pid]);eq(await rpc('public_home_featured_pins',[]),[{id:b.pid,position:1},{id:a.pid,position:2}]);eq(await fingerprint(),unchanged);
 const history=await q('select version,action,actor,position,before_pins,after_pins,created_at is not null stamp from machimoa_review.home_featured_history order by version');
 eq(history.map(x=>x.action),['pin','pin','reorder']);ok(history.every(x=>x.actor===actor&&x.stamp));eq(history[2].before_pins,[a.pid,b.pid]);eq(history[2].after_pins,[b.pid,a.pid]);
 // Public eligibility affects exposure, never silently rewrites saved pins/history.
 bd=await detail(b.cid);await q('update public.curations set is_published=false where id=$1',[b.pid]);await reject(()=>save(b.cid,bd,b.pid,2));
 eq(await rpc('public_home_featured_pins',[]),[{id:a.pid,position:2}]);const hidden=await detail(b.cid);eq(hidden.position,1);eq(hidden.eligible,false);eq(hidden.pins[0].eligible,false);
 const removed=await save(a.cid,await detail(a.cid),b.pid,null);eq(removed.pins.map(x=>x.id),[a.pid]);eq(removed.position,1);
 // Global + content/revision fingerprints also protect edits from a different published-item view.
 const stale=await detail(c.cid);await save(a.cid,await detail(a.cid),a.pid,null);await reject(()=>save(c.cid,stale,c.pid,1));
 const changed=await detail(c.cid);await q("update machimoa_review.curation_candidates set summary_ko='합성 변경' where id=$1",[c.cid]);await reject(()=>save(c.cid,changed,c.pid,1));
 const changedPublic=await detail(c.cid);await q("update public.curations set summary_ko='합성 공개 변경' where id=$1",[c.pid]);await reject(()=>save(c.cid,changedPublic,c.pid,1));
 await reject(()=>rpc('admin_review_set_home_featured',[c.cid,'f'.repeat(64),(changedPublic).version,c.pid,1,randomUUID(),actor]));
 await save(a.cid,await detail(a.cid),a.pid,1);const staleOther=await detail(c.cid);await q("update public.curations set title_ja='別の合成変更' where id=$1",[a.pid]);await reject(()=>save(c.cid,staleOther,c.pid,2));
 // Eligibility parity: exact application endpoints, unknown status, permanent information and event occurrences.
 const eligible=async(data,now='2026-10-24T12:00:00+09:00',category='program',extra={})=>{
  await q("update public.curations set user_category=$2,content_filters=$3,event_start_on=$4,event_end_on=$5,application_deadline_kind=case when $2='program' then 'none' else null end where id=$1",[c.pid,category,JSON.stringify(data),category==='event'?(extra.start??'2000-01-01'):null,category==='event'?(extra.end??'2000-01-02'):null]);
  return (await q('select machimoa_review.home_featured_eligible(c,$2::timestamptz) ok from public.curations c where id=$1',[c.pid,now]))[0].ok;
 };
 let data=filters();data.application.value.end=endpoint('2026-10-24');eq(await eligible(data,'2026-10-24T23:59:59.999+09:00'),true);eq(await eligible(data,'2026-10-25T00:00:00+09:00'),false);
 data.application.value.end=endpoint('2026-10-24T12:00:00+09:00','minute');eq(await eligible(data),true);eq(await eligible(data,'2026-10-24T12:00:00.001+09:00'),false);
 data=filters();data.application.value.sourceStatus='unknown';eq(await eligible(data),false);data.application.value.sourceStatus='closed';eq(await eligible(data),false);
 data.application.value={deadlineKind:'none',start:null,end:null,sourceStatus:'open'};eq(await eligible(data),true);data.application=unknown;eq(await eligible(data),false);
 data=filters();data.application.value.sourceStatus='not_started';data.application.value.start=endpoint('2026-10-25');eq(await eligible(data),false);data.application.value.start=endpoint('2026-10-24');eq(await eligible(data),true);
 data=filters('event');eq(await eligible(data,undefined,'event'),true);data.schedule=unknown;eq(await eligible(data,undefined,'event'),false);
 eq(await eligible(null,undefined,'event',{start:'2026-10-25',end:'2026-10-26'}),true);eq(await eligible(null,undefined,'event'),false);eq(await eligible(null),false);
 await q("update public.curations set user_category='program',application_deadline_kind='none',event_start_on=null,event_end_on=null,content_filters=$2 where id=$1",[c.pid,JSON.stringify(filters())]);
 await q("update public.curations set content_ja=null where id=$1",[c.pid]);eq((await detail(c.cid)).eligible,false);await reject(async()=>save(c.cid,await detail(c.cid),c.pid,2));await q("update public.curations set content_ja='本文' where id=$1",[c.pid]);
 const writesBefore=await q('select to_jsonb(h) value from machimoa_review.home_featured_history h order by version');await detail(a.cid);await rpc('public_home_featured_pins',[]);eq(await q('select to_jsonb(h) value from machimoa_review.home_featured_history h order by version'),writesBefore);
 for(const role of ['anon','authenticated','service_role']){
  for(const table of ['home_featured_state','home_featured_history'])for(const permission of ['select','insert','update','delete'])eq((await q('select has_table_privilege($1,$2,$3) ok',[role,'machimoa_review.'+table,permission]))[0].ok,false);
  for(const fn of ['public.admin_review_home_featured(uuid)','public.admin_review_set_home_featured(uuid,text,text,uuid,integer,uuid,uuid)'])eq((await q("select has_function_privilege($1,$2,'execute') ok",[role,fn]))[0].ok,role==='service_role');
  eq((await q("select has_function_privilege($1,'public.public_home_featured_pins()','execute') ok",[role]))[0].ok,true);
  for(const fn of ['machimoa_review.home_featured_detail(uuid)','machimoa_review.home_featured_eligible(public.curations,timestamp with time zone)'])eq((await q("select has_function_privilege($1,$2,'execute') ok",[role,fn]))[0].ok,false);
 }
 const meta=await q("select p.prosecdef,p.proconfig,p.proowner='postgres'::regrole owner from pg_proc p where p.proname in ('admin_review_home_featured','admin_review_set_home_featured','public_home_featured_pins')");for(const fn of meta){eq(fn.prosecdef,true);eq(fn.owner,true);ok(fn.proconfig.includes('search_path=""'));}
 eq((await q("select count(*)::int n from pg_class where oid in ('machimoa_review.home_featured_state'::regclass,'machimoa_review.home_featured_history'::regclass) and relrowsecurity"))[0].n,2);
 // Real parallel sessions, global fence and final max2 survive contention.
 if(process.env.MACHIMOA_HOME_COLOR_CONTAINER){
  const snapshot=await detail(c.cid),preserved=await fingerprint();const execute=position=>new Promise(resolve=>{
   const sql=`set role service_role;select public.admin_review_set_home_featured('${c.cid}','${snapshot.revision}','${snapshot.version}','${c.pid}',${position},'${randomUUID()}','${actor}');`;
   const child=execFile('docker',['--context','desktop-linux','exec','-i',process.env.MACHIMOA_HOME_COLOR_CONTAINER,'psql','-XqAt','-U','postgres','-v','ON_ERROR_STOP=1'],{timeout:20000},e=>resolve(!e));child.stdin.end(sql);
  });eq((await Promise.all([execute(1),execute(2)])).filter(Boolean).length,1);eq(await fingerprint(),preserved);eq((await detail(c.cid)).pins.length,2);
 }
 console.log(JSON.stringify({passed:checks,engine:'isolated PostgreSQL',operational_db:0,ai:0,content_mutations_by_feature:0}));
}finally{await db.close();}
