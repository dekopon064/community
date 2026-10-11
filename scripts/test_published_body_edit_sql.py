"""Synthetic-only PostgreSQL, explicit isolated database; no HTTP/provider calls."""
import argparse,json,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

parser=argparse.ArgumentParser();parser.add_argument('--database',required=True)
db=parser.parse_args().database
assert db.startswith('published_body_local_') and db.replace('_','').isalnum()
container='machimoa-saved-count-sql-20261009-56ca9041'
def docker(parts,body=None):
 r=subprocess.run(['docker',*parts],input=body.encode() if body else None,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.decode())
 return r.stdout.decode().strip()
m=json.loads(docker(['inspect',container]))[0]
assert m['State']['Running'] and m['HostConfig']['NetworkMode']=='none' and not m['HostConfig']['PortBindings']
assert m['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
assert all(x['Type']=='volume' and x['Name']==container+'-data' for x in m['Mounts'])
assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
def sql(q):return docker(['exec','-i',container,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],q)
def lit(v):return 'NULL' if v is None else "'"+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)).replace("'","''")+"'"
def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
def query(n,a):return 'begin;set local role service_role;select public.'+n+'('+','.join(map(lit,a))+');commit;'
def rpc(n,a):return json.loads(sql(query(n,a)))
checks=0
def ok(v):
 global checks
 assert v
 checks+=1
def deny(q,reason):
 global checks
 try:sql(q)
 except RuntimeError as e:assert reason in str(e),str(e);checks+=1
 else:raise AssertionError(reason)
root=Path(__file__).resolve().parents[1]
up=(root/'supabase/migrations/20261011085348_admin_published_body_edit.sql').read_text(encoding='utf8')
down=(root/'supabase/rollback/20261011085348_admin_published_body_edit_down.sql').read_text(encoding='utf8')
sql(up)
actor='00000000-0000-4000-8000-000000000001'
signatures=['admin_review_published_list(integer,integer)','admin_review_published_detail(uuid)','admin_review_save_published_body(uuid,text,text,text,jsonb,text,uuid)']
for role in ['anon','authenticated']:
 for signature in signatures:ok(not scalar("has_function_privilege('"+role+"','public."+signature+"','EXECUTE')"))
for signature in signatures:ok(scalar("has_function_privilege('service_role','public."+signature+"','EXECUTE')"))
for role in ['anon','authenticated','service_role']:
 ok(not scalar("has_table_privilege('"+role+"','machimoa_review.published_body_edits','SELECT,INSERT,UPDATE,DELETE')"))
ok(scalar("(select relrowsecurity from pg_class where oid='machimoa_review.published_body_edits'::regclass)"))

# Owner-only fixture setup, never a production save/claim workflow.
key='published-body-synthetic-'+uuid4().hex
sid=json.loads(sql("insert into machimoa_review.source_items(source_id,external_key,revision_hash,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload,has_source_url,body_usable) values('youthcenter_policy',"+lit(key)+",repeat('a',64),now(),now(),'missing','missing','observe_only','{}','{\"plcyNm\":\"합성 게시 글\",\"plain_text\":\"합성 원문\"}',true,true) returning to_jsonb(id);"))
pid=json.loads(sql("insert into public.curations(slug,category,user_category,title,title_ko,title_ja,summary,summary_ko,summary_ja,content,content_ko,content_ja,is_published,source,source_item_id) values("+lit(key)+",'living','living','제목','제목','題名','요약','요약','要約','기존 한국어','기존 한국어','元の日本語',true,'youthcenter',"+lit(key)+") returning to_jsonb(id);"))
cid=json.loads(sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,category,user_category,title,title_ko,title_ja,summary,summary_ko,summary_ja,content,content_ko,content_ja,raw_payload,ai_status,ai_status_ko,ai_status_ja,review_status,published_curation_id,published_at,reviewed_by,reviewed_at) values('youthcenter',"+lit(key)+",repeat('a',64),"+lit(key)+",'living','living','제목','제목','題名','요약','요약','要約','기존 한국어','기존 한국어','元の日本語','{}','success','success','success','published',"+lit(pid)+",now(),"+lit(actor)+",now()) returning to_jsonb(id);"))
sql("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='youthcenter_policy';")
detail=lambda:rpc('admin_review_published_detail',[cid])
d=detail();before_public=scalar('(select to_jsonb(p) from public.curations p where id='+lit(pid)+')')
before_candidate=scalar('(select to_jsonb(c) from machimoa_review.curation_candidates c where id='+lit(cid)+')')
body={'contentKo':'## 주요 내용\n**합성 수강료: 무료**\n\n## 신청 방법\n온라인 신청','contentJa':'## 主な内容\n**合成受講料：無料**\n\n## 申請方法\nオンライン申請'}
def args(current=d,patch=body):return [cid,current['revision'],current['version'],current['publishedBodyVersion'],patch,'중복 안내 정리',actor]
ok(any(x['id']==cid for x in rpc('admin_review_published_list',[0,25])))
deny(query('admin_review_save_published_body',args()[:-1]+[None]),'review_invalid_input')
deny(query('admin_review_save_published_body',args(patch={**body,'titleKo':'제목 변경'})),'review_invalid_input')
deny(query('admin_review_save_published_body',args(patch={**body,'contentKo':''})),'review_invalid_input')
deny(query('admin_review_save_published_body',args(patch={'contentKo':'기존 한국어','contentJa':'元の日本語'})),'review_invalid_input')
sql('update public.curations set content_ko='+lit('공개 글 직접 변경')+' where id='+lit(pid)+';')
deny(query('admin_review_save_published_body',args()),'review_conflict')
d=detail();ok(d['content']['contentKo']=='공개 글 직접 변경')
sql("create function public.published_body_test_fail() returns trigger language plpgsql as $$begin raise exception 'synthetic_atomic_failure';end$$; create trigger published_body_test_fail before insert on machimoa_review.admin_review_events for each row execute function public.published_body_test_fail();")
deny(query('admin_review_save_published_body',args(d)),'synthetic_atomic_failure')
ok(scalar('(select count(*) from machimoa_review.published_body_edits where candidate_id='+lit(cid)+')')==0)
ok(detail()==d)
sql('drop trigger published_body_test_fail on machimoa_review.admin_review_events;drop function public.published_body_test_fail();')
barrier=Barrier(2)
def concurrent():
 barrier.wait()
 try:rpc('admin_review_save_published_body',args(d));return 'saved'
 except RuntimeError as e:assert 'review_conflict' in str(e);return 'conflict'
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:concurrent(),range(2)))
ok(sorted(results)==['conflict','saved'])
saved=detail();ok(saved['publishedBodyVersion']!=d['publishedBodyVersion'] and saved['version']!=d['version'])
ok(saved['content']['contentKo']==body['contentKo'] and saved['content']['contentJa']==body['contentJa'])
pc=scalar('(select to_jsonb(p) from public.curations p where id='+lit(pid)+')')
cc=scalar('(select to_jsonb(c) from machimoa_review.curation_candidates c where id='+lit(cid)+')')
for column,value in before_public.items():
 if column not in ['content','content_ko','content_ja','updated_at']:ok(pc[column]==value)
