import assert from 'node:assert/strict';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
const f=await reviewDatabase();let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
try{
 const {db,query,rpc,source,job,candidate}=f;
 const read=(watch=[],offset=0)=>rpc('admin_review_ai_queue',[offset,25,watch]);
 const acl=(await query(`select has_function_privilege('anon','public.admin_review_ai_queue(integer,integer,uuid[])','execute') anon,
 has_function_privilege('authenticated','public.admin_review_ai_queue(integer,integer,uuid[])','execute') auth,
 has_function_privilege('service_role','public.admin_review_ai_queue(integer,integer,uuid[])','execute') service`))[0];
 eq(acl,{anon:false,auth:false,service:true});eq((await read()).items,[]);
 const existing=await query(`select n.nspname,p.proname,pg_get_functiondef(p.oid) definition,p.proacl::text acl from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname in ('machimoa_review','public') and p.proname<>'admin_review_ai_queue' order by p.oid`);eq(existing,f.baseline);
 for(const role of ['anon','authenticated']){
  await db.exec('set role '+role);await assert.rejects(()=>query('select public.admin_review_ai_queue()'),e=>e.code==='42501');checks++;await db.exec('reset role');
 }
 await assert.rejects(()=>read([],100001),e=>e.code==='PT422');checks++;
 const s=await source('queue');const j=await job(s);
 const retry=await source('retry','youthcenter_content'),r=await job(retry,'queued',{retryCount:1,errorCode:'ai_network',nextRetryAt:'2099-01-01T00:00:00Z'});
 const failed=await job(await source('failed'),'failed',{retryCount:3,errorCode:'RAW_TOKEN_DO_NOT_ECHO'});
 const active=await job(await source('claim'),'claimed',{leaseUntil:'2099-01-01T00:00:00Z'});
 const expired=await job(await source('expired'),'claimed',{leaseUntil:'2000-01-01T00:00:00Z'});
 const snapshot=await read();eq(snapshot.items.length,5);eq(snapshot.items.find(x=>x.jobId===r).errorCode,'ai_network');eq(snapshot.items.find(x=>x.jobId===failed).errorCode,null);
 eq(snapshot.items.find(x=>x.jobId===active).leaseState,'active');eq(snapshot.items.find(x=>x.jobId===expired).leaseState,'expired');
 eq(JSON.stringify(snapshot).includes('LOCAL_DO_NOT_ECHO'),false);eq(JSON.stringify(snapshot).includes('RAW_TOKEN'),false);
 const before=await query('select * from machimoa_review.processing_jobs order by id');
 await read([j,r]);eq(await query('select * from machimoa_review.processing_jobs order by id'),before);
 await query("update machimoa_review.processing_jobs set status='completed',completed_at=clock_timestamp(),error_code='ai_network' where id=$1",[j]);
 let watched=(await read([j])).observed[0];eq(watched.resultState,'missing');eq((await read()).items.some(x=>x.jobId===j),false);
 const c=await candidate('queue');watched=(await read([j])).observed[0];eq(watched.resultState,'ready');eq(watched.status,'completed');
 await query("update machimoa_review.curation_candidates set review_status='rejected',reviewed_at=clock_timestamp(),reviewed_by='local' where id=$1",[c]);eq((await read([j])).observed[0].resultState,'processed');
 await query("update machimoa_review.curation_candidates set review_status='pending',reviewed_at=null,reviewed_by=null where id=$1",[c]);
 await query("insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note) values($1,$2,'save_facts',$3,'합성 변경')",[s,f.revision,'00000000-0000-4000-8000-000000000001']);
 eq((await read([j])).observed[0].resultState,'input_changed');
 await query("update machimoa_review.source_items set revision_hash=repeat('b',64) where id=$1",[s]);eq((await read([j])).observed[0].resultState,'source_changed');
 eq((await read(['00000000-0000-4000-8000-000000000099'])).observed[0].status,'missing');
 const seoul=await source('seoul-queue','seoul_reservation'),sj=await job(seoul);
 eq((await read()).items.find(x=>x.jobId===sj).sourceName,'seoul_reservation');
 await query("update machimoa_review.processing_jobs set status='completed',completed_at=clock_timestamp() where id=$1",[sj]);
 const sc=await candidate('seoul-queue','seoul_reservation');
 eq((await read([sj])).observed[0].resultState,'input_changed');
 await query(`insert into machimoa_review.source_item_program_facts(source_item_id,revision_hash,source_snapshot,observed_facts,facts) values($1,$2,'{}','{}','{}')`,[seoul,f.revision]);
 await query(`insert into machimoa_review.program_candidate_inputs(candidate_id,source_item_id,revision_hash,facts_version,job_id,claimed_at,lease_until,worker_id,schema_version,profile,api_category,input_facts,output_hash)
 values($1,$2,$3,1,$4,now(),now()+interval '1 minute','synthetic','program-scope-v1-local','program_capital_v1_local','문화체험','{}',repeat('c',64))`,[sc,seoul,f.revision,sj]);
 eq((await read([sj])).observed[0].resultState,'ready');
 await query('update machimoa_review.source_item_program_facts set facts_version=2 where source_item_id=$1',[seoul]);
 eq((await read([sj])).observed[0].resultState,'input_changed');
 const white=await source('whitespace'),wj=await job(white,'completed'),wc=await candidate('whitespace');
 for(const value of ['\t'.repeat(20),'\n\r','\u00a0\u2000\u3000','\u2028\u2029']){
  await query('update machimoa_review.curation_candidates set summary_ja=$2 where id=$1',[wc,value]);
  eq((await read([wj])).observed[0].resultState,'unavailable');
 }
 await query("update machimoa_review.curation_candidates set summary_ja='日本語' where id=$1",[wc]);
 eq((await read([wj])).observed[0].resultState,'ready');
 await query("update machimoa_review.processing_jobs set status='cancelled' where id=$1",[r]);
 eq((await read([r])).observed[0].status,'cancelled');
 for(let i=0;i<26;i++)await job(await source('page-'+i));
 const page=await read();eq(page.items.length,25);eq(page.hasMore,true);eq((await read([],25)).hasMore,false);
 console.log('AI read RPC fresh memory PostgreSQL checks:',checks,'Existing function definitions/ACL unchanged. No operational DB/AI.');
}finally{await f.db.close();}
