-- Local-only rollout preparation. Disabled source; no backfill or v1 changes.
-- Apply only to an explicitly isolated test DB under this task's authorization.
begin;
do $$ begin
  if current_user <> 'postgres' then raise exception 'postgres_required'; end if;
end $$;

insert into machimoa_review.ingest_sources
 (source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source)
 values ('seoul_reservation','seoul_open_data','content','rest',false,'testing_only','seoul_reservation');
insert into machimoa_review.source_sync_state(source_id) values ('seoul_reservation');

-- Original structured extraction and inert source snapshot are retained per revision.
-- Operator changes affect facts only, never the observation or normalized payload.
create table machimoa_review.source_item_program_facts (
 source_item_id uuid not null references machimoa_review.source_items(id) on delete restrict,
 revision_hash text not null check (revision_hash ~ '^[a-f0-9]{64}$'),
 schema_version text not null default 'program-scope-v1-local' check(schema_version='program-scope-v1-local'),
 evaluated_profile text not null default 'program_capital_v1_local' check(evaluated_profile='program_capital_v1_local'),
 source_snapshot jsonb not null, observed_facts jsonb not null, facts jsonb not null,
 facts_version bigint not null default 1, manual_excluded boolean not null default false,
 result jsonb not null default '{}', updated_by uuid, updated_at timestamptz not null default clock_timestamp(),
 primary key(source_item_id,revision_hash)
);
alter table machimoa_review.source_item_program_facts enable row level security;
revoke all on machimoa_review.source_item_program_facts from public,anon,authenticated,service_role;

create function machimoa_review.program_validate(p jsonb) returns void
language plpgsql immutable security definer set search_path='' as $$
declare k text; v jsonb; d jsonb; dt text;
begin
 if p is null or jsonb_typeof(p)<>'object' or octet_length(p::text)>200000 then
   raise exception using errcode='PT422',message='invalid_program_facts'; end if;
 if (select array_agg(key order by key) from jsonb_object_keys(p) key) is distinct from
    array(select unnest(array['schema_version','content_kind','application_actor','delivery_mode','activity_region',
    'activity_evidence','residence_scope','residence_evidence','target_raw','conditions','application_methods','fee_kind',
    'fee_amounts','source_status','conflicts','missing','editorial_pending','period_evidence','periods','official_url','description']) order by 1)
 then raise exception using errcode='PT422',message='invalid_program_fields'; end if;
 if (p->>'schema_version') is distinct from 'program-scope-v1-local'
 or coalesce(p->>'content_kind','') not in ('program','unknown','employment','institutional_business','policy_finance')
 or coalesce(p->>'application_actor','') not in ('individual','individual_or_group','institution','nationality_excluded')
 or coalesce(p->>'delivery_mode','') not in ('online','offline','hybrid','unknown')
 or coalesce(p->>'activity_region','') not in ('capital','noncapital','mixed','not_applicable','unknown')
 or coalesce(p->>'residence_scope','') not in ('nationwide','includes_capital','capital','noncapital','not_stated','unknown')
 or coalesce(p->>'fee_kind','') not in ('free','paid','unknown')
 or coalesce(p->>'source_status','') not in ('open','reservation_closed','application_closed','unknown')
 then raise exception using errcode='PT422',message='invalid_program_value'; end if;
 foreach k in array array['schema_version','content_kind','application_actor','delivery_mode','activity_region',
 'residence_scope','target_raw','fee_kind','source_status','official_url','description'] loop
   if jsonb_typeof(p->k)<>'string' or char_length(p->>k)>60000 then
     raise exception using errcode='PT422',message='invalid_program_text'; end if;
 end loop;
 if p->>'official_url'<>'' and p->>'official_url' !~ '^https?://yeyak[.]seoul[.]go[.]kr/web/reservation/selectReservView[.]do[?]rsv_svc_id=[A-Za-z0-9_-]+$' then
   raise exception using errcode='PT422',message='invalid_official_url'; end if;
 foreach k in array array['activity_evidence','residence_evidence','conditions','application_methods','fee_amounts',
 'conflicts','missing','editorial_pending','period_evidence'] loop
   if jsonb_typeof(p->k)<>'array' or jsonb_array_length(p->k)>200 then
     raise exception using errcode='PT422',message='invalid_program_array'; end if;
   for v in select value from jsonb_array_elements(p->k) loop
     if jsonb_typeof(v)<>'string' or char_length(v#>>'{}')>4000 then
       raise exception using errcode='PT422',message='invalid_program_array'; end if;
   end loop;
 end loop;
 if p->'editorial_pending'<>'[]'::jsonb then raise exception using errcode='PT422',message='unsupported_editorial_gate'; end if;
 if exists(select 1 from jsonb_array_elements_text(p->'application_methods') x where x not in ('internet','onsite','phone')) then
   raise exception using errcode='PT422',message='invalid_application_method'; end if;
 if jsonb_typeof(p->'periods')<>'object' or
 (select array_agg(key order by key) from jsonb_object_keys(p->'periods') key) is distinct from
 array['RCPTBGNDT','RCPTENDDT','SVCOPNBGNDT','SVCOPNENDDT'] then
   raise exception using errcode='PT422',message='invalid_program_periods'; end if;
 for k,d in select key,value from jsonb_each(p->'periods') loop
   if jsonb_typeof(d)<>'object' or coalesce(d->>'status','') not in ('ok','missing','unparsed') then
     raise exception using errcode='PT422',message='invalid_program_periods'; end if;
   if d->>'status'='ok' then
     dt:=d->>'value';
     if d->>'precision'='day' then
       if dt is null or dt !~ '^\d{4}-\d{2}-\d{2}$' then raise exception using errcode='PT422',message='invalid_period_date'; end if;
       perform dt::date;
     elsif d->>'precision'='second' then
       if dt is null or dt !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+]09:00$' then raise exception using errcode='PT422',message='invalid_period_time'; end if;
       perform dt::timestamptz;
     else raise exception using errcode='PT422',message='invalid_period_precision'; end if;
   end if;
 end loop;