for column,value in before_candidate.items():
 if column not in ['content','content_ko','content_ja','updated_at']:ok(cc[column]==value)
audit=scalar('(select to_jsonb(e) from machimoa_review.published_body_edits e where candidate_id='+lit(cid)+')')
ok(audit['before_public']['contentKo']=='공개 글 직접 변경' and audit['before_candidate']['contentKo']=='기존 한국어')
ok(audit['after_body']==body and audit['actor']==actor)
ok(saved['history'][0]['fields']==['published_body_edit'])
deny(query('admin_review_save_published_body',args(d)),'review_conflict')
sql("insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,claim_lease_until,reason_codes) values("+lit(sid)+",repeat('a',64),'ai_enrichment','claimed',now(),now(),now()+interval '1 hour','{}');")
deny(query('admin_review_save_published_body',args(saved,{'contentKo':'다른 본문','contentJa':'別の本文'})),'review_conflict')
sql('delete from machimoa_review.processing_jobs where source_item_id='+lit(sid)+';')
sql("update machimoa_review.ingest_sources set enabled=false where source_id='youthcenter_policy';")
deny(query('admin_review_save_published_body',args(saved,{'contentKo':'다른 본문','contentJa':'別の本文'})),'program_candidate_unavailable')

# Native My서울 published records from this cloned synthetic-only test database.
native_ids=scalar("(select jsonb_agg(id) from machimoa_review.curation_candidates where source='myseoul_program' and review_status='published')")
ok(bool(native_ids))
for native in native_ids or []:
 n=rpc('admin_review_published_detail',[native])
 before=scalar("(select jsonb_build_array((select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_program_facts f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_content_filters f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.myseoul_change_reviews f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.program_candidate_inputs f)))")
 q=query('admin_review_save_published_body',[native,n['revision'],n['version'],n['publishedBodyVersion'],{'contentKo':n['content']['contentKo']+'\n합성 수정','contentJa':n['content']['contentJa']+'\n合成修正'},'합성 본문 수정',actor])
 if n['programInfo']['inputChanged']:deny(q,'review_conflict')
 else:sql(q);ok(True)
 after=scalar("(select jsonb_build_array((select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_program_facts f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_content_filters f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.myseoul_change_reviews f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.program_candidate_inputs f)))")
 ok(before==after)

