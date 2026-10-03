-- Local draft: additive My change review and bounded collection. No source activation.
begin;
do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;end $$;
create table machimoa_review.myseoul_change_function_backup(name text primary key, definition text not null, installed text);
alter table machimoa_review.myseoul_change_function_backup enable row level security;
revoke all on machimoa_review.myseoul_change_function_backup from public,anon,authenticated,service_role;
insert into machimoa_review.myseoul_change_function_backup(name,definition)
select p.oid::regprocedure::text,pg_get_functiondef(p.oid) from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where (n.nspname='machimoa_review' and p.proname in ('admin_review_item','admin_review_snapshot','admin_review_lock','program_candidate_guard','program_candidate_info','myseoul_refresh','myseoul_admin_lock','myseoul_reason_fields','myseoul_evaluate'))
or (n.nspname='public' and p.proname in ('admin_review_detail','admin_review_list','observe_myseoul_program','claim_myseoul_program_ai','admin_myseoul_program_save'));
create table machimoa_review.myseoul_change_reviews(
 id bigint generated always as identity primary key,
 candidate_id uuid not null references machimoa_review.curation_candidates(id) on delete restrict,
 revision_hash text not null check(revision_hash ~ '^[a-f0-9]{64}$'),facts_version bigint not null check(facts_version>0),
 content_hash text not null, disposition text not null check(disposition in ('no_impact','edited')),
 actor uuid not null,note text not null check(char_length(btrim(note)) between 1 and 4000),
 occurred_at timestamptz not null default clock_timestamp());
alter table machimoa_review.myseoul_change_reviews enable row level security;
revoke all on machimoa_review.myseoul_change_reviews from public,anon,authenticated,service_role;
revoke all on sequence machimoa_review.myseoul_change_reviews_id_seq from public,anon,authenticated,service_role;
create index myseoul_change_review_candidate_idx on machimoa_review.myseoul_change_reviews(candidate_id,id desc);
create table machimoa_review.myseoul_collection_cursor(source_id text primary key check(source_id='myseoul_program'),after_key text not null default '',recheck_after text not null default '',check(after_key='' or after_key ~ '^[A-F0-9]{32}:[A-F0-9]{32}$'));
insert into machimoa_review.myseoul_collection_cursor values('myseoul_program','','');
alter table machimoa_review.myseoul_collection_cursor enable row level security;
revoke all on machimoa_review.myseoul_collection_cursor from public,anon,authenticated,service_role;

create function machimoa_review.myseoul_content(p_id uuid) returns jsonb
language sql stable set search_path='' as $$
select case when c.review_status='published' then (select jsonb_build_object('titleKo',p.title_ko,'titleJa',p.title_ja,'summaryKo',p.summary_ko,'summaryJa',p.summary_ja,'contentKo',p.content_ko,'contentJa',p.content_ja) from public.curations p where p.id=c.published_curation_id) else jsonb_build_object('titleKo',c.title_ko,'titleJa',c.title_ja,'summaryKo',c.summary_ko,'summaryJa',c.summary_ja,'contentKo',c.content_ko,'contentJa',c.content_ja) end
from machimoa_review.curation_candidates c where c.id=p_id $$;
create function machimoa_review.myseoul_content_hash(p_id uuid) returns text
language sql stable set search_path='' as $$
select encode(sha256(convert_to(jsonb_build_array(machimoa_review.myseoul_content(p_id),case when c.review_status='published' then (select jsonb_build_array(p.user_category,p.application_deadline_kind,p.application_deadline_on,p.event_start_on,p.event_end_on) from public.curations p where p.id=c.published_curation_id) else jsonb_build_array(c.user_category,c.application_deadline_kind,c.application_deadline_on,c.event_start_on,c.event_end_on) end)::text,'UTF8')),'hex')
from machimoa_review.curation_candidates c where id=p_id $$;
create function machimoa_review.myseoul_review_matches(p_id uuid) returns boolean
language sql stable set search_path='' as $$
select exists(select 1 from machimoa_review.myseoul_change_reviews r join machimoa_review.program_candidate_inputs m on m.candidate_id=r.candidate_id
join machimoa_review.source_items s on s.id=m.source_item_id
join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
where r.candidate_id=p_id and r.revision_hash=s.revision_hash and r.facts_version=f.facts_version
and r.content_hash=machimoa_review.myseoul_content_hash(p_id)) $$;

-- Small field comparison, not a natural-language change classifier.
create function machimoa_review.myseoul_merge_facts(p_observed jsonb,p_previous jsonb,p_current jsonb) returns jsonb
language plpgsql set search_path='' as $$
declare v jsonb:=p_observed;k text;code text;issue jsonb;fields text[];unchanged boolean;key2 text;old_value jsonb;new_value jsonb;actual jsonb;related text[];dependency text;source_changed boolean;
 mutable text[]:=array['description','official_url','public_category','purpose','target','residence','age','companion','language','conditions','application_actor','venue','delivery_mode','activity_region','activity_evidence','residence_scope','residence_evidence','qualification_note','fees','periods','session_evidence','meeting_evidence','application_methods','application_links','source_status'];