end $$;

create function machimoa_review.program_evaluate(p jsonb,p_now timestamptz) returns jsonb
language plpgsql immutable security definer set search_path='' as $$
declare excluded text[]:='{}'; reasons text[]:='{}'; unavailable text[]:='{}'; d jsonb; a jsonb; b jsonb; kind text; result text;
begin
 perform machimoa_review.program_validate(p);
 if p_now is null then raise exception using errcode='PT422',message='program_now_required'; end if;
 if p->>'content_kind' in ('employment','institutional_business') then excluded:=array_append(excluded,'service_scope_excluded'); end if;
 if p->>'application_actor' in ('institution','nationality_excluded') and not (p->'conflicts' ? 'application_actor_conflict') then
   excluded:=array_append(excluded,case when p->>'application_actor'='institution' then 'individual_participation_excluded' else 'nationality_explicitly_excluded' end); end if;
 if p->>'activity_region' in ('noncapital','mixed') and p->>'delivery_mode'<>'online' then excluded:=array_append(excluded,'activity_outside_capital'); end if;
 if p->>'residence_scope'='noncapital' then excluded:=array_append(excluded,'residence_outside_capital'); end if;
 if cardinality(excluded)>0 then return jsonb_build_object('decision','out_of_scope','disposition','non_target','reasons',to_jsonb(excluded)); end if;
 reasons:=array(select jsonb_array_elements_text(p->'missing')) || array(select jsonb_array_elements_text(p->'conflicts'));
 if p->>'official_url'='' then reasons:=array_append(reasons,'missing_source_url');end if;
 if char_length(btrim(p->>'description'))<20 and not reasons && array['attachment_dependent','program_description_missing'] then
 reasons:=array_append(reasons,'program_description_missing');end if;
 if exists(select 1 from jsonb_each(p->'periods') x where x.value->>'status'<>'ok') then reasons:=array_append(reasons,'period_missing_or_unparsed');end if;
 foreach kind in array array['RCPT','SVCOPN'] loop
   a:=p->'periods'->(kind||'BGNDT');b:=p->'periods'->(kind||'ENDDT');
   if a->>'status'='ok' and b->>'status'='ok' and
     (left(a->>'value',10)>left(b->>'value',10) or
      a->>'precision'='second' and b->>'precision'='second' and (a->>'value')::timestamptz>(b->>'value')::timestamptz) then
      reasons:=array_append(reasons,'period_order_conflict');end if;
 end loop;
 if p->>'fee_kind'='free' and exists(select 1 from jsonb_array_elements_text(p->'fee_amounts') x where x ~ '^[1-9][0-9,]*(\.[0-9]+)?\s*(만\s*)?원') then
 reasons:=array_append(reasons,'fee_conflict');end if;
 if p->>'content_kind'<>'program' then reasons:=array_append(reasons,case when p->>'content_kind'='policy_finance' then 'policy_eligibility_unconfirmed' else 'program_purpose_unconfirmed' end); end if;
 if p->>'delivery_mode'='unknown' then reasons:=array_append(reasons,'delivery_mode_unknown'); end if;
 if p->>'delivery_mode' in ('offline','hybrid') and (p->>'activity_region'<>'capital' or p->'activity_evidence'='[]'::jsonb) then reasons:=array_append(reasons,'activity_location_unknown'); end if;
 if p->>'residence_scope'='unknown' or p->>'delivery_mode'='online' and
 (p->>'residence_scope' not in ('nationwide','includes_capital','capital') or p->'residence_evidence'='[]'::jsonb) then reasons:=array_append(reasons,'residence_scope_unknown'); end if;
 if p->>'source_status'='unknown' then reasons:=array_append(reasons,'source_status_unknown'); end if;
 -- Stable first occurrence order, also used by Python.
 reasons:=array(select reason from unnest(reasons) with ordinality r(reason,n) group by reason order by min(n));
 d:=p->'periods'->'RCPTENDDT';
 if p->>'source_status' in ('reservation_closed','application_closed') or
 (d->>'status'='ok' and (case when d->>'precision'='day' then (p_now at time zone 'Asia/Seoul')::date>(d->>'value')::date else p_now>(d->>'value')::timestamptz end))
 then unavailable:=array_append(unavailable,'not_currently_accepting'); end if;
 d:=p->'periods'->'SVCOPNENDDT';
 if d->>'status'='ok' and (case when d->>'precision'='day' then (p_now at time zone 'Asia/Seoul')::date>(d->>'value')::date else p_now>(d->>'value')::timestamptz end)
 then unavailable:=array_append(unavailable,'program_ended'); end if;
 d:=p->'periods'->'RCPTBGNDT';
 if d->>'status'='ok' and (case when d->>'precision'='day' then (p_now at time zone 'Asia/Seoul')::date<(d->>'value')::date else p_now<(d->>'value')::timestamptz end)
 then unavailable:=array_append(unavailable,'application_not_started'); end if;
 if cardinality(unavailable)>0 and cardinality(reasons)=0 then result:='not_currently_available';reasons:=unavailable;
 elsif cardinality(reasons)>0 then result:='review_required';else result:='in_scope';end if;
 return jsonb_build_object('decision',result,'disposition',case when result='in_scope' then 'target' else 'observe_only' end,'reasons',to_jsonb(reasons));
