// Fresh in-memory PostgreSQL with synthetic source/candidate/public rows only.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {registerHooks} from 'node:module';
import {reviewDatabase} from './review_queue_test_fixture.mjs';
registerHooks({resolve(specifier, context, next) {try{return next(specifier,context);}catch(error){if(specifier.startsWith('.')&&!/\.[a-z]+$/i.test(specifier))return next(specifier+'.ts',context);throw error;}}});
const {sourceImageUrl}=await import('../app/lib/sourceImages.ts');
const f=await reviewDatabase();let checks=0;
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
try {
 const {db,query:q,source,candidate,revision}=f;
 for(const name of ['20261002000100_admin_review_trash.sql','20261002000200_admin_review_trash_publication.sql'])await db.exec(await readFile(new URL('../supabase/migrations/'+name,import.meta.url),'utf8'));
 const baseline=await q(`select p.oid,pg_get_functiondef(p.oid) body,p.proacl::text acl from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('machimoa_review','public') order by p.oid`);
 await db.exec(await readFile(new URL('../supabase/migrations/20261003000000_source_images.sql',import.meta.url),'utf8'));
 eq(await q(`select p.oid,pg_get_functiondef(p.oid) body,p.proacl::text acl from pg_proc p where p.oid=any($1::oid[]) order by p.oid`,[baseline.map(x=>x.oid)]),baseline);
 eq((await q('select count(*)::int n from public.curations where source_image_url is not null'))[0].n,0);
 const values=['https://images.example.org/a.png','https://images.example.org/get?id=2&size=300','HTTPS://IMAGES.EXAMPLE.ORG/a.png',null,'http://images.example.org/a.png','https://127.0.0.1/a','https://user:secret@images.example.org/a','https://images.local/a','data:image/png;base64,SECRET','https://images.example.org/a.svg','https://images.example.org/%0a','https://images.example.org/a#secret','https://images.example.org/a\n','https://images.example.org/'+ 'x'.repeat(2048)];
 for(const value of values)eq((await q('select machimoa_review.safe_source_image_url($1) url',[value]))[0].url,sourceImageUrl(value));
 const sid=await source('image-content','youthcenter_content');
 await q(`update machimoa_review.source_items set normalized_payload=$2 where id=$1`,[sid,JSON.stringify({source_image_url:'https://images.example.org/poster.png',secret:'PRIVATE_DO_NOT_PROJECT'})]);
 const cid=await candidate('image-content','youthcenter_content');
 const pub=(await q(`insert into public.curations(slug,title,summary,content,source,source_item_id,is_published) values('image-public','공개 제목','요약','본문','youthcenter_content','image-content',true) returning id`))[0].id;
 eq((await q('select source_image_url from public.curations where id=$1',[pub]))[0].source_image_url,null);
 await q(`update machimoa_review.curation_candidates set review_status='published',published_curation_id=$2,published_at=now(),reviewed_at=now(),reviewed_by='synthetic' where id=$1`,[cid,pub]);
 eq((await q('select source_image_url from public.curations where id=$1',[pub]))[0].source_image_url,'https://images.example.org/poster.png');
 // Image removal clears the public URL on the next publication, not ingest alone.
 await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[sid,JSON.stringify({source_image_url:null})]);
 eq((await q('select source_image_url from public.curations where id=$1',[pub]))[0].source_image_url,'https://images.example.org/poster.png');
 await q(`update machimoa_review.curation_candidates set review_status='published' where id=$1`,[cid]);
 eq((await q('select source_image_url from public.curations where id=$1',[pub]))[0].source_image_url,null);
 // A different source/revision cannot project an old image.
 await q('update machimoa_review.source_items set normalized_payload=$2,revision_hash=repeat(\'b\',64) where id=$1',[sid,JSON.stringify({source_image_url:'https://images.example.org/new.png'})]);
 await q(`update machimoa_review.curation_candidates set review_status='published' where id=$1`,[cid]);
 eq((await q('select source_image_url from public.curations where id=$1',[pub]))[0].source_image_url,null);
 const seoul=await source('image-seoul','seoul_reservation'),sc=await candidate('image-seoul','seoul_reservation');
 await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[seoul,JSON.stringify({provider_fields:{IMGURL:'https://images.example.org/seoul.jpg'}})]);
 const sp=(await q(`insert into public.curations(slug,title,summary,content,source,source_item_id,is_published) values('seoul-public','제목','요약','본문','seoul_reservation','image-seoul',true) returning id`))[0].id;
 await q(`update machimoa_review.curation_candidates set review_status='published',published_curation_id=$2,published_at=now(),reviewed_at=now(),reviewed_by='synthetic' where id=$1`,[sc,sp]);
 eq((await q('select source_image_url from public.curations where id=$1',[sp]))[0].source_image_url,'https://images.example.org/seoul.jpg');
 // Transaction rollback cannot leave a partial projection.
 await assert.rejects(()=>db.transaction(async tx=>{await tx.query(`update machimoa_review.curation_candidates set review_status='published' where id=$1`,[cid]);throw Error('synthetic failure');}));checks++;
 const acl=await q(`select p.proname,has_function_privilege('anon',p.oid,'execute') anon,has_function_privilege('authenticated',p.oid,'execute') auth from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_review' and p.proname in ('safe_source_image_url','project_published_source_image')`);
 for(const x of acl){eq(x.anon,false);eq(x.auth,false);}
 for(const role of ['anon','authenticated']){await db.exec('set role '+role);await assert.rejects(()=>q('select * from machimoa_review.source_items'),e=>e.code==='42501');checks++;await db.exec('reset role');}
 await assert.rejects(()=>q(`update public.curations set source_image_url='data:image/png;base64,SECRET' where id=$1`,[pub]),e=>e.code==='23514');checks++;
 eq((await q('select revision_hash from machimoa_review.source_items where id=$1',[seoul]))[0].revision_hash,revision);
 // Run the actual existing publication function, not only a status transition.
 const directSource=await source('actual-publication','youthcenter_content');
 await q('update machimoa_review.source_items set normalized_payload=$2 where id=$1',[directSource,JSON.stringify({source_image_url:'https://images.example.org/actual.png'})]);
 await q("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='youthcenter_content'");
 const directCandidate=await candidate('actual-publication','youthcenter_content');
 await q("update machimoa_review.curation_candidates set category='생활',user_category='living',source_url='https://www.youthcenter.go.kr/' where id=$1",[directCandidate]);
 const actualPublished=(await q("select machimoa_review.publish_curation_candidate($1,'synthetic',null,false) id",[directCandidate]))[0].id;
 eq((await q('select source_image_url from public.curations where id=$1',[actualPublished]))[0].source_image_url,'https://images.example.org/actual.png');
 console.log('Source image migration/projection checks:',checks,'Fresh memory DB; existing function definitions/ACL unchanged; no operational access.');
}finally{await f.db.close();}