# Fresh native fixture with matching source/facts/input, separate from the
# changed reclassification fixtures. No guard, trigger or ACK is bypassed.
ns,np,nc,nj=[str(uuid4()) for _ in range(4)];nk='synthetic-native-'+nc
template=native_ids[0]
sql("insert into machimoa_review.source_items select (jsonb_populate_record(null::machimoa_review.source_items,to_jsonb(s)||jsonb_build_object('id',"+lit(ns)+",'external_key',"+lit(nk)+"))).* from machimoa_review.source_items s join machimoa_review.curation_candidates c on c.source_item_id=s.external_key and s.source_id=machimoa_review.canonical_source_id(c.source) where c.id="+lit(template)+";")
sql("insert into machimoa_review.source_item_program_facts select (jsonb_populate_record(null::machimoa_review.source_item_program_facts,to_jsonb(f)||jsonb_build_object('source_item_id',"+lit(ns)+",'source_snapshot',to_jsonb(ns)))).* from machimoa_review.source_item_program_facts f join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash join machimoa_review.curation_candidates c on c.source_item_id=s.external_key and s.source_id=machimoa_review.canonical_source_id(c.source) cross join machimoa_review.source_items ns where c.id="+lit(template)+" and ns.id="+lit(ns)+";")
sql("insert into public.curations select (jsonb_populate_record(null::public.curations,to_jsonb(p)||jsonb_build_object('id',"+lit(np)+",'slug',"+lit(nk)+",'source_item_id',"+lit(nk)+"))).* from public.curations p join machimoa_review.curation_candidates c on c.published_curation_id=p.id where c.id="+lit(template)+";")
sql("insert into machimoa_review.curation_candidates overriding system value select (jsonb_populate_record(null::machimoa_review.curation_candidates,to_jsonb(c)||jsonb_build_object('id',"+lit(nc)+",'revision_seq',nextval(pg_get_serial_sequence('machimoa_review.curation_candidates','revision_seq')::regclass),'source_item_id',"+lit(nk)+",'source_revision_hash',ns.revision_hash,'published_curation_id',"+lit(np)+"))).* from machimoa_review.curation_candidates c cross join machimoa_review.source_items ns where c.id="+lit(template)+" and ns.id="+lit(ns)+";")
sql("insert into machimoa_review.processing_jobs(id,source_item_id,revision_hash,processing_stage,status,queued_at,available_at,completed_at) select "+lit(nj)+",id,revision_hash,'ai_enrichment','completed',clock_timestamp(),clock_timestamp(),clock_timestamp() from machimoa_review.source_items where id="+lit(ns)+";insert into machimoa_review.program_candidate_inputs(candidate_id,source_item_id,revision_hash,facts_version,job_id,claimed_at,lease_until,worker_id,schema_version,profile,api_category,input_facts,output_hash) select "+lit(nc)+",s.id,s.revision_hash,f.facts_version,"+lit(nj)+",clock_timestamp()-interval '2 minutes',clock_timestamp()-interval '1 minute','synthetic-completed','myseoul-program-facts-v1-local','myseoul-program-v1-local','합성',f.facts,repeat('a',64) from machimoa_review.source_items s join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash where s.id="+lit(ns)+";")
# A public image can differ from the source-image projection. The existing
# candidate UPDATE trigger must not replace it during a body-only edit.
public_image='https://global.seoul.go.kr/contents/commoneditor/synthetic-preserved.png'
sql('update public.curations set source_image_url='+lit(public_image)+' where id='+lit(np)+';')
native_public=scalar('(select to_jsonb(p) from public.curations p where id='+lit(np)+')')
n=rpc('admin_review_published_detail',[nc]);ok(not n['programInfo']['inputChanged'])
protected="(select jsonb_build_array((select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_program_facts f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_content_filters f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.myseoul_change_reviews f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.program_candidate_inputs f),(select jsonb_agg(to_jsonb(f)) from machimoa_review.review_classification_candidates f)))"
before=scalar(protected)
changed=rpc('admin_review_save_published_body',[nc,n['revision'],n['version'],n['publishedBodyVersion'],{'contentKo':n['content']['contentKo']+'\n합성 본문만 수정','contentJa':n['content']['contentJa']+'\n合成本体のみ修正'},'현재 입력 합성 본문 수정',actor])
ok(changed['content']['contentKo'].endswith('합성 본문만 수정'))
ok(changed['publishedAt']==n['publishedAt'] and changed['publishedId']==n['publishedId'])
ok(scalar(protected)==before)
native_after=scalar('(select to_jsonb(p) from public.curations p where id='+lit(np)+')')
ok(native_after['source_image_url']==public_image)
ok({k:v for k,v in native_after.items() if k not in ['content','content_ko','content_ja','updated_at']}=={k:v for k,v in native_public.items() if k not in ['content','content_ko','content_ja','updated_at']})
sql(down)
ok(not scalar("to_regprocedure('public.admin_review_save_published_body(uuid,text,text,text,jsonb,text,uuid)') is not null"))
ok(scalar('(select to_jsonb(e) from machimoa_review.published_body_edits e where candidate_id='+lit(cid)+')')==audit)
ok(scalar('(select content_ko from public.curations where id='+lit(pid)+')')==body['contentKo'])
print(json.dumps({'checks':checks,'database':db,'result':'passed','productionAccess':False,'providerCalls':0}))