end $$;

-- Reason-specific patch fields. Unsupported reasons are preserved, never cleared.
create function machimoa_review.program_reason_fields(reason text) returns text[]
language sql immutable security definer set search_path='' as $$
 select case
 when reason in ('activity_location_unknown','delivery_mode_unknown') then array['delivery_mode','activity_region','activity_evidence']
 when reason='residence_scope_unknown' then array['residence_scope','residence_evidence']
 when reason in ('program_purpose_unconfirmed','policy_eligibility_unconfirmed') then array['content_kind','description']
 when reason in ('attachment_dependent','program_description_missing') then array['description','content_kind','delivery_mode','activity_region','activity_evidence','application_methods']
 when reason='missing_source_url' then array['official_url']
 when reason in ('period_missing_or_unparsed','body_period_needs_confirmation','period_order_conflict','body_api_period_conflict','invalid_body_date','date_weekday_conflict') then array['periods','period_evidence']
 when reason in ('source_status_unknown','source_status_conflict') then array['source_status']
 when reason='application_actor_conflict' then array['application_actor','conditions','target_raw']
 when reason='target_conflict' then array['target_raw','conditions']
 when reason='fee_conflict' then array['fee_kind','fee_amounts']
 when reason='eligibility_document_unconfirmed' then array['conditions']
 else '{}'::text[] end
