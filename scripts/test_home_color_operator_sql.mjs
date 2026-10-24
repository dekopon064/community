// Fresh network-none PostgreSQL + synthetic rows. Never a shared/operational DB.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {syncBuiltinESMExports} from 'node:module';
import https from 'node:https';import http from 'node:http';import net from 'node:net';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
globalThis.fetch=https.request=https.get=http.request=http.get=net.Socket.prototype.connect=()=>{throw Error('network_forbidden');};syncBuiltinESMExports();
const f=await reviewDatabase(),{db,query:q,rpc,source,candidate}=f;
const actor='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002';
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=a=>{assert.ok(a);checks++;},reject=async fn=>{await assert.rejects(fn);checks++;};
const file='20261023234936_home_color_operator_choice.sql';
const detail=cid=>rpc('admin_review_home_color',[cid]);
const save=(cid,d,tone,request=randomUUID(),who=actor)=>rpc('admin_review_set_home_color',[cid,d.revision,d.version,tone,request,who]);
const fingerprint=async()=>q(`select
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from public.curations c) content,
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from machimoa_review.curation_candidates c) candidate,
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from machimoa_review.admin_review_events c) history,
 (select md5(string_agg(to_jsonb(c)::text,'' order by curation_id)) from machimoa_review.home_card_colors c) analysis`);
