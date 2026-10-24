// Canonical synthetic review fixture, isolated SQL only. No real endpoints/keys.
import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';import {syncBuiltinESMExports} from 'node:module';
import https from 'node:https';import http from 'node:http';import net from 'node:net';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
import {planSql,reserveSql,finishSql,analyzerHash,runReanalysis} from './one_off_home_color_reanalysis.mjs';
globalThis.fetch=https.request=https.get=http.request=http.get=net.Socket.prototype.connect=()=>{throw Error('network_forbidden');};syncBuiltinESMExports();
const f=await reviewDatabase(),{db,query:q,rpc,source,candidate}=f;
const actor='00000000-0000-4000-8000-000000000001',other='00000000-0000-4000-8000-000000000002',codeHash=await analyzerHash();
const table='machimoa_review.home_color_area40_once';
let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;},ok=x=>{assert.ok(x);checks++;},reject=async fn=>{await assert.rejects(fn);checks++;};
const exec=async sql=>{const result=await db.exec(sql);return [...result].reverse().find(x=>x.rows?.[0]?.result)?.rows[0].result;};
const plan=async pid=>(await q(planSql(100))).find(x=>x.id===pid);
const detail=cid=>rpc('admin_review_home_color',[cid]);
const save=async(cid,tone)=>{const d=await detail(cid);return rpc('admin_review_set_home_color',[cid,d.revision,d.version,tone,randomUUID(),other]);};
const reserve=(p,req=randomUUID())=>exec(reserveSql(p,actor,req,codeHash)).then(result=>({req,result}));
const finish=(p,req,tone='orange',state='completed')=>exec(finishSql(p,actor,req,{state,tone,reason:state==='failed'?'analysis_failed':tone==='default'?'ambiguous':'matched'}));
const snapshot=()=>q(`select
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from public.curations c) content,
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from machimoa_review.curation_candidates c) candidate,
 (select md5(string_agg(to_jsonb(c)::text,'' order by id)) from machimoa_review.admin_review_events c) history,
 (select md5(string_agg(to_jsonb(c)::text,'' order by curation_id)) from machimoa_review.home_card_colors c) analysis,
 (select md5(string_agg(to_jsonb(c)::text,'' order by curation_id,version)) from machimoa_review.home_card_color_choices c) choices`);