begin
 if p_previous->>'parser_version' is distinct from p_observed->>'parser_version' or p_previous->>'revision_contract' is distinct from p_observed->>'revision_contract' then
 raise exception using errcode='PT409',message='myseoul_contract_conflict';end if;
 foreach k in array mutable loop
 for key2 in select unnest(case when k='periods' then array['application','operation'] else array[''] end) loop
 old_value:=case when k='periods' then p_previous->k->key2 else p_previous->k end;
 new_value:=case when k='periods' then p_observed->k->key2 else p_observed->k end;
 actual:=case when k='periods' then p_current->k->key2 else p_current->k end;
 if actual is distinct from old_value then
 v:=jsonb_set(v,case when k='periods' then array[k,key2] else array[k] end,actual);
 source_changed:=old_value is distinct from new_value;
 related:=case when k in ('venue','delivery_mode','activity_region','activity_evidence') then array['venue','delivery_mode','activity_region','activity_evidence']
 when k in ('residence_scope','residence_evidence') then array['residence','residence_scope','residence_evidence']
 when k='qualification_note' then array['target','conditions','qualification_note'] else array[k] end;
 foreach dependency in array related loop
 if k<>'periods' and p_previous->dependency is distinct from p_observed->dependency then source_changed:=true;end if;
 end loop;
 if source_changed then
 code:='source_change_conflict:'||case when k='periods' then key2 else k end;
 if not exists(select 1 from jsonb_array_elements(v->'issues') x where x->>'code'=code) then
 v:=jsonb_set(v,'{issues}',v->'issues'||jsonb_build_array(jsonb_build_object('code',code,'field',k,'evidence',jsonb_build_array('원문 변경과 이전 운영자 보완값을 대조해 주세요.'))));end if;
 end if;end if;end loop;end loop;
 for issue in select value from jsonb_array_elements(p_observed->'issues') loop
 code:=issue->>'code';fields:=machimoa_review.myseoul_reason_fields(code);unchanged:=cardinality(fields)>0;
 foreach k in array fields loop if p_previous->k is distinct from p_observed->k then unchanged:=false;end if;end loop;
 if unchanged and exists(select 1 from jsonb_array_elements(p_previous->'issues') x where x->>'code'=code)
 and not exists(select 1 from jsonb_array_elements(p_current->'issues') x where x->>'code'=code) then
 v:=jsonb_set(v,'{issues}',coalesce((select jsonb_agg(x) from jsonb_array_elements(v->'issues') x where x->>'code'<>code),'[]'));end if;
 end loop;
 -- An unrelated later source edit cannot silently clear an unresolved carry conflict.
 for issue in select value from jsonb_array_elements(p_current->'issues') where value->>'code' like 'source_change_conflict:%' loop
 if not exists(select 1 from jsonb_array_elements(v->'issues') x where x->>'code'=issue->>'code') then
 v:=jsonb_set(v,'{issues}',v->'issues'||jsonb_build_array(issue));end if;end loop;
 perform machimoa_review.myseoul_validate(v);return v;
end $$;