$$;

create function machimoa_review.program_refresh(p_id uuid,p_now timestamptz default clock_timestamp()) returns void
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 v_result jsonb; stage text; reason text[]; allowed boolean;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash for update;
 if not found then raise exception using errcode='PT404',message='program_facts_not_found';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
   raise exception using errcode='PT409',message='program_processing_active';end if;
 select enabled and permission_status in ('approved_noncommercial','approved_commercial') into allowed
 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 v_result:=case when f.manual_excluded then jsonb_build_object('decision','out_of_scope','disposition','non_target','reasons',jsonb_build_array('manual_service_scope_excluded'))
 else machimoa_review.program_evaluate(f.facts,p_now) end;
 update machimoa_review.source_item_program_facts set result=v_result where source_item_id=p_id and revision_hash=s.revision_hash;
 update machimoa_review.source_items set disposition=v_result->>'disposition' where id=p_id;
 -- Old revisions cannot remain queued. Completed jobs are never resurrected.
 update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp()
 where source_item_id=p_id and revision_hash<>s.revision_hash and status in ('queued','failed');
 stage:=case when v_result->>'decision'='review_required' then 'content_review'
             when v_result->>'decision'='in_scope' and allowed then 'ai_enrichment' else null end;
 update machimoa_review.processing_jobs set status=case when processing_stage='content_review' and v_result->>'decision'='in_scope' then 'completed' else 'cancelled' end,
 completed_at=clock_timestamp(),reason_codes=case when processing_stage='content_review' then '{}'::text[] else reason_codes end
 where source_item_id=p_id and revision_hash=s.revision_hash and status in ('queued','failed') and processing_stage is distinct from stage;
 if stage is not null then
   reason:=case when stage='content_review' then array(select jsonb_array_elements_text(v_result->'reasons')) else '{}'::text[] end;
   insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
   values(p_id,s.revision_hash,stage,'queued',clock_timestamp(),clock_timestamp(),reason)
   on conflict(source_item_id,revision_hash,processing_stage) do update
   set reason_codes=excluded.reason_codes,status='queued',completed_at=null
   where machimoa_review.processing_jobs.status in ('queued','cancelled','failed');
 end if;
end $$;

create function public.observe_seoul_program(p_run_id uuid,p_items jsonb,p_next_checkpoint jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare entry jsonb; r record; sid uuid; outcomes jsonb:='[]';
begin
 if p_items is null or jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items) not between 1 and 40 then
   raise exception using errcode='PT422',message='program_batch_invalid';end if;
 -- Lease first, then items in stable order, consistent with the base observation contract.
 perform 1 from machimoa_review.source_sync_state where source_id='seoul_reservation' for update;
 perform 1 from machimoa_review.source_items where source_id='seoul_reservation'
 and external_key in (select value->>'external_key' from jsonb_array_elements(p_items)) order by external_key for update;
 if (select count(distinct value->>'external_key') from jsonb_array_elements(p_items))<>jsonb_array_length(p_items) then
   raise exception using errcode='PT422',message='duplicate_program_id';end if;
 for entry in select value from jsonb_array_elements(p_items) loop
   perform machimoa_review.program_validate(entry->'program_facts');
   if entry->>'disposition' is distinct from 'observe_only' or entry->'jobs'<>'[]'::jsonb or entry->'relationships'<>'[]'::jsonb
      or entry->'normalized_payload'->>'source_id' is distinct from 'seoul_reservation' then
     raise exception using errcode='PT422',message='invalid_program_observation';end if;
 end loop;
 for r in select * from machimoa_review.upsert_source_observations('seoul_reservation',p_run_id,p_items,p_next_checkpoint) loop
   entry:=p_items->r.input_index;
   select id into sid from machimoa_review.source_items where source_id='seoul_reservation' and external_key=r.external_key;
   insert into machimoa_review.source_item_program_facts(source_item_id,revision_hash,source_snapshot,observed_facts,facts)
   values(sid,entry->>'revision_hash',entry-'program_facts',entry->'program_facts',entry->'program_facts') on conflict do nothing;
   perform machimoa_review.program_refresh(sid);
   outcomes:=outcomes||jsonb_build_array(jsonb_build_object('id',sid,'outcome',r.outcome,'revision',entry->>'revision_hash'));
 end loop;
 return outcomes;
