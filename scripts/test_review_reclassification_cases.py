"""Synthetic classification cases. The caller supplies the verified local DB only."""
import copy
import json
from pathlib import Path
from uuid import uuid4

def run_cases(sql, root, only="all"):
    from test_myseoul_db import fixtures
    count=0
    def lit(v):
        if v is None:return 'NULL'
        if isinstance(v,bool):return str(v).lower()
        if isinstance(v,int):return str(v)
        return "'"+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)).replace("'","''")+"'"
    def value(q):return json.loads(sql('select to_jsonb(q) from ('+q+') q;'))
    def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
    def rpc(name,args):return json.loads(sql('begin;set local role service_role;select to_jsonb(public.'+name+'('+','.join(map(lit,args))+'));commit;'))
    def ok(v):
        nonlocal count
        assert v
        count+=1
    def deny(q,code):
        nonlocal count
        try:sql(q)
        except RuntimeError as e:assert code in str(e),str(e);count+=1
        else:raise AssertionError('expected '+code)
    def reject(name,args,code='PT409'):
        deny('begin;set local role service_role;select public.'+name+'('+','.join(map(lit,args))+');commit;',code)
    down=(root/'supabase/rollback/20261010013000_review_reclassification_down.sql').read_text(encoding='utf-8')
    up=(root/'supabase/migrations/20261010013000_review_reclassification.sql').read_text(encoding='utf-8')
    if only!='narrow' and not scalar('exists(select 1 from machimoa_review.review_classifications)'):
        # A successor change blocks restoration without partial effects.
        deny("begin;alter function public.admin_review_classification_detail(uuid) set search_path='public';"+down,'classification_successor_changed')
        ok(scalar("(select proconfig=array['search_path=\"\"']::text[] from pg_proc where oid='public.admin_review_classification_detail(uuid)'::regprocedure)"))
        sql(down)
        ok(scalar("to_regclass('machimoa_review.review_classifications') is null"))
        sql(up)
    if only=='narrow':
        import re
        down_inner=re.sub(r'commit;\s*$','',re.sub(r'(?im)^begin;\s*','',down,count=1),flags=re.I)
        up_inner=re.sub(r'commit;\s*$','',re.sub(r'(?im)^begin;\s*','',up,count=1),flags=re.I)
        # Successor table and predecessor changes must roll back the entire attempt.
        deny('begin;alter table machimoa_review.review_classifications add column unexpected text;'+down,'classification_successor_table_changed')
        ok(not scalar("exists(select 1 from pg_attribute where attrelid='machimoa_review.review_classifications'::regclass and attname='unexpected')"))
        deny('begin;'+down_inner+"alter function machimoa_review.content_filter_info(uuid,text) set search_path='public';"+up_inner,'classification_predecessor_changed')
        ok(scalar("to_regprocedure('public.admin_review_reclassify(uuid,text,text,bigint,jsonb,jsonb,text,uuid)') is not null"))
    for name in ['review_classifications','review_classification_history','review_classification_claims','review_classification_candidates']:
        ok(scalar("(select relrowsecurity from pg_class where oid='machimoa_review."+name+"'::regclass)"))
        for role in ['anon','authenticated','service_role']:
            ok(not scalar("has_table_privilege('"+role+"','machimoa_review."+name+"','select')"))
    for name in ['admin_review_classification_detail(uuid)','admin_review_reclassify(uuid,text,text,bigint,jsonb,jsonb,text,uuid)','claim_reclassified_content_ai(uuid,text,bigint,text,integer)','finish_reclassified_content_ai(uuid,text,bigint,timestamptz,timestamptz,text,jsonb)']:
        for role in ['anon','authenticated']:
            ok(not scalar("has_function_privilege('"+role+"','public."+name+"','execute')"))
        ok(scalar("has_function_privilege('service_role','public."+name+"','execute')"))
    actor='00000000-0000-4000-8000-000000000001'
    sql("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id in ('myseoul_program','seoul_reservation','youthcenter_content','youthcenter_policy');")
    run=scalar("(select id from machimoa_review.ingest_runs where source_id='myseoul_program' and status='running' order by started_at desc limit 1)")
    if not run:run=scalar("(select run_id from public.start_ingest_run('myseoul_program',3600))")
    base=next(x['item'] for x in fixtures()['fixtures'] if x['name']=='personal')
    def observe():
        p=copy.deepcopy(base);old=p['external_key'].split(':')[-1];new=uuid4().hex.upper()
        p=json.loads(json.dumps(p).replace(old,new));p['revision_hash']=uuid4().hex*2;p['myseoul_facts']['source_revision']=p['revision_hash']
        return rpc('observe_myseoul_program',[run,[p],None])[0]['id']
    known=lambda v:{'status':'known','value':v}
    na={'status':'not_applicable','value':None}
    def content(cat):
        d={'schema':'content-filters-v1','category':cat,**{k:copy.deepcopy(na) for k in ['topic','location','delivery','audience','spaceKind','application','schedule']}}
        if cat=='program':d.update(topic=known('culture_experience'),delivery=known('online'),audience=known('other'),application=known({'deadlineKind':'fixed','start':None,'end':{'value':'2099-10-15','precision':'day'},'sourceStatus':'unknown'}))
        if cat=='event':d.update(topic=known('festival_exchange'),location=known({'scope':'specific','venues':[{'province':'11','district':None,'facility':'','address':''}]}),schedule=known({'kind':'continuous','occurrences':[{'start':{'value':'2099-10-09','precision':'day'},'end':{'value':'2099-10-09','precision':'day'}}],'recurrence':None}))
        if cat=='youth_space':d.update(spaceKind=known('introduction'),location=known({'scope':'specific','venues':[{'province':'41','district':'성남시','facility':'','address':''}]}))
        return d if cat in ('program','event','youth_space') else None
    def facts(cat):return {'productType':'living_guide' if cat=='living' else 'policy_reference' if cat=='policy' else 'event_program','category':cat,'scope':'nationwide','regions':[],'evidence':'합성 원문: 전국 신청 가능','foreignEligibility':'eligible' if cat=='policy' else 'unknown','delivery':'online' if cat in ('program','policy','living') else 'offline','deadlineKind':'fixed' if cat in ('program','policy') else '', 'deadlineOn':'2099-10-15' if cat in ('program','policy') else '', 'eventStart':'2099-10-02' if cat=='event' else '', 'eventEnd':'2099-10-16' if cat=='event' else ''}
    detail=lambda sid:rpc('admin_review_classification_detail',[sid])
    def save(item,cat):return rpc('admin_review_reclassify',[item['id'],item['revision'],item['version'],item['classificationVersion'],facts(cat),content(cat),'합성 원문 근거에 따라 분류와 필요한 값을 확인했습니다.',actor])
    output={'titleKo':'합성 검토 제목','contentKo':'합성 내용','summaryKo':'합성 요약','titleJa':'合成の題名','contentJa':'合成の内容','summaryJa':'合成の要約','aiModel':'synthetic-only'}
    def finish(c):return rpc('finish_reclassified_content_ai',[c['jobId'],c['revision'],c['classificationVersion'],c['claimedAt'],c['leaseUntil'],c['workerId'],output])
    if only=='narrow':
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        sid=observe();initial=detail(sid);barrier=Barrier(2)
        def concurrent_save(cat):
            barrier.wait()
            try:return save(initial,cat)['category']
            except RuntimeError as e:
                assert 'PT409' in str(e),str(e)
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(concurrent_save,['living','policy']))
        ok(results.count('conflict')==1);ok(detail(sid)['classificationVersion']==1)
        ok(scalar('(select count(*) from machimoa_review.review_classification_history where source_item_id='+lit(sid)+')')==1)
        sid=observe()
        # An unrelated pending stage in an older revision does not block current input.
        sql("insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at) values("+lit(sid)+","+lit('e'*64)+",'relationship_review','queued',array['relationship_unresolved'],clock_timestamp(),clock_timestamp());")
        after=save(detail(sid),'living');ok(after['ready']);c=rpc('claim_reclassified_content_ai',[sid,after['revision'],1,'synthetic-old-review',300]);ok(finish(c)['outcome']=='inserted')
        sid=observe()
        sql("insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at) select id,revision_hash,'relationship_review','queued',array['relationship_unresolved'],clock_timestamp(),clock_timestamp() from machimoa_review.source_items where id="+lit(sid)+';')
        after=save(detail(sid),'living');ok(not after['ready']);native=rpc('admin_myseoul_program_detail',[sid]);ok(native['status']=='open' and 'relationship_unresolved' in native['result']['reasons'])
        print(json.dumps({'checks':count,'transport':'isolated PostgreSQL narrow correction/concurrency','actualProviderCalls':0,'productionAccess':False}),flush=True)
        return
    if only=='public':
        for role in ['anon','authenticated']:
            ok(not scalar("has_function_privilege('"+role+"','public.admin_review_apply_public_classification(uuid,text,text,bigint,text,jsonb,boolean,text,uuid)','execute')"))
            ok(not scalar("has_table_privilege('"+role+"','machimoa_review.review_classification_publications','select')"))
        sid=observe();first=save(detail(sid),'program');job=rpc('claim_reclassified_content_ai',[sid,first['revision'],1,'synthetic-public-seed',300]);cid=finish(job)['candidateId']
        candidate=rpc('admin_review_detail',['candidates',cid]);published=rpc('admin_review_publish',[cid,candidate['revision'],candidate['version'],actor]);pid=published['publishedId']
        before=scalar('(select to_jsonb(cu) from public.curations cu where id='+lit(pid)+')')
        ready=detail(cid);ok(ready['id']==cid and ready['category']=='program' and ready['editable']);ok(ready['publication']['category']=='program')
        new=save(ready,'event');ok(new['id']==cid and new['ready']);ok(new['publication']['category']=='program')
        ok(scalar('(select to_jsonb(cu) from public.curations cu where id='+lit(pid)+')')==before)
        # Published candidate remains readable while the separate review draft changes.
        visible=rpc('admin_review_detail',['candidates',cid]);ok(visible['publishedId']==pid)
        review={k:output[k] for k in ['titleKo','titleJa','summaryKo','summaryJa','contentKo','contentJa']};review['contentKo']='합성 행사로 재분류한 본문';review['contentJa']='分類を確認した合成本文'
        def args(item,body=review,checked=True):return [cid,item['revision'],item['version'],item['classificationVersion'],item['publication']['version'],body,checked,'합성 양언어 본문과 필터를 확인해 공개 적용합니다.',actor]
        reject('admin_review_apply_public_classification',args(new,checked=False),'PT422')
        bad=dict(review,extra='client actor');reject('admin_review_apply_public_classification',args(new,bad),'PT422')
        ok(scalar('(select to_jsonb(cu) from public.curations cu where id='+lit(pid)+')')==before)
        # A concurrent public edit conflicts; it is never overwritten silently.
        sql('update public.curations set summary_ko='+lit('합성 동시 수정')+' where id='+lit(pid)+';')
        reject('admin_review_apply_public_classification',args(new))
        current=detail(cid)
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2)
        def concurrent_apply(_):
            barrier.wait()
            try:return rpc('admin_review_apply_public_classification',args(current))
            except RuntimeError as e:
                assert 'PT409' in str(e),str(e)
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(concurrent_apply,range(2)))
        ok(results.count('conflict')==1)
        applied=next(result for result in results if isinstance(result,dict))
        ok(applied['publication']['applied']);ok(applied['publication']['category']=='event')
        after=scalar('(select to_jsonb(cu) from public.curations cu where id='+lit(pid)+')')
        for k in ['id','slug','created_at','source','source_item_id','source_url','is_published','source_image_url']:ok(after[k]==before[k])
        ok(after['user_category']=='event' and after['category']=='event');ok(after['content_filters']==content('event'));ok(after['content_ko']==review['contentKo']);ok(after['content_ja']==review['contentJa'])
        ok(after['application_deadline_on'] is None and after['event_start_on']==facts('event')['eventStart'])
        ok(scalar('(select count(*) from machimoa_review.review_classification_publications where source_item_id='+lit(sid)+')')==1)
        reject('admin_review_apply_public_classification',args(applied))
        ok(scalar('(select count(*) from public.curations where id='+lit(pid)+')')==1)
        # Later public changes invalidate the completion snapshot. No blind retry.
        sql('update public.curations set summary_ja='+lit('合成の別変更')+' where id='+lit(pid)+';');ok(not detail(cid)['publication']['applied'])
        next_draft=save(detail(cid),'living');ok(next_draft['publication']['category']=='event')
        sql("insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at) select id,revision_hash,'relationship_review','queued',array['relationship_unresolved'],clock_timestamp(),clock_timestamp() from machimoa_review.source_items where id="+lit(sid)+';')
        blocked=detail(cid);ok(not blocked['ready']);reject('admin_review_apply_public_classification',args(blocked))
        ok(scalar('(select user_category from public.curations where id='+lit(pid)+')')=='event')
        deny(down,'classification_records_present');ok(scalar("to_regprocedure('public.admin_review_apply_public_classification(uuid,text,text,bigint,text,jsonb,boolean,text,uuid)') is not null"))
        print(json.dumps({'checks':count,'transport':'isolated PostgreSQL public reclassification','actualProviderCalls':0,'productionAccess':False}),flush=True)
        return
    items=[]
    for cat in (['policy','program','event','youth_space','living'] if only=='all' else []):
        sid=observe();original=scalar("(select facts from machimoa_review.source_item_program_facts where source_item_id="+lit(sid)+')')
        initial=detail(sid);ok(not initial['active']);ok(initial['editable'])
        after=save(initial,cat);ok(after['category']==cat and after['classificationVersion']==1);ok(after['ready'])
        ok(scalar("(select facts from machimoa_review.source_item_program_facts where source_item_id="+lit(sid)+')')==original)
        reject('admin_review_reclassify',[sid,initial['revision'],initial['version'],0,facts(cat),content(cat),'합성 stale version 확인입니다.',actor])
        if cat=='program':
            bad=content(cat);bad['delivery']=known('onsite')
            reject('admin_review_reclassify',[sid,after['revision'],after['version'],1,facts(cat),bad,'합성 불일치 입력 확인입니다.',actor],'PT422')
            ok(detail(sid)['classificationVersion']==1)
        claim=rpc('claim_reclassified_content_ai',[sid,after['revision'],1,'synthetic-'+cat,300]);ok(claim['facts']['category']==cat and claim['filters']==content(cat))
        locked=detail(sid);ok(not locked['editable'])
        reject('admin_review_reclassify',[sid,locked['revision'],locked['version'],1,facts(cat),content(cat),'합성 active claim 충돌입니다.',actor])
        reject('finish_reclassified_content_ai',[claim['jobId'],claim['revision'],1,claim['claimedAt'],claim['leaseUntil'],'other-worker',output])
        candidate=finish(claim);ok(candidate['outcome']=='inserted')
        ok(finish(claim)['outcome']=='duplicate')
        ok(claim['nativeConfirmedFacts']['programFacts']==original)
        cid=candidate['candidateId'];ok(scalar("(select user_category from machimoa_review.curation_candidates where id="+lit(cid)+')')==cat)
        ok(scalar('machimoa_review.program_candidate_info('+lit(cid)+")->>'canPublish'")=='true')
        # Public projection uses the same ID, category, dates and filter snapshot.
        published=rpc('admin_review_detail',['candidates',cid]);ok(published['category']==cat)
        pub=rpc('admin_review_publish',[cid,published['revision'],published['version'],actor])
        public_id=pub['publishedId'];ok(public_id is not None)
        ok(scalar('(select user_category from public.curations where id='+lit(public_id)+')')==cat)
        ok(scalar('(select content_filters from public.curations where id='+lit(public_id)+')')==content(cat))
        ok(detail(sid)['editable'] and detail(sid)['publication'] is not None)
        items.append((sid,cid))
    if only=='all':
        # An unprocessed older candidate is preserved but cannot be approved/published.
        sid=observe();one=save(detail(sid),'program');claim=rpc('claim_reclassified_content_ai',[sid,one['revision'],1,'synthetic-change',300]);cid=finish(claim)['candidateId']
        two=save(detail(sid),'event');ok(two['ready'] and two['classificationVersion']==2)
        ok(scalar('(select review_status from machimoa_review.curation_candidates where id='+lit(cid)+')')=='superseded')
        deny('select machimoa_review.classification_candidate_guard('+lit(cid)+');','classification_candidate_input_changed')
        next_claim=rpc('claim_reclassified_content_ai',[sid,two['revision'],2,'synthetic-change-new',300]);next_cid=finish(next_claim)['candidateId'];ok(next_cid!=cid)
        ok(scalar('(select content_ko from machimoa_review.curation_candidates where id='+lit(cid)+')')==output['contentKo'])
        # Original source facts changed: no auto-adoption or old snapshot publication.
        sql('update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='+lit(sid)+';')
        stale=detail(sid);ok(not stale['ready'] and 'classification_input_changed' in stale['reasons'])
        deny('select machimoa_review.classification_candidate_guard('+lit(next_cid)+');','classification_candidate_input_changed')
    # Generic sources can reclassify, with solved legacy review stages retired.
    for source in ['youthcenter_content','youthcenter_policy','seoul_reservation']:
        sid=str(uuid4());rev=uuid4().hex*2
        sql('insert into machimoa_review.source_items(id,source_id,external_key,revision_hash,disposition,min_fields,normalized_payload,has_source_url,body_usable,attachment_present,attachment_length,is_data_url,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status) values('+','.join(map(lit,[sid,source,'synthetic-'+uuid4().hex,rev,'observe_only',{'title':'합성 제목','source_url':'https://synthetic.invalid/item'},{'plain_text':'합성 원문 설명입니다. 전국 신청 가능하며 원문 자료를 읽지 않습니다.','source_url':'https://synthetic.invalid/item'},True,True,False,0,False,"2026-10-10T00:00:00Z","2026-10-10T00:00:00Z","missing","missing"]))+');')
        sql('insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at) select '+lit(sid)+','+lit(rev)+",stage,'queued',array['region_scope_unknown'],clock_timestamp(),clock_timestamp() from unnest(array['region_review','relevance_review','product_type_review']) stage;")
        after=save(detail(sid),'living');ok(after['ready']);claim=rpc('claim_reclassified_content_ai',[sid,rev,1,'synthetic-generic',300]);ok(finish(claim)['outcome']=='inserted')
    # Unrelated review stages cannot be erased by a complete category form.
    sid=observe()
    sql("insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at) select id,revision_hash,'relationship_review','queued',array['relationship_unresolved'],clock_timestamp(),clock_timestamp() from machimoa_review.source_items where id="+lit(sid)+';')
    after=save(detail(sid),'living');ok(not after['ready'])
    reject('claim_reclassified_content_ai',[sid,after['revision'],1,'synthetic-pending',300])
    ok(scalar('(select status from machimoa_review.processing_jobs where source_item_id='+lit(sid)+" and processing_stage='relationship_review')")=='queued')
    # Expiry requires an explicit fenced close; never reclaims automatically.
    sid=observe();after=save(detail(sid),'living');c=rpc('claim_reclassified_content_ai',[sid,after['revision'],1,'synthetic-expiry',30])
    reject('claim_reclassified_content_ai',[sid,after['revision'],1,'synthetic-expiry-new',30])
    # Let the synthetic 30-second lease expire naturally; no guard or fence edit.
    import time
    time.sleep(31)
    expired=c['leaseUntil']
    args=[c['jobId'],c['claimedAt'],expired,c['workerId'],1]
    ok(rpc('reclassified_content_ai_status',args+[False])['status']=='expired')
    ok(not detail(sid)['editable'])
    reject('reclassified_content_ai_status',[c['jobId'],c['claimedAt'],expired,'other-worker',1,True])
    ok(rpc('reclassified_content_ai_status',args+[True])['status']=='expired_closed')
    ok(detail(sid)['editable'])
    reject('finish_reclassified_content_ai',[c['jobId'],after['revision'],1,c['claimedAt'],expired,c['workerId'],output])
    next_claim=rpc('claim_reclassified_content_ai',[sid,after['revision'],1,'synthetic-expiry-explicit',300]);ok(finish(next_claim)['outcome']=='inserted')
    ok(rpc('reclassified_content_ai_status',args+[False])['status']=='superseded')
    # Legitimate records block rollback; no deletion to make it pass.
    deny(down,'classification_records_present')
    ok(scalar("to_regprocedure('public.admin_review_reclassify(uuid,text,text,bigint,jsonb,jsonb,text,uuid)') is not null"))
    print(json.dumps({'checks':count,'transport':'isolated PostgreSQL','actualProviderCalls':0,'productionAccess':False}),flush=True)
