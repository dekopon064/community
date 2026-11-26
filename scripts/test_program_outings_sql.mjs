// In-memory Postgres. The classification tables use their original definitions.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { reviewDatabase } from './review_queue_test_fixture.mjs';

const {db,query,rpc,source,candidate,job,revision}=await reviewDatabase();
const actor='00000000-0000-4000-8000-000000000001';
const migration=n=>readFile(new URL('../supabase/migrations/'+n,import.meta.url),'utf8');
const ep=(value,precision='day')=>({value,precision});
const start=ep('2026-11-28T11:00:00+09:00','minute'),end=ep('2026-11-28T13:00:00+09:00','minute');
const projection=async(source,facts)=>(await query('select machimoa_review.program_session($1,$2) v',[source,JSON.stringify(facts)]))[0].v;
const viewing={subject:'exhibition',reservationNotRequired:true,from:'2026-11-24',through:'2026-12-06',weekdays:[0,2,3,4,5,6],exceptions:['2026-11-27']};
try {
 const filterMigration=await migration('20261007090144_content_filter_contract.sql');
 for(const name of ['day','endpoint']){
   const begin=filterMigration.indexOf('create function machimoa_review.content_filter_'+name+'(');
   await db.exec(filterMigration.slice(begin,filterMigration.indexOf('end $$;',begin)+8));
 }
 const classification=await migration('20261010013000_review_reclassification.sql');
 for(const table of ['claims','candidates']){
   const i=classification.indexOf('create table machimoa_review.review_classification_'+table+'(');
   await db.exec(classification.slice(i,classification.indexOf(';',i)+1));
 }
 await db.exec(await migration('20261126104626_program_outings.sql'));
 const booked={start,end,officialBooking:true};
 const seoul={periods:{SVCOPNBGNDT:{...start,status:'ok'},SVCOPNENDDT:{...end,status:'ok'}},source_status:'open',application_methods:['internet'],official_url:'https://example.invalid/apply'};
 assert.deepEqual(await projection('seoul_reservation',seoul),booked);
 const my={periods:{operation:[{status:'ok',endpoints:[start,end]}]},application_links:['https://example.invalid/application'],application_methods:['온라인 신청']};
 assert.deepEqual(await projection('myseoul_program',my),booked);
 assert.equal(await projection('myseoul_program',{...my,application_methods:['온라인 예약 또는 현장 접수 가능']}),null);
 assert.deepEqual(await projection('myseoul_program',{...my,application_links:[],application_methods:['전화 신청 02-000-0000']}),booked);
 assert.equal(await projection('myseoul_program',{...my,periods:{application:my.periods.operation}}),null);
 assert.equal(await projection('seoul_reservation',{...seoul,source_status:'reservation_closed'}),null);
 assert.equal(await projection('myseoul_program',{...my,conditions:['해당 회차 매진']}),null);
 assert.deepEqual(await projection('myseoul_program',{...my,conditions:['신청 마감 11월 27일 오후 5시']}),booked);
 assert.equal(await projection('seoul_reservation',{...seoul,application_methods:[],fee_kind:'free'}),null);
 for (const [src,base] of [['seoul_reservation',seoul],['myseoul_program',my]]) {
   const free={...base,application_methods:['예약 없이 현장 참여']};
   assert.deepEqual(await projection(src,free),{start,end,officialBooking:false});
   for(const methods of [[],['무료'],['현장 접수'],['취소석에 한해 현장 접수']]){
     assert.equal(await projection(src,{...base,application_methods:methods}),null);
   }
   const onsite={...base,application_methods:['onsite']};
   assert.deepEqual(await projection(src,{...onsite,description:'해당 회차는 사전예약 없이 현장 참여 가능합니다.'}),{start,end,officialBooking:false});
   for(const description of ['해당 회차는 사전예약 없이 현장 참여 가능하지 않습니다.','전시는 예약 없이 관람 가능합니다.']){
     assert.equal(await projection(src,{...onsite,description}),null);
   }
   for(const condition of ['취소석이 있을 때만 현장 접수','현장 접수는 잔여석에 한해 가능','입장 자체는 사전예약 필수']){
     assert.equal(await projection(src,{...free,conditions:[condition]}),null);
   }
 }
 assert.equal(await projection('seoul_reservation',{...seoul,periods:{...seoul.periods,SVCOPNENDDT:{...end,value:'2026-12-06',status:'ok'}}}),null);
 const midnight={value:'2026-11-28T00:00:00+09:00',precision:'second',status:'ok'};
 const dateOnly={...seoul,periods:{SVCOPNBGNDT:midnight,SVCOPNENDDT:midnight}};
 assert.equal(await projection('seoul_reservation',dateOnly),null);
 assert.deepEqual(await projection('seoul_reservation',{...dateOnly,description:'답사일시: 11. 28.(토) 11~13시'}),booked);
 const spanning={...seoul,periods:{SVCOPNBGNDT:{...ep('2026-11-24'),status:'ok'},SVCOPNENDDT:{...ep('2026-12-06'),status:'ok'}}};
 assert.deepEqual(await projection('seoul_reservation',{...spanning,description:'운영일시 : `26. 11. 28(토), 11:00-13:00(120분 내외)'}),booked);
 assert.equal(await projection('seoul_reservation',{...spanning,description:'운영일시: 11. 28.(금) 11~13시'}),null);
 assert.equal(await projection('seoul_reservation',{...seoul,description:'1회차, 2회차가 있는 교육입니다.'}),null);
 assert.deepEqual(await projection('myseoul_program',{...my,conditions:['매진 시 접수가 종료될 수 있습니다.']}),booked);
 const multi=(await query("select machimoa_review.program_sessions('seoul_reservation',$1) v",[JSON.stringify({...spanning,description:'해설일시: 12. 3.(목) 11~13시\n해설일시: 12. 5.(토) 11~13시'})]))[0].v;
 const malformed=(await query("select machimoa_review.program_sessions('seoul_reservation',$1) v",[JSON.stringify({...spanning,conditions:{legacy:'unknown'},description:'해설일시: 12. 3.(목) 11~13시\n해설일시: 12. 5.(토) 11~13시'})]))[0].v;
 assert.equal(malformed,null);
 const partial=(await query("select machimoa_review.program_sessions('seoul_reservation',$1) v",[JSON.stringify({...spanning,description:'해설일시: 12. 3.(목) 11~13시 (매진)\n해설일시: 12. 5.(토) 11~13시'})]))[0].v;
 assert.deepEqual(partial.map(s=>s.start.value.slice(0,10)),['2026-12-05']);
 assert.deepEqual(multi.map(s=>s.start.value.slice(0,10)),['2026-12-03','2026-12-05']);
 assert.equal(await projection('myseoul_program',{...my,periods:{operation:[{status:'ok',endpoints:[{value:'private memo',precision:'day'}]}]}}),null);
 const custom={...viewing,subject:'other',labelKo:'공개 리허설 관람',labelJa:'公開リハーサルの見学'};
 assert.equal((await query('select machimoa_review.valid_general_viewing($1) v',[JSON.stringify(custom)]))[0].v,true);
 for(const value of [null,viewing,{...viewing,weekdays:[]},{...viewing,reservationNotRequired:false},{...viewing,from:'2026-02-31'},{...viewing,secret:'operator memo'}]){
   assert.equal((await query('select machimoa_review.valid_general_viewing($1) v',[value&&JSON.stringify(value)]))[0].v,value===null||value===viewing);
 }
 await query("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='youthcenter_content'");
 for(const withViewing of [true,false]){
   const key='local-outing-'+withViewing;
   await source(key,'youthcenter_content'); const id=await candidate(key,'youthcenter_content');
   await query("update machimoa_review.curation_candidates set category='프로그램',user_category='program',application_deadline_kind='none',source_url='https://example.invalid' where id=$1",[id]);
   if(withViewing){
     const item=await rpc('admin_review_detail',['candidates',id]);
     const args=[id,item.revision,item.version,item.content,actor,null,viewing];
     const saved=await rpc('admin_review_save_candidate_viewing',args);
     assert.deepEqual(saved.viewing,viewing);assert.notEqual(saved.version,item.version);
     await assert.rejects(()=>rpc('admin_review_save_candidate_viewing',args));
   }
   const pid=(await query('select machimoa_review.publish_curation_candidate($1,$2,null,false) id',[id,actor]))[0].id;
   const published=(await query('select program_outing from public.curations where id=$1 and is_published',[pid]))[0];
   assert.deepEqual(published.program_outing,withViewing?{viewing}:null);
 }
 // Attach the same source-version and claim snapshot used by the native worker.
 const sid=await source('native-session','seoul_reservation');
 const cid=await candidate('native-session','seoul_reservation');
 await query("update machimoa_review.curation_candidates set user_category='program',category='프로그램',application_deadline_kind='none' where id=$1",[cid]);
 const jid=await job(sid,'completed');
 const native=JSON.stringify({...seoul,description:'private source text'});
 await query("insert into machimoa_review.source_item_program_facts(source_item_id,revision_hash,source_snapshot,observed_facts,facts) values($1,$2,'{}',$3,$3)",[sid,revision,native]);
 await query("insert into machimoa_review.program_candidate_inputs(candidate_id,source_item_id,revision_hash,facts_version,job_id,claimed_at,lease_until,worker_id,schema_version,profile,api_category,input_facts,output_hash) values($1,$2,$3,1,$4,now(),now()+interval '1 hour','local','program-scope-v1-local','program_capital_v1_local','문화체험',$5,'local')",[cid,sid,revision,jid,native]);
 const projected=()=>query('select machimoa_review.candidate_program_outing(c) v from machimoa_review.curation_candidates c where id=$1',[cid]);
 assert.deepEqual((await projected())[0].v,{sessions:[booked]});
 await query("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='seoul_reservation'");
 await query("update machimoa_review.curation_candidates set source_url='https://example.invalid/booking' where id=$1",[cid]);
 const publishedId=(await query('select machimoa_review.publish_curation_candidate($1,$2,null,false) id',[cid,actor]))[0].id;
 assert.deepEqual((await query('select program_outing from public.curations where id=$1 and is_published',[publishedId]))[0].program_outing,{sessions:[booked]});
 await query('update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id=$1',[sid]);
 assert.equal((await projected())[0].v,null);
 for (const [description,blocked] of [['입장 자체는 사전예약 필수',true],['예약자만 입장 가능합니다.',true],['입장은 예약이 필요합니다.',true],['예약 없이는 입장할 수 없습니다.',true],['일반 관람은 예약이 필요하지 않습니다. 해설만 사전예약 필수',false],['공예 수업은 사전예약 필수',false],['해설은 사전예약 필수',false],['체험은 취소석이 있을 때만 현장 접수',false]]){
   const facts=JSON.stringify({...seoul,description});
   await query('update machimoa_review.program_candidate_inputs set input_facts=$1, facts_version=2 where candidate_id=$2',[facts,cid]);
   await query('update machimoa_review.curation_candidates set general_viewing=$1 where id=$2',[JSON.stringify(viewing),cid]);
   const result=(await projected())[0].v;
   assert.deepEqual(result?.viewing??null,blocked?null:viewing,description);
 }
 console.log('PASS source-specific snapshots, time and access guards, editor save/version conflict, optional publication and private-to-public projection');
} finally {await db.close();}