async function published(key,image='https://images.example.org/fake.png',state='failed'){
 const sid=await source(key,'youthcenter_content');
 await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[sid,JSON.stringify({source_image_url:image,plain_text:'합성 원문'})]);
 await q("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='youthcenter_content'");
 const cid=await candidate(key,'youthcenter_content');
 await q("update machimoa_review.curation_candidates set category='생활',user_category='living',source_url='https://www.youthcenter.go.kr/' where id=$1",[cid]);
 const pid=(await q('select machimoa_review.publish_curation_candidate($1,$2,null,false) id',[cid,other]))[0].id;
 if(image&&['failed','completed'].includes(state)){
  const claim=await rpc('admin_home_color_claim',[pid,cid,other]);
  await rpc('admin_home_color_finish',[pid,claim.token,other,state==='completed'?'blue':'default',state,state==='completed'?'matched':'analysis_failed']);
 }
 return {sid,cid,pid};
}
try{
 await db.exec(await readFile(new URL('../supabase/migrations/20261003000000_source_images.sql',import.meta.url),'utf8'));
 await db.exec(await readFile(new URL('../supabase/migrations/20261023123507_home_card_colors.sql',import.meta.url),'utf8'));
 const migration=await readFile(new URL('../supabase/migrations/'+file,import.meta.url),'utf8');
 const originals=await fingerprint();
 const funcs=await q("select p.oid,pg_get_functiondef(p.oid) definition,p.proacl::text acl from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','machimoa_review') and p.proname<>'public_home_card_colors' order by p.oid");
 await db.exec(migration);eq(await fingerprint(),originals);
 eq(await q('select p.oid,pg_get_functiondef(p.oid) definition,p.proacl::text acl from pg_proc p where p.oid=any($1::oid[]) order by p.oid',[funcs.map(x=>x.oid)]),funcs);
 const a=await published('manual-failed');let d=await detail(a.cid);
 eq(d.analysisState,'failed');eq(d.tone,'default');eq(d.manual,false);eq(d.canEdit,true);
 ok(!/token|image_url|PRIVATE|worker/.test(JSON.stringify(d)));
 const unchanged=await fingerprint(),request=randomUUID();
 const first=await save(a.cid,d,'green',request);
 eq(first.tone,'green');eq(first.manual,true);eq(first.choiceVersion,1);eq(first.analysisState,'failed');ok(first.changedAt);ok(first.version!==d.version);
 eq(await fingerprint(),unchanged);
 eq(await rpc('public_home_card_colors',[[a.pid]]),[{id:a.pid,tone:'green',manual:true,ready:true}]);
 eq(await save(a.cid,d,'green',request),first);eq((await q('select count(*)::int n from machimoa_review.home_card_color_choices'))[0].n,1);
 await reject(()=>save(a.cid,d,'red'));await reject(()=>save(a.cid,d,'red',request));await reject(()=>save(a.cid,d,'green',request,other));
 eq(await save(a.cid,first,'green'),first);eq((await q('select count(*)::int n from machimoa_review.home_card_color_choices'))[0].n,1);
 const second=await save(a.cid,first,'red');eq(second.choiceVersion,2);await reject(()=>save(a.cid,d,'green',request));
 const history=await q('select version,tone,previous_tone,actor from machimoa_review.home_card_color_choices where curation_id=$1 order by version',[a.pid]);
 eq(history,[{version:1,tone:'green',previous_tone:'default',actor},{version:2,tone:'red',previous_tone:'green',actor}]);
 const readBefore=await q('select to_jsonb(h) value from machimoa_review.home_card_color_choices h order by version');await detail(a.cid);await rpc('public_home_card_colors',[[a.pid]]);eq(await q('select to_jsonb(h) value from machimoa_review.home_card_color_choices h order by version'),readBefore);
 for(const [label,image,state]of [['completed','https://images.example.org/fake.png','completed'],['no-image',null,'no_image'],['missing','https://images.example.org/fake.png','missing']]){
  const x=await published('manual-'+label,image,state);
  if(state==='missing')await q('delete from machimoa_review.home_card_colors where curation_id=$1',[x.pid]);
  const before=await fingerprint();let current=await detail(x.cid);eq(current.analysisState,state);
  for(const tone of ['orange','yellow','green','blue','purple','red','default']){
   current=await save(x.cid,current,tone);eq(current.tone,tone);eq(current.analysisState,state);
   eq((await rpc('public_home_card_colors',[[x.pid]]))[0],{id:x.pid,tone,manual:true,ready:true});
  }
  eq(await fingerprint(),before);
 }
 const active=await published('manual-active','https://images.example.org/fake.png','pending');
 const activeClaim=await rpc('admin_home_color_claim',[active.pid,active.cid,other]);d=await detail(active.cid);eq(d.canEdit,false);await reject(()=>save(active.cid,d,'orange'));
 await q("update machimoa_review.home_card_colors set expires_at=clock_timestamp()-interval '1 second' where curation_id=$1",[active.pid]);
 d=await detail(active.cid);eq(d.canEdit,true);eq(d.analysisState,'processing');await save(active.cid,d,'purple');
 await rpc('admin_home_color_finish',[active.pid,activeClaim.token,other,'blue','completed','matched']);
 eq((await detail(active.cid)).analysisState,'failed');eq((await detail(active.cid)).tone,'purple');
 const changed=await detail(a.cid);await q("update machimoa_review.curation_candidates set summary_ko='새 합성 값' where id=$1",[a.cid]);await reject(()=>save(a.cid,changed,'orange'));
 d=await detail(a.cid);await q("update public.curations set content='새 합성 공개 본문' where id=$1",[a.pid]);await reject(()=>save(a.cid,d,'orange'));
 for(const value of ['unapproved','#123456','__proto__',null])await reject(async()=>save(a.cid,await detail(a.cid),value));
 await reject(async()=>save(a.cid,await detail(a.cid),'orange',randomUUID(),null));
 const beforeHide=await detail(a.cid);await q('update public.curations set is_published=false where id=$1',[a.pid]);await reject(()=>detail(a.cid));await reject(()=>save(a.cid,beforeHide,'orange'));eq(await rpc('public_home_card_colors',[[a.pid]]),[]);
 await reject(()=>rpc('public_home_card_colors',[Array(7).fill(active.pid)]));
 for(const role of ['anon','authenticated','service_role']){
  for(const permission of ['select','insert','update','delete'])eq((await q('select has_table_privilege($1,\'machimoa_review.home_card_color_choices\',$2) ok',[role,permission]))[0].ok,false);
  for(const fn of ['public.admin_review_home_color(uuid)','public.admin_review_set_home_color(uuid,text,text,text,uuid,uuid)'])eq((await q('select has_function_privilege($1,$2,\'execute\') ok',[role,fn]))[0].ok,role==='service_role');
 }
 const metadata=await q("select p.prosecdef,p.proconfig,p.proowner='postgres'::regrole owner from pg_proc p where p.oid in ('public.admin_review_home_color(uuid)'::regprocedure,'public.admin_review_set_home_color(uuid,text,text,text,uuid,uuid)'::regprocedure)");for(const fn of metadata){eq(fn.prosecdef,true);eq(fn.owner,true);ok(fn.proconfig.some(x=>x.startsWith('search_path=')));}
 // Two actual concurrent connections with the same snapshot: exactly one wins.
 if(process.env.MACHIMOA_HOME_COLOR_CONTAINER){
  const concurrentItem=await published('manual-concurrent');d=await detail(concurrentItem.cid);const before=await fingerprint();
  const execute=tone=>new Promise(resolve=>{const sql=`set role service_role;select public.admin_review_set_home_color('${concurrentItem.cid}','${d.revision}','${d.version}','${tone}','${randomUUID()}','${actor}');`;
   const child=execFile('docker',['--context','desktop-linux','exec','-i',process.env.MACHIMOA_HOME_COLOR_CONTAINER,'psql','-XqAt','-U','postgres','-v','ON_ERROR_STOP=1'],{timeout:20000},(e,out)=>resolve({ok:!e,out:e?null:JSON.parse(out.trim())}));child.stdin.end(sql);
  });
  const results=await Promise.all([execute('orange'),execute('yellow')]);eq(results.filter(x=>x.ok).length,1);eq((await detail(concurrentItem.cid)).choiceVersion,1);eq(await fingerprint(),before);
 }
 console.log(JSON.stringify({passed:checks,operational_db:0,real_images:0,ai:0,engine:'isolated PostgreSQL'}));
}finally{await db.close();}