end $$;

create function public.admin_program_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 jobs jsonb; history jsonb; editable text[]; reasons text[]; permission jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation';
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash;
 if not found then raise exception using errcode='PT404',message='program_facts_not_found';end if;
 select coalesce(jsonb_agg(jsonb_build_object('stage',processing_stage,'status',status,'reasons',reason_codes) order by processing_stage),'[]') into jobs
 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=s.revision_hash;
 select jsonb_build_object('enabled',enabled,'permission',permission_status) into permission from machimoa_review.ingest_sources where source_id=s.source_id;
 reasons:=array(select jsonb_array_elements_text(f.result->'reasons'));
 select array_agg(distinct field order by field) into editable from unnest(reasons) reason cross join lateral unnest(machimoa_review.program_reason_fields(reason)) field;
 select coalesce(jsonb_agg(jsonb_build_object('action',action,'actor',actor,'at',occurred_at,'note',note,'fields',changed_fields) order by id desc),'[]') into history
 from (select * from machimoa_review.admin_review_events where source_item_id=p_id order by id desc limit 25) e;
 return jsonb_build_object('id',p_id,'revision',s.revision_hash,'version',encode(sha256(convert_to(jsonb_build_array(s.revision_hash,f.facts_version,f.result,jobs,permission)::text,'UTF8')),'hex'),
 'schema',f.schema_version,'profile',f.evaluated_profile,'factsVersion',f.facts_version,
 'source',jsonb_build_object('name',s.source_id,'title',s.normalized_payload->>'title','url',s.normalized_payload->>'source_url','body',s.normalized_payload->>'program_text'),
 'facts',f.facts,'observedFacts',f.observed_facts,'result',f.result,'editableFields',coalesce(to_jsonb(editable),'[]'),
 'status',case when f.manual_excluded or f.result->>'decision'='out_of_scope' then 'excluded' when f.result->>'decision'='review_required' then 'open' else 'resolved' end,
 'aiStatus',coalesce((select status from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=s.revision_hash and processing_stage='ai_enrichment'),'blocked'),
 'history',history);
end $$;

create function public.admin_program_list(p_offset integer default 0,p_limit integer default 25) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare items jsonb;
begin
 if p_offset is null or p_offset not between 0 and 999999 or p_limit is null or p_limit not between 1 and 25 then
 raise exception using errcode='PT422',message='invalid_page';end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',id,'title',title,'reasons',reasons)),'[]') into items from (
 select s.id,s.normalized_payload->>'title' title,f.result->'reasons' reasons
 from machimoa_review.source_items s join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
 where s.source_id='seoul_reservation' and not f.manual_excluded and f.result->>'decision'='review_required'
 and exists(select 1 from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash
 and j.processing_stage='content_review' and j.status in ('queued','claimed'))
 order by s.first_seen_at,s.id offset p_offset limit p_limit) q;
 return items;
end $$;