-- Selective runtime patches preserve other sources and the installed predecessor ACL.
-- Missing anchors fail the migration transaction rather than replacing unfamiliar contracts.
do $patch$ declare r record;d text;before text;begin
for r in select p.oid,p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where (n.nspname='public' and p.proname in ('admin_review_detail','admin_review_list','claim_myseoul_program_ai','admin_myseoul_program_save'))
or (n.nspname='machimoa_review' and p.proname in ('admin_review_item','admin_review_lock','admin_review_snapshot','myseoul_admin_lock','myseoul_reason_fields','myseoul_evaluate')) loop
 d:=pg_get_functiondef(r.oid);before:=d;
 if r.proname='admin_review_detail' then
 d:=replace(d,'c.source_revision_hash is distinct from s.revision_hash','c.source_revision_hash is distinct from s.revision_hash and c.source<>''myseoul_program''');
 elsif r.proname='admin_review_list' then
 d:=replace(d,'and s.revision_hash=c.source_revision_hash','and (c.source=''myseoul_program'' or s.revision_hash=c.source_revision_hash)');
 d:=replace(d,'c.review_status=''pending''','(c.review_status=''pending'' or (c.source=''myseoul_program'' and c.review_status=''published'' and not machimoa_review.myseoul_review_matches(c.id) and exists(select 1 from machimoa_review.program_candidate_inputs m join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash where m.candidate_id=c.id and (m.revision_hash<>s.revision_hash or m.facts_version<>f.facts_version))))');
 elsif r.proname='admin_review_lock' then
 d:=replace(d,'c.source_revision_hash is distinct from s.revision_hash','c.source_revision_hash is distinct from s.revision_hash and c.source<>''myseoul_program''');
 elsif r.proname='admin_review_item' then
 d:=replace(d,'select coalesce(pg_catalog.jsonb_agg(distinct r.reason)',
 'if s->>''source_id''=''myseoul_program'' then
 s:=s||jsonb_build_object(''normalized_payload'',s->''normalized_payload''||jsonb_build_object(''source_url'',v->''program''->''facts''->>''official_url'',''plain_text'',v->''program''->''facts''->>''description''));
 if c->>''review_status''=''published'' then c:=c||jsonb_build_object(''user_category'',v->''publishedContent''->''user_category'',''application_deadline_on'',v->''publishedContent''->''application_deadline_on'',''event_start_on'',v->''publishedContent''->''event_start_on'');end if;end if;
 select coalesce(pg_catalog.jsonb_agg(distinct r.reason)');
 d:=replace(d,'''content'',pg_catalog.jsonb_build_object(','''content'',case when s->>''source_id''=''myseoul_program'' and c->>''review_status''=''published'' then machimoa_review.myseoul_content(p_id) else pg_catalog.jsonb_build_object(');
 d:=replace(d,'''contentJa'',coalesce(c->>''content_ja'','''')));','''contentJa'',coalesce(c->>''content_ja'','''')) end);');
 d:=replace(d,'''publishedId'',c->''published_curation_id'',','''publishedId'',c->''published_curation_id'',''publishedSlug'',case when s->>''source_id''=''myseoul_program'' then v->''publishedContent''->''slug'' else null end,');
 elsif r.proname='admin_myseoul_program_save' then
 d:=replace(d,'''source_fact_conflict:application'')','''source_fact_conflict:application'',''source_change_conflict:application'')');
 d:=replace(d,'''source_fact_conflict:operation'')','''source_fact_conflict:operation'',''source_change_conflict:operation'')');
 elsif r.proname='admin_review_snapshot' then
 d:=replace(d,'   from machimoa_review.source_items s join',' || case when s.source_id=''myseoul_program'' then jsonb_build_object(''changeReviews'',(select coalesce(jsonb_agg(to_jsonb(r) order by r.id),''[]'') from machimoa_review.myseoul_change_reviews r where r.candidate_id=p_id),''publishedContent'',(select to_jsonb(pc) from public.curations pc join machimoa_review.curation_candidates c on c.published_curation_id=pc.id where c.id=p_id)) else ''{}''::jsonb end from machimoa_review.source_items s join');
 elsif r.proname='myseoul_admin_lock' then
 d:=replace(d,'and status=''claimed'')','and status=''claimed'' and (claim_lease_until is null or claim_lease_until>clock_timestamp()))');
 elsif r.proname='myseoul_reason_fields' then
 d:=replace(d,'select case','select case when reason in (''source_change_conflict:application'',''source_change_conflict:operation'') then array[''periods''] when reason like ''source_change_conflict:%'' and split_part(reason,'':'',2) in (''description'',''official_url'',''public_category'',''purpose'',''target'',''residence'',''age'',''companion'',''language'',''conditions'',''application_actor'',''venue'',''delivery_mode'',''activity_region'',''activity_evidence'',''residence_scope'',''residence_evidence'',''qualification_note'',''fees'',''periods'',''session_evidence'',''meeting_evidence'',''application_methods'',''application_links'',''source_status'') then array[split_part(reason,'':'',2)]');
 elsif r.proname='myseoul_evaluate' then
 d:=replace(d,'like ''source_fact_conflict:%''','like ''source_fact_conflict:%'' or r like ''source_change_conflict:%''');
 elsif r.proname='claim_myseoul_program_ai' then
 d:=replace(d,'and source_item_id=s.external_key and source_revision_hash=p_revision','and source_item_id=s.external_key');
 end if;
 if d=before then raise exception 'myseoul patch anchor missing: %',r.proname;end if;execute d;
end loop;end $patch$;

create or replace function machimoa_review.myseoul_refresh(p_id uuid,p_now timestamptz default clock_timestamp()) returns void
language plpgsql set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; v_result jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='myseoul_program' for update;
 if not found then raise exception using errcode='PT404',message='myseoul_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash for update;
 if not found or f.schema_version<>'myseoul-program-facts-v1-local' or f.evaluated_profile<>'myseoul-program-v1-local' then
 raise exception using errcode='PT409',message='myseoul_contract_conflict';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 -- Preserve active claims; expire only leases that have actually elapsed.
 update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp()
 where source_item_id=p_id and status='claimed' and claim_lease_until<=clock_timestamp();
 -- Current revision / claim-attempt fences still reject past responses.
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 v_result:=case when f.manual_excluded then jsonb_build_object('decision','out_of_scope','disposition','non_target','scope','excluded','application','unknown',
 'quality','sufficient','public_category',f.facts->>'public_category','reasons',jsonb_build_array('manual_service_scope_excluded'),'ai_status','blocked')
 else machimoa_review.myseoul_evaluate(f.facts,p_now) end;
 update machimoa_review.source_item_program_facts set result=v_result where source_item_id=p_id and revision_hash=s.revision_hash;
 update machimoa_review.source_items set disposition=v_result->>'disposition' where id=p_id;
 update machimoa_review.processing_jobs set status=case when revision_hash=s.revision_hash and processing_stage='content_review'
 and v_result->>'decision'='in_scope' then 'completed' else 'cancelled' end,completed_at=clock_timestamp()
 where source_item_id=p_id and status in ('queued','failed') and (revision_hash<>s.revision_hash or
 (processing_stage='content_review' and v_result->>'decision'<>'review_required') or
 (processing_stage='ai_enrichment' and (v_result->>'decision'<>'in_scope' or not exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id and enabled and permission_status in ('approved_noncommercial','approved_commercial')))) or
 processing_stage not in ('content_review','ai_enrichment'));
 if v_result->>'decision'='review_required' then
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
 values(p_id,s.revision_hash,'content_review','queued',clock_timestamp(),clock_timestamp(),array(select jsonb_array_elements_text(v_result->'reasons')))
 on conflict(source_item_id,revision_hash,processing_stage) do update set reason_codes=excluded.reason_codes,status='queued',completed_at=null
 where machimoa_review.processing_jobs.status in ('queued','cancelled','failed');end if;
 -- Explicit My consumption only. Claim and completion recheck the current gate.
 if v_result->>'decision'='in_scope' and exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id and enabled and permission_status in ('approved_noncommercial','approved_commercial'))
 and not exists(select 1 from machimoa_review.curation_candidates where source='myseoul_program' and source_item_id=s.external_key ) then
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
 values(p_id,s.revision_hash,'ai_enrichment','queued',clock_timestamp(),clock_timestamp(),'{}')
 on conflict(source_item_id,revision_hash,processing_stage) do update set status='queued',completed_at=null
 where machimoa_review.processing_jobs.status='cancelled';
 end if;
end $$;
create or replace function public.observe_myseoul_program(p_run_id uuid,p_items jsonb,p_next_checkpoint jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare entry jsonb; r record; sid uuid; existing machimoa_review.source_item_program_facts%rowtype; outcomes jsonb:='[]';previous_rows jsonb:='{}';prior jsonb;incoming_existing text[]:='{}';
begin
 if p_run_id is null or p_items is null or jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items) not between 1 and 40 then
 raise exception using errcode='PT422',message='invalid_myseoul_batch';end if;
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' for update;
 perform 1 from machimoa_review.source_items where source_id='myseoul_program'
 and external_key in (select value->>'external_key' from jsonb_array_elements(p_items)) order by external_key for update;
 if (select count(distinct value->>'external_key') from jsonb_array_elements(p_items))<>jsonb_array_length(p_items) then
 raise exception using errcode='PT422',message='duplicate_myseoul_id';end if;
 for entry in select value from jsonb_array_elements(p_items) loop
 perform machimoa_review.myseoul_validate(entry->'myseoul_facts');
 if coalesce(entry->>'external_key','') !~ '^[A-F0-9]{32}:[A-F0-9]{32}$' or entry->>'revision_hash' is distinct from entry->'myseoul_facts'->>'source_revision' or
 entry->>'disposition' is distinct from 'observe_only' or entry->'jobs' is distinct from '[]'::jsonb or entry->'relationships' is distinct from '[]'::jsonb or
 (entry->'normalized_payload'->>'center_id')||':'||(entry->'normalized_payload'->>'program_id') is distinct from entry->>'external_key' then
 raise exception using errcode='PT422',message='invalid_myseoul_observation';end if;
 if entry->'normalized_payload'->>'parser_version' is distinct from 'myseoul-html-v2-local' or
 entry->'normalized_payload'->>'revision_contract' is distinct from 'myseoul-semantic-v2' or entry->'normalized_payload'->>'source_language' is distinct from 'ko' or
 entry->'normalized_payload'->>'official_url' is distinct from entry->'myseoul_facts'->>'official_url' or
 entry->'myseoul_facts'->>'official_url' is distinct from 'https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmDetail.do?cntr_no='||split_part(entry->>'external_key',':',1)||'&prgrm_no='||split_part(entry->>'external_key',':',2)||'&lang=ko' then
 raise exception using errcode='PT422',message='myseoul_identity_mismatch';end if;
 select to_jsonb(f) into prior from machimoa_review.source_item_program_facts f join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash where s.source_id='myseoul_program' and s.external_key=entry->>'external_key';
 if prior is not null then previous_rows:=previous_rows||jsonb_build_object(entry->>'external_key',prior);end if;
 select f.* into existing from machimoa_review.source_item_program_facts f join machimoa_review.source_items s on s.id=f.source_item_id
 where s.source_id='myseoul_program' and s.external_key=entry->>'external_key' and f.revision_hash=entry->>'revision_hash';
 if found then incoming_existing:=array_append(incoming_existing,entry->>'external_key');end if;
 if found and (existing.schema_version<>'myseoul-program-facts-v1-local' or existing.evaluated_profile<>'myseoul-program-v1-local'
 or existing.observed_facts->>'parser_version' is distinct from entry->'myseoul_facts'->>'parser_version'
 or existing.observed_facts->>'revision_contract' is distinct from entry->'myseoul_facts'->>'revision_contract') then
 raise exception using errcode='PT409',message='myseoul_contract_conflict';end if;
 end loop;
 for r in select * from machimoa_review.upsert_source_observations('myseoul_program',p_run_id,p_items,p_next_checkpoint) loop
 entry:=p_items->r.input_index;
 select id into sid from machimoa_review.source_items where source_id='myseoul_program' and external_key=r.external_key;
 insert into machimoa_review.source_item_program_facts(source_item_id,revision_hash,schema_version,evaluated_profile,source_snapshot,observed_facts,facts)
 values(sid,entry->>'revision_hash','myseoul-program-facts-v1-local','myseoul-program-v1-local',entry-'myseoul_facts',entry->'myseoul_facts',entry->'myseoul_facts') on conflict do nothing;
 prior:=previous_rows->r.external_key;
 if r.outcome='changed' and prior is not null and not r.external_key=any(incoming_existing) then
 update machimoa_review.source_item_program_facts set facts=machimoa_review.myseoul_merge_facts(entry->'myseoul_facts',prior->'observed_facts',prior->'facts'),
 manual_excluded=(prior->>'manual_excluded')::boolean,updated_by=(prior->>'updated_by')::uuid,updated_at=clock_timestamp()
 where source_item_id=sid and revision_hash=entry->>'revision_hash';end if;
 -- Source reversion must never undo a human service-scope exclusion.
 if r.outcome='changed' and prior is not null and (prior->>'manual_excluded')::boolean then
 update machimoa_review.source_item_program_facts set manual_excluded=true,facts_version=facts_version+1,
 updated_by=(prior->>'updated_by')::uuid,updated_at=clock_timestamp()
 where source_item_id=sid and revision_hash=entry->>'revision_hash' and not manual_excluded;end if;
 perform machimoa_review.myseoul_refresh(sid);
 outcomes:=outcomes||jsonb_build_array(jsonb_build_object('id',sid,'outcome',r.outcome,'revision',entry->>'revision_hash'));
 end loop;return outcomes;
end $$;

create function machimoa_review.program_candidate_info_before_myseoul_changes(p_id uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('inputFactsVersion',m.facts_version,'currentFactsVersion',f.facts_version,
 'inputChanged',m.facts_version<>f.facts_version,
 'canPublish',m.facts_version=f.facts_version and not f.manual_excluded and src.enabled and
 src.permission_status in ('approved_noncommercial','approved_commercial') and
 (s.source_id<>'myseoul_program' or not exists(select 1 from machimoa_review.processing_jobs
 where source_item_id=s.id and revision_hash=s.revision_hash and processing_stage<>'ai_enrichment' and status in ('queued','claimed'))) and
 (case when s.source_id='myseoul_program' then machimoa_review.myseoul_evaluate(f.facts,statement_timestamp()) else machimoa_review.program_evaluate(f.facts,statement_timestamp()) end)->>'decision'='in_scope',
 'applicationPeriod',case when s.source_id='myseoul_program' then coalesce((select string_agg(value->>'raw',' / ') from jsonb_array_elements(m.input_facts->'periods'->'application')),'공식 안내 확인') else concat(m.input_facts->'periods'->'RCPTBGNDT'->>'value',' ~ ',m.input_facts->'periods'->'RCPTENDDT'->>'value') end,
 'operatingPeriod',case when s.source_id='myseoul_program' then coalesce((select string_agg(value->>'raw',' / ') from jsonb_array_elements(m.input_facts->'periods'->'operation')),'공식 안내 확인') else concat(m.input_facts->'periods'->'SVCOPNBGNDT'->>'value',' ~ ',m.input_facts->'periods'->'SVCOPNENDDT'->>'value') end)
 from machimoa_review.program_candidate_inputs m join machimoa_review.source_item_program_facts f
 on f.source_item_id=m.source_item_id and f.revision_hash=m.revision_hash
 join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash
 join machimoa_review.ingest_sources src on src.source_id=s.source_id where m.candidate_id=p_id;
$$;
create function machimoa_review.program_candidate_guard_before_myseoul_changes(p_id uuid) returns void
language plpgsql security definer set search_path='' as $$
declare m machimoa_review.program_candidate_inputs%rowtype; f machimoa_review.source_item_program_facts%rowtype;
begin
 select * into m from machimoa_review.program_candidate_inputs where candidate_id=p_id;
 if not found then raise exception using errcode='PT409',message='program_candidate_input_changed';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=m.source_item_id and revision_hash=m.revision_hash for update;
 if not found or f.facts_version<>m.facts_version then raise exception using errcode='PT409',message='program_candidate_input_changed';end if;
 begin
 if m.schema_version='myseoul-program-facts-v1-local' and m.profile='myseoul-program-v1-local' then
 perform machimoa_review.myseoul_ai_check(m.source_item_id,m.revision_hash,m.facts_version);
 else perform machimoa_review.program_ai_check(m.source_item_id,m.revision_hash,m.facts_version);end if;
 exception when sqlstate 'PT409' then raise exception using errcode='PT409',message='program_candidate_unavailable';end;
end $$;
create or replace function machimoa_review.program_candidate_info(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare m machimoa_review.program_candidate_inputs%rowtype;s machimoa_review.source_items%rowtype;f machimoa_review.source_item_program_facts%rowtype;src machimoa_review.ingest_sources%rowtype;
 changed boolean;checked boolean;fields jsonb;r jsonb;
begin
 select * into m from machimoa_review.program_candidate_inputs where candidate_id=p_id;
 select * into s from machimoa_review.source_items where id=m.source_item_id;
 if s.source_id is distinct from 'myseoul_program' then return machimoa_review.program_candidate_info_before_myseoul_changes(p_id);end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=s.revision_hash;
 select * into src from machimoa_review.ingest_sources where source_id=s.source_id;
 changed:=m.revision_hash is distinct from s.revision_hash or m.facts_version is distinct from f.facts_version;
 checked:=machimoa_review.myseoul_review_matches(p_id);
 select coalesce(jsonb_agg(label order by label),'[]') into fields from (values
 ('title','제목'),('description','설명'),('target','대상'),('conditions','참여 조건'),('language','진행 언어'),('venue','장소'),('delivery_mode','진행 방식'),('fees','비용'),('periods','신청·진행 일정'),('session_evidence','회차·시간'),('meeting_evidence','집결 안내'),('application_methods','신청 방법'),('application_links','신청 링크'),('source_status','모집 상태'),('public_category','공개 분류'),('residence','거주 조건'),('age','연령'),('companion','동반 조건')) v(key,label)
 where case when key='title' then (select pf.source_snapshot->'min_fields'->>'title' from machimoa_review.source_item_program_facts pf where pf.source_item_id=m.source_item_id and pf.revision_hash=m.revision_hash) is distinct from s.min_fields->>'title'
 else m.input_facts->key is distinct from f.facts->key end;
 r:=machimoa_review.myseoul_evaluate(f.facts,statement_timestamp());
 return jsonb_build_object('inputFactsVersion',m.facts_version,'currentFactsVersion',f.facts_version,'inputChanged',changed,
 'changeReviewed',checked,'changedFields',fields,'comparisonAvailable',m.input_facts is not null,
 'canPublish',(not changed or checked) and f.schema_version='myseoul-program-facts-v1-local' and f.evaluated_profile='myseoul-program-v1-local'
 and not f.manual_excluded and src.enabled and src.permission_status in ('approved_noncommercial','approved_commercial') and r->>'decision'='in_scope'
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and processing_stage<>'ai_enrichment' and revision_hash=s.revision_hash and status in ('queued','claimed')),
 'applicationPeriod',coalesce((select string_agg(value->>'raw',' / ') from jsonb_array_elements(f.facts->'periods'->'application')),'공식 안내 확인'),
 'operatingPeriod',coalesce((select string_agg(value->>'raw',' / ') from jsonb_array_elements(f.facts->'periods'->'operation')),'공식 안내 확인'));
end $$;

create or replace function machimoa_review.program_candidate_guard(p_id uuid) returns void
language plpgsql security definer set search_path='' as $$
declare m machimoa_review.program_candidate_inputs%rowtype;s machimoa_review.source_items%rowtype;f machimoa_review.source_item_program_facts%rowtype;
begin
 select * into m from machimoa_review.program_candidate_inputs where candidate_id=p_id;
 select * into s from machimoa_review.source_items where id=m.source_item_id for update;
 if s.source_id is distinct from 'myseoul_program' then perform machimoa_review.program_candidate_guard_before_myseoul_changes(p_id);return;end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=s.revision_hash for update;
 if (m.revision_hash is distinct from s.revision_hash or m.facts_version is distinct from f.facts_version) and not machimoa_review.myseoul_review_matches(p_id) then
 raise exception using errcode='PT409',message='program_candidate_input_changed';end if;
 begin perform machimoa_review.myseoul_ai_check(s.id,s.revision_hash,f.facts_version);
 exception when sqlstate 'PT409' then raise exception using errcode='PT409',message='program_candidate_unavailable';end;
end $$;

create function public.admin_myseoul_review_change(p_id uuid,p_revision text,p_version text,p_disposition text,p_note text,p_content jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;f machimoa_review.source_item_program_facts%rowtype;c machimoa_review.curation_candidates%rowtype;
 item jsonb;k text;v text;before_content jsonb;changed text[];ap jsonb;op jsonb;
begin
 if p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$'
 or p_disposition is null or p_disposition not in ('no_impact','edited') or char_length(btrim(coalesce(p_note,''))) not between 1 and 4000 then
 raise exception using errcode='PT422',message='review_invalid_input';end if;
 select si.* into s from machimoa_review.source_items si join machimoa_review.program_candidate_inputs m on m.source_item_id=si.id
 where m.candidate_id=p_id and si.source_id='myseoul_program' for update of si;
 if not found then raise exception using errcode='PT404',message='review_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=s.revision_hash for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=s.id order by revision_hash,processing_stage for update;
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 select * into c from machimoa_review.curation_candidates where id=p_id for update;
 if c.review_status not in ('pending','published') then raise exception using errcode='PT409',message='review_already_processed';end if;
 if c.review_status='published' then
 if not exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id
 and enabled and permission_status in ('approved_noncommercial','approved_commercial')) then
 raise exception using errcode='PT409',message='program_candidate_unavailable';end if;
 select user_category,application_deadline_kind,application_deadline_on,event_start_on,event_end_on into c.user_category,c.application_deadline_kind,c.application_deadline_on,c.event_start_on,c.event_end_on
 from public.curations where id=c.published_curation_id for update;
 if not found then raise exception using errcode='PT409',message='review_conflict';end if;end if;
 item:=machimoa_review.admin_review_item('candidates',p_id);
 if s.revision_hash<>p_revision or item->>'version'<>p_version then raise exception using errcode='PT409',message='review_conflict';end if;
 if f.manual_excluded or machimoa_review.myseoul_evaluate(f.facts,clock_timestamp())->>'decision'<>'in_scope'
 or exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and ((status='claimed' and (claim_lease_until is null or claim_lease_until>clock_timestamp())) or (revision_hash=s.revision_hash and processing_stage<>'ai_enrichment' and status='queued'))) then
 raise exception using errcode='PT409',message='program_candidate_unavailable';end if;
 before_content:=machimoa_review.myseoul_content(p_id);
 if p_disposition='edited' then
 if p_content is null or jsonb_typeof(p_content)<>'object' or (select array_agg(key order by key) from jsonb_object_keys(p_content) key) is distinct from
 array['contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] or octet_length(p_content::text)>1200000 then raise exception using errcode='PT422',message='review_invalid_input';end if;
 for k,v in select key,value from jsonb_each_text(p_content) loop
 if jsonb_typeof(p_content->k)<>'string' or char_length(btrim(v)) not between 1 and (case when k like 'title%' then 300 when k like 'summary%' then 1000 else 200000 end) then raise exception using errcode='PT422',message='review_invalid_input';end if;
 p_content:=jsonb_set(p_content,array[k],to_jsonb(btrim(v)));end loop;
 if p_content=before_content then raise exception using errcode='PT422',message='review_invalid_input';end if;
 update machimoa_review.curation_candidates set title=p_content->>'titleKo',title_ko=p_content->>'titleKo',title_ja=p_content->>'titleJa',summary=p_content->>'summaryKo',summary_ko=p_content->>'summaryKo',summary_ja=p_content->>'summaryJa',content=p_content->>'contentKo',content_ko=p_content->>'contentKo',content_ja=p_content->>'contentJa' where id=p_id;
 elsif p_content is not null then raise exception using errcode='PT422',message='review_invalid_input';end if;
 -- Projection changes are required edits, never silently accepted as 'no impact'.
 select value->'endpoints' into ap from jsonb_array_elements(f.facts->'periods'->'application') where value->>'status'='ok' limit 1;
 select value->'endpoints' into op from jsonb_array_elements(f.facts->'periods'->'operation') where value->>'status'='ok' limit 1;
 if p_disposition='no_impact' and (c.user_category is distinct from f.facts->>'public_category' or
 (c.user_category='program' and (c.application_deadline_kind is distinct from case when ap is null then 'none' else 'fixed' end or c.application_deadline_on is distinct from left(ap->(jsonb_array_length(ap)-1)->>'value',10)::date)) or
 (c.user_category='event' and (c.event_start_on is distinct from left(op->0->>'value',10)::date or c.event_end_on is distinct from left(op->(jsonb_array_length(op)-1)->>'value',10)::date))) then
 raise exception using errcode='PT422',message='review_invalid_input';end if;
 if f.facts->>'public_category'='event' and (op is null or jsonb_array_length(op)=0) then raise exception using errcode='PT422',message='review_invalid_input';end if;
 update machimoa_review.curation_candidates set user_category=f.facts->>'public_category',
 application_deadline_kind=case when f.facts->>'public_category'='program' then case when ap is null then 'none' else 'fixed' end else null end,
 application_deadline_on=case when f.facts->>'public_category'='program' then left(ap->(jsonb_array_length(ap)-1)->>'value',10)::date end,
 event_start_on=case when f.facts->>'public_category'='event' then left(op->0->>'value',10)::date end,
 event_end_on=case when f.facts->>'public_category'='event' then left(op->(jsonb_array_length(op)-1)->>'value',10)::date end where id=p_id;
 -- Public modification is explicit and atomic; never changes publication visibility/time.
 if c.review_status='published' and p_disposition='edited' then
 update public.curations pc set title=cc.title,title_ko=cc.title_ko,title_ja=cc.title_ja,summary=cc.summary,summary_ko=cc.summary_ko,summary_ja=cc.summary_ja,content=cc.content,content_ko=cc.content_ko,content_ja=cc.content_ja,
 user_category=cc.user_category,application_deadline_kind=cc.application_deadline_kind,application_deadline_on=cc.application_deadline_on,event_start_on=cc.event_start_on,event_end_on=cc.event_end_on,updated_at=clock_timestamp()
 from machimoa_review.curation_candidates cc where cc.id=p_id and pc.id=c.published_curation_id;
 if not found then raise exception using errcode='PT409',message='review_conflict';end if;end if;
 insert into machimoa_review.myseoul_change_reviews(candidate_id,revision_hash,facts_version,content_hash,disposition,actor,note)
 values(p_id,s.revision_hash,f.facts_version,machimoa_review.myseoul_content_hash(p_id),p_disposition,p_actor,btrim(p_note));
 insert into machimoa_review.admin_review_events(source_item_id,candidate_id,revision_hash,action,actor,note,changed_fields)
 values(s.id,p_id,s.revision_hash,'save_candidate',p_actor,btrim(p_note),array['source_change_review:'||p_disposition,'source_change_stage:'||c.review_status]);
 return machimoa_review.admin_review_item('candidates',p_id);
end $$;

create function public.myseoul_collection_state(p_run_id uuid,p_keys text[]) returns jsonb
language plpgsql security definer set search_path='' as $$
declare known jsonb;rechecks jsonb;after_key text;recheck_after text;
begin
 if p_keys is null or cardinality(p_keys)>1000 or exists(select 1 from unnest(p_keys) k where k is null or k !~ '^[A-F0-9]{32}:[A-F0-9]{32}$') then raise exception using errcode='PT422',message='invalid_myseoul_command';end if;
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and active_run_id=p_run_id and lease_owner=p_run_id and lease_expires_at>clock_timestamp() for update;
 if not found then raise exception using errcode='PT409',message='myseoul_lease_lost';end if;
 select coalesce(jsonb_agg(external_key),'[]') into known from machimoa_review.source_items where source_id='myseoul_program' and external_key=any(p_keys);
 select c.recheck_after into recheck_after from machimoa_review.myseoul_collection_cursor c where source_id='myseoul_program';
 select coalesce(jsonb_agg(jsonb_build_object('key',external_key,'url',official_url) order by (external_key>recheck_after) desc,external_key),'[]') into rechecks from (
 select s.id,s.external_key,s.last_seen_at,f.facts->>'official_url' official_url from machimoa_review.source_items s
 join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
 where s.source_id='myseoul_program' and not f.manual_excluded and machimoa_review.myseoul_evaluate(f.facts,statement_timestamp())->>'application' not in ('closed','ended')
 and (exists(select 1 from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash and j.status in ('queued','claimed','failed'))
 or exists(select 1 from machimoa_review.curation_candidates c where c.source='myseoul_program' and c.source_item_id=s.external_key and c.review_status in ('pending','published')))
 order by (s.external_key>recheck_after) desc,s.external_key limit 8) q;
 -- Known includes off-homepage rechecks; no title-based merging.
 select coalesce(jsonb_agg(distinct k),'[]') into known from (select jsonb_array_elements_text(known) k union select value->>'key' from jsonb_array_elements(rechecks)) q;
 select c.after_key into after_key from machimoa_review.myseoul_collection_cursor c where source_id='myseoul_program';
 return jsonb_build_object('known',known,'rechecks',rechecks,'after',after_key,'recheckAfter',recheck_after);
end $$;

create function public.finish_myseoul_collection(p_run_id uuid,p_summary jsonb,p_requests integer,p_after text,p_recheck_after text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare k text;state text;
begin
 if p_summary is null or jsonb_typeof(p_summary)<>'object' or (select count(*) from jsonb_object_keys(p_summary))<>12 or not p_summary ?& array['coverage','source_complete','homepage_scope_complete','discovered','selected','processed','homepage_processed','omitted','failed','new_selected','recheck_selected','stop_reason']
 or p_summary->>'coverage' is distinct from 'homepage_education_only' or p_summary->'source_complete' is distinct from 'false'::jsonb
 or jsonb_typeof(p_summary->'homepage_scope_complete')<>'boolean' or p_requests is null or p_requests not between 0 and 9 or p_recheck_after is null or (p_recheck_after<>'' and p_recheck_after !~ '^[A-F0-9]{32}:[A-F0-9]{32}$') or p_after is null or (p_after<>'' and p_after !~ '^[A-F0-9]{32}:[A-F0-9]{32}$') then raise exception using errcode='PT422',message='invalid_myseoul_summary';end if;
 foreach k in array array['discovered','selected','processed','homepage_processed','omitted','failed','new_selected','recheck_selected'] loop
 if p_summary->>k !~ '^[0-9]+$' or (p_summary->>k)::numeric>10000 then raise exception using errcode='PT422',message='invalid_myseoul_counts';end if;end loop;
 if (p_summary->>'homepage_processed')::int+(p_summary->>'omitted')::int<>(p_summary->>'discovered')::int or
 ((p_summary->>'homepage_scope_complete')::boolean and (p_summary->>'omitted')::int<>0) or (p_summary->>'homepage_processed')::int>(p_summary->>'processed')::int or (p_summary->>'selected')::int>8 or (p_summary->>'processed')::int+(p_summary->>'failed')::int>(p_summary->>'selected')::int or
 (p_summary->>'new_selected')::int+(p_summary->>'recheck_selected')::int<>(p_summary->>'selected')::int or
 p_summary->>'stop_reason' not in ('read_failed','outcome_unknown','detail_failed','homepage_scope_complete','discovery_budget_limit') then raise exception using errcode='PT422',message='invalid_myseoul_counts';end if;
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and active_run_id=p_run_id and lease_owner=p_run_id and lease_expires_at>clock_timestamp() for update;
 if not found then raise exception using errcode='PT409',message='myseoul_lease_lost';end if;
 state:=case when p_summary->>'stop_reason' in ('read_failed','outcome_unknown') then 'failed' when (p_summary->>'homepage_scope_complete')::boolean and (p_summary->>'failed')::int=0 then 'complete' else 'incomplete' end;
 perform machimoa_review.finish_ingest_run(p_run_id,state,p_summary->>'stop_reason',p_requests,false,(p_summary->>'processed')::int);
 update machimoa_review.ingest_runs set run_summary=p_summary where id=p_run_id;
 update machimoa_review.myseoul_collection_cursor set after_key=p_after,recheck_after=p_recheck_after where source_id='myseoul_program';
 return jsonb_build_object('status',state,'summary',p_summary);
end $$;

-- All new internal helpers are private; only the three wrappers are executable by service_role.
do $$ declare r record;begin
 for r in select p.oid from pg_proc p join pg_namespace n on n.oid=p.pronamespace where
 (n.nspname='machimoa_review' and p.proname in ('myseoul_content','myseoul_content_hash','myseoul_review_matches','myseoul_merge_facts','program_candidate_info_before_myseoul_changes','program_candidate_guard_before_myseoul_changes')) or
 (n.nspname='public' and p.proname in ('admin_myseoul_review_change','myseoul_collection_state','finish_myseoul_collection')) loop
 execute format('revoke all on function %s from public,anon,authenticated,service_role',r.oid::regprocedure);
 end loop;end $$;
grant execute on function public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid),public.myseoul_collection_state(uuid,text[]),public.finish_myseoul_collection(uuid,jsonb,integer,text,text) to service_role;
update machimoa_review.myseoul_change_function_backup b set installed=pg_get_functiondef(b.name::regprocedure);
notify pgrst,'reload schema';
commit;