async function published(key,state='completed',image='https://images.example.org/synthetic.png'){
 const sid=await source(key,'youthcenter_content');
 await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[sid,JSON.stringify({source_image_url:image,plain_text:'합성 원문'})]);
 await q("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='youthcenter_content'");
 const cid=await candidate(key,'youthcenter_content');await q("update machimoa_review.curation_candidates set category='생활',user_category='living',source_url='https://www.youthcenter.go.kr/' where id=$1",[cid]);
 const pid=(await q('select machimoa_review.publish_curation_candidate($1,$2,null,false) id',[cid,other]))[0].id;
 if(['failed','completed'].includes(state)){const claim=await rpc('admin_home_color_claim',[pid,cid,other]);await rpc('admin_home_color_finish',[pid,claim.token,other,state==='completed'?'blue':'default',state,state==='completed'?'matched':'analysis_failed']);}
 return{sid,cid,pid};
}
try{
 for(const name of ['20261003000000_source_images.sql','20261023123507_home_card_colors.sql','20261023234936_home_color_operator_choice.sql'])await db.exec(await readFile(new URL('../supabase/migrations/'+name,import.meta.url),'utf8'));
 const migration=await readFile(new URL('../supabase/migrations/20261024054210_home_color_area40_oneoff.sql',import.meta.url),'utf8');
 const a=await published('oneoff-success'),beforeMigration=await snapshot();
 const meta=await q("select oid,proowner,proacl::text,proconfig,prosecdef from pg_proc where oid in ('machimoa_review.home_color_detail(uuid)'::regprocedure,'public.public_home_card_colors(uuid[])'::regprocedure)");
 // Deliberately change a prerequisite, confirm fail-closed and atomic rollback.
 const original=(await q("select pg_get_functiondef('machimoa_review.home_color_detail(uuid)'::regprocedure) definition"))[0].definition;
 await db.exec(original.replace("'analysisState'","'analysisState' /* synthetic drift */"));
 await reject(()=>db.exec(migration));eq((await q('select to_regclass($1) value',[table]))[0].value,null);
 await db.exec(original);await db.exec(migration);eq(await snapshot(),beforeMigration);
 eq(await q('select oid,proowner,proacl::text,proconfig,prosecdef from pg_proc where oid=any($1::oid[])',[meta.map(x=>x.oid)]),meta);
 const priorDetail=await detail(a.cid),baseline=await snapshot(),p=await plan(a.pid);eq(p.eligibility,'eligible');
 const r=await reserve(p);eq(r.result,{status:'reserved'});
 eq((await detail(a.cid)).tone,'blue');eq((await detail(a.cid)).canEdit,true);ok((await detail(a.cid)).version!==priorDetail.version);
 await reject(()=>rpc('admin_review_set_home_color',[a.cid,priorDetail.revision,priorDetail.version,'green',randomUUID(),other]));
 eq(await finish(p,r.req),{status:'completed',tone:'orange'});eq(await snapshot(),baseline);
 eq((await detail(a.cid)).analysisTone,'orange');eq((await detail(a.cid)).tone,'orange');eq((await detail(a.cid)).manual,false);
 eq(await rpc('public_home_card_colors',[[a.pid]]),[{id:a.pid,tone:'orange',manual:false,ready:true}]);
 eq((await plan(a.pid)).eligibility,'already_attempted');eq((await reserve(p,r.req)).result.status,'already_attempted');
 eq((await finish(p,r.req,'red')).status,'unconfirmed');eq((await detail(a.cid)).tone,'orange');
 eq((await q(`select count(*)::int n from ${table} where curation_id=$1`,[a.pid]))[0].n,1);
 // A later intentional manual choice always wins; it records the new previous tone.
 await save(a.cid,'green');eq((await detail(a.cid)).tone,'green');eq((await q('select previous_tone from machimoa_review.home_card_color_choices where curation_id=$1',[a.pid]))[0].previous_tone,'orange');eq((await plan(a.pid)).eligibility,'manual');
 const manual=await published('oneoff-manual');await save(manual.cid,'red');const mp=await plan(manual.pid);eq(mp.eligibility,'manual');eq((await reserve(mp)).result.status,'changed');
 const inFlight=await published('oneoff-manual-during');const ip=await plan(inFlight.pid),ir=await reserve(ip);await save(inFlight.cid,'purple');eq((await finish(ip,ir.req)).status,'skipped_manual');eq((await detail(inFlight.cid)).tone,'purple');
 const failed=await published('oneoff-download-fail');const fp=await plan(failed.pid),fr=await reserve(fp),oldFail=await snapshot();
 eq(await finish(fp,fr.req,'default','failed'),{status:'failed',tone:'default'});eq((await detail(failed.cid)).tone,'blue');eq(await snapshot(),oldFail);
 const ambiguous=await published('oneoff-ambiguous');const ap=await plan(ambiguous.pid),ar=await reserve(ap);eq((await finish(ap,ar.req,'default')).status,'completed');eq((await detail(ambiguous.cid)).analysisReason,'ambiguous');eq((await detail(ambiguous.cid)).tone,'default');
 for(const [label,statement]of [
  ['body',"update public.curations set content='changed synthetic content' where id=$1"],
  ['image',"update public.curations set source_image_url='https://images.example.org/changed.png' where id=$1"],
  ['unpublish','update public.curations set is_published=false where id=$1'],
  ['revision',"update machimoa_review.curation_candidates set source_revision_hash=repeat('b',64) where published_curation_id=$1"],
  ['original-analysis',"update machimoa_review.home_card_colors set reason='ambiguous' where curation_id=$1"]]){
  const x=await published('oneoff-changed-'+label),xp=await plan(x.pid),xr=await reserve(xp);await q(statement,[x.pid]);eq((await finish(xp,xr.req)).status,'skipped_changed');
 }
 const stale=await published('oneoff-stale-before');const sp=await plan(stale.pid);await q("update public.curations set summary='new synthetic summary' where id=$1",[stale.pid]);eq((await reserve(sp)).result.status,'changed');
 const expired=await published('oneoff-expired'),ep=await plan(expired.pid),er=await reserve(ep);await q(`update ${table} set started_at=clock_timestamp()-interval '2 minutes',expires_at=clock_timestamp()-interval '1 minute' where curation_id=$1`,[expired.pid]);eq((await finish(ep,er.req)).status,'expired');eq((await detail(expired.cid)).tone,'blue');
 for(const [label,state,image]of [['active','pending','https://images.example.org/synthetic.png'],['noimage','no_image',null]]){const x=await published('oneoff-'+label,state,image);const xp=await plan(x.pid);eq(xp.eligibility,'ineligible');}
 const claimed=await published('oneoff-processing','pending');await rpc('admin_home_color_claim',[claimed.pid,claimed.cid,other]);const cp=await plan(claimed.pid);eq(cp.eligibility,'ineligible');eq((await reserve({...cp,image_url:cp.image_url})).result.status,'changed');
 const wrong=await published('oneoff-wrong-fence'),wp=await plan(wrong.pid),wr=await reserve(wp);eq((await finish(wp,randomUUID())).status,'unconfirmed');eq((await exec(finishSql(wp,other,wr.req,{state:'completed',tone:'orange',reason:'matched'}))).status,'unconfirmed');
 eq((await finish({...wp,image_url:'https://images.example.org/not-the-poster.png'},wr.req)).status,'unconfirmed');
 eq((await finish({...wp,analysis_hash:'f'.repeat(64)},wr.req)).status,'unconfirmed');eq((await finish(wp,wr.req)).status,'completed');
 // Two real DB connections contend on the same candidate/public locks.
 const race=await published('oneoff-reserve-race'),rp=await plan(race.pid);
 const races=await Promise.all([reserve(rp),reserve(rp)]);eq(races.map(x=>x.result.status).sort(),['already_attempted','reserved']);
 const winner=races.find(x=>x.result.status==='reserved');eq((await finish(rp,winner.req)).status,'completed');
 // Manual save wins while finish is waiting: second statement must see it.
 if(typeof db.raw==='function'){
  const x=await published('oneoff-manual-lock-race'),xp=await plan(x.pid),xr=await reserve(xp),d=await detail(x.cid);
  const blocker=db.raw(`begin;select 1 from machimoa_review.curation_candidates where id='${x.cid}' for update;select pg_sleep(1);select public.admin_review_set_home_color('${x.cid}','${d.revision}','${d.version}','red','${randomUUID()}','${other}');commit;`);
  // Wait for the actual lock, not an arbitrary timer, using separate connections.
  let observed=false;for(let i=0;i<40;i++){const locks=await q("select count(*)::int n from pg_locks where relation='machimoa_review.curation_candidates'::regclass and mode='RowShareLock' and granted");if(locks[0].n>0){observed=true;break;}}ok(observed);
  const ending=finish(xp,xr.req);await blocker;eq((await ending).status,'skipped_manual');eq((await detail(x.cid)).tone,'red');
 }
 const readBefore=await snapshot();await detail(a.cid);await rpc('public_home_card_colors',[[a.pid]]);eq(await snapshot(),readBefore);
 // The complete injected runner reaches reserve -> fake image -> terminal SQL
 // -> unchanged existing content/history -> public/admin projection.
 const connected=await published('oneoff-connected'),connectedPlan=await plan(connected.pid),connectedBefore=await snapshot();let downloads=0,analyses=0;
 eq((await reserve({...connectedPlan,image_url:'https://images.example.org/wrong.png'})).result.status,'changed');
 const output=await runReanalysis({rows:[connectedPlan],actor,execute:true,sql:exec,codeHash,confirmedCodeHash:codeHash,
 loadImage:async url=>{eq(url,connectedPlan.image_url);downloads++;return new Uint8Array([1,2,3]);},
 analyze:async bytes=>{eq([...bytes],[1,2,3]);analyses++;return{tone:'yellow',reason:'matched'};}});
 eq(output,[{id:connected.pid,status:'completed',tone:'yellow'}]);eq(downloads,1);eq(analyses,1);eq(await snapshot(),connectedBefore);eq((await detail(connected.cid)).tone,'yellow');
 for(const role of ['anon','authenticated','service_role'])for(const action of ['select','insert','update','delete'])eq((await q('select has_table_privilege($1,$2,$3) ok',[role,table,action]))[0].ok,false);
 eq((await q('select relrowsecurity from pg_class where oid=$1::regclass',[table]))[0].relrowsecurity,true);
 await reject(()=>rpc('public_home_card_colors',[Array(7).fill(a.pid)]));
 // No new public functions, no permissions granted by the one-off migration.
 ok(!/create (?:or replace )?function public\.(?!public_home_card_colors)/i.test(migration));ok(!/\bgrant\b/i.test(migration));
 console.log(JSON.stringify({passed:checks,operational_db:0,real_images:0,ai:0,engine:'isolated PostgreSQL 17; network none',prior_analysis:'unchanged'}));
}finally{await db.close();}