create function public.admin_program_save(p_id uuid,p_revision text,p_version text,p_patch jsonb,p_resolve text[],p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; item jsonb;
 next_facts jsonb; field text; reason text; allowed text[]:='{}'; active text[]; changed text[]:='{}'; d jsonb;
begin
 if p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$'
 or p_patch is null or jsonb_typeof(p_patch)<>'object' or p_resolve is null or cardinality(p_resolve)>30
 or char_length(btrim(coalesce(p_note,''))) not between 1 and 4000 then
 raise exception using errcode='PT422',message='invalid_program_command';end if;
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 if s.revision_hash<>p_revision then raise exception using errcode='PT409',message='source_revision_conflict';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 item:=public.admin_program_detail(p_id);
 if item->>'version'<>p_version then raise exception using errcode='PT409',message='program_version_conflict';end if;
 if item->>'status'<>'open' or not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='content_review' and status='queued') then
 raise exception using errcode='PT409',message='program_already_processed';end if;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
 raise exception using errcode='PT409',message='program_processing_active';end if;
 active:=array(select jsonb_array_elements_text(f.result->'reasons'));
 foreach reason in array active loop allowed:=allowed||machimoa_review.program_reason_fields(reason);end loop;
 for field in select jsonb_object_keys(p_patch) loop
   if not field=any(allowed) then raise exception using errcode='PT422',message='program_field_read_only';end if;
   if p_patch->field is distinct from f.facts->field then changed:=array_append(changed,field);end if;
 end loop;
 if cardinality(changed)=0 then raise exception using errcode='PT422',message='program_change_required';end if;
 next_facts:=f.facts||p_patch;
 foreach reason in array p_resolve loop
   if reason is null or not reason=any(active) or not (changed && machimoa_review.program_reason_fields(reason)) then
   raise exception using errcode='PT422',message='program_reason_not_resolved';end if;
   next_facts:=jsonb_set(next_facts,'{missing}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'missing') where value#>>'{}'<>reason),'[]'));
   next_facts:=jsonb_set(next_facts,'{conflicts}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'conflicts') where value#>>'{}'<>reason),'[]'));
 end loop;
 perform machimoa_review.program_validate(next_facts);
 -- A resolution must supply actual facts, not merely remove a diagnostic flag.
 if next_facts->>'official_url'='' and 'missing_source_url'=any(p_resolve) or
 char_length(btrim(next_facts->>'description'))<20 and p_resolve && array['attachment_dependent','program_description_missing'] or
 next_facts->'activity_evidence'='[]'::jsonb and p_resolve && array['activity_location_unknown','delivery_mode_unknown'] or
 next_facts->'residence_evidence'='[]'::jsonb and 'residence_scope_unknown'=any(p_resolve) or
 next_facts->'period_evidence'='[]'::jsonb and p_resolve && array['body_period_needs_confirmation','date_weekday_conflict','body_api_period_conflict','invalid_body_date'] then
 raise exception using errcode='PT422',message='program_evidence_required';end if;
 if p_resolve && array['period_missing_or_unparsed','period_order_conflict','body_period_needs_confirmation','date_weekday_conflict','body_api_period_conflict','invalid_body_date'] then
   for d in select value from jsonb_each(next_facts->'periods') loop
     if d->>'status'<>'ok' then raise exception using errcode='PT422',message='period_still_missing';end if;
   end loop;
   if machimoa_review.program_evaluate(next_facts,clock_timestamp())->'reasons' ? 'period_order_conflict' then
     raise exception using errcode='PT422',message='invalid_period_order';end if;
 end if;
 update machimoa_review.source_item_program_facts set facts=next_facts,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,p_note,changed||array(select 'resolved:'||x from unnest(p_resolve) x));
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $$;

create function public.admin_program_exclude(p_id uuid,p_revision text,p_version text,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; item jsonb;
begin
 if p_actor is null or p_revision is null or p_version is null or char_length(btrim(coalesce(p_note,''))) not between 1 and 4000 then
 raise exception using errcode='PT422',message='invalid_program_command';end if;
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 perform 1 from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 item:=public.admin_program_detail(p_id);
 if s.revision_hash<>p_revision or item->>'version'<>p_version then raise exception using errcode='PT409',message='program_version_conflict';end if;
 if item->>'status'<>'open' or not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='content_review' and status='queued') then
 raise exception using errcode='PT409',message='program_already_processed';end if;
 update machimoa_review.source_item_program_facts set manual_excluded=true,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'exclude',p_actor,p_note,array['service_scope']);
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $$;

-- No grants on private functions/tables. Only the five public service wrappers.
do $$ declare r record; begin
 for r in select p.oid::regprocedure signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='machimoa_review' and p.proname in ('program_validate','program_evaluate','program_reason_fields','program_refresh')
    or n.nspname='public' and p.proname in ('observe_seoul_program','admin_program_detail','admin_program_list','admin_program_save','admin_program_exclude') loop
   execute format('revoke all on function %s from public,anon,authenticated,service_role',r.signature);
 end loop;
 for r in select p.oid::regprocedure signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='public' and p.proname in ('observe_seoul_program','admin_program_detail','admin_program_list','admin_program_save','admin_program_exclude') loop
   execute format('grant execute on function %s to service_role',r.signature);
 end loop;
end $$;
commit;
