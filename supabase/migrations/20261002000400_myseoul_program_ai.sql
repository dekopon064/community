-- My-only consumption, no registry activation or schedule changes.
begin;
alter table machimoa_review.program_candidate_inputs drop constraint program_candidate_inputs_schema_version_check;
alter table machimoa_review.program_candidate_inputs drop constraint program_candidate_inputs_profile_check;
alter table machimoa_review.program_candidate_inputs drop constraint program_candidate_inputs_api_category_check;
alter table machimoa_review.program_candidate_inputs add constraint program_candidate_inputs_contract_pair check (
(schema_version='program-scope-v1-local' and profile='program_capital_v1_local' and api_category='문화체험') or
(schema_version='myseoul-program-facts-v1-local' and profile='myseoul-program-v1-local' and char_length(api_category) between 1 and 100));


create function machimoa_review.myseoul_ai_check(p_id uuid,p_revision text,p_version bigint) returns void
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; allowed boolean;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='myseoul_program' for update;
 if not found or s.revision_hash is distinct from p_revision then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 if not found or f.facts_version is distinct from p_version or
 f.schema_version<>'myseoul-program-facts-v1-local' or f.evaluated_profile<>'myseoul-program-v1-local' then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=s.id order by revision_hash,processing_stage for update;
 select enabled and permission_status in ('approved_noncommercial','approved_commercial') into allowed
 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 if not coalesce(allowed,false) or f.manual_excluded or
 machimoa_review.myseoul_evaluate(f.facts,clock_timestamp())->>'decision'<>'in_scope' or
 f.facts->>'public_category' not in ('program','event') or
 exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) then
  raise exception using errcode='PT409',message='program_ai_unavailable';end if;
end $$;

create function public.claim_myseoul_program_ai(p_source_item_id uuid,p_revision text,p_worker_id text,p_lease_seconds integer) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 j machimoa_review.processing_jobs%rowtype; v_now timestamptz;
begin
 if p_source_item_id is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or
 p_worker_id is null or char_length(btrim(p_worker_id)) not between 1 and 128 or p_worker_id<>btrim(p_worker_id) or
 p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 -- Direct target selection; a different source/job cannot win this claim.
 select * into s from machimoa_review.source_items where id=p_source_item_id and source_id='myseoul_program' for update skip locked;
 if not found then return '[]'::jsonb;end if;
 -- Recover expired attempts even when gate is now closed. A queued row is not
 -- execution permission; the gate below remains authoritative. This prevents
 -- an abandoned claim from permanently blocking program refresh/admin edits.
 update machimoa_review.processing_jobs set status='queued',claimed_at=null,claimed_by=null,claim_lease_until=null
 where source_item_id=s.id and processing_stage='ai_enrichment' and status='claimed' and claim_lease_until<=clock_timestamp();
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision;
 if not found then return '[]'::jsonb;end if;
 begin perform machimoa_review.myseoul_ai_check(s.id,p_revision,f.facts_version);
 exception when sqlstate 'PT409' then return '[]'::jsonb;end;
 if exists(select 1 from machimoa_review.curation_candidates where source='myseoul_program'
 and source_item_id=s.external_key and source_revision_hash=p_revision) then return '[]'::jsonb;end if;
 v_now:=clock_timestamp();
 select * into j from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage='ai_enrichment' and ((status='queued' and available_at<=v_now and (next_retry_at is null or next_retry_at<=v_now))
 or (status='claimed' and claim_lease_until<=v_now)) for update skip locked;
 if not found then return '[]'::jsonb;end if;
 update machimoa_review.processing_jobs set status='claimed',claimed_at=v_now,
 claimed_by=p_worker_id,claim_lease_until=v_now+make_interval(secs=>p_lease_seconds) where id=j.id returning * into j;
 return jsonb_build_array(jsonb_build_object('jobId',j.id,'sourceItemId',s.id,'source','myseoul_program',
 'externalKey',s.external_key,'revision',p_revision,'schema',f.schema_version,'profile',f.evaluated_profile,
 'factsVersion',f.facts_version,'title',s.min_fields->>'title','publicCategory',f.facts->>'public_category',
 'facts',f.facts,'observedFacts',f.observed_facts,'claimedAt',j.claimed_at,'leaseUntil',j.claim_lease_until,'workerId',p_worker_id));
end $$;

create function public.finish_myseoul_program_ai(p_job_id uuid,p_revision text,p_facts_version bigint,
 p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_output jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 j machimoa_review.processing_jobs%rowtype; m machimoa_review.program_candidate_inputs%rowtype;
 v_id uuid; k text; v text; v_now timestamptz; v_hash text; deadline date; deadline_kind text; event_start date; event_end date; category text; ap jsonb; op jsonb;
begin
 if p_job_id is null or p_revision is null or p_facts_version is null or p_claimed_at is null or p_lease_until is null or
 p_worker_id is null or p_output is null or jsonb_typeof(p_output)<>'object' or octet_length(p_output::text)>600000 or
 (select array_agg(key order by key) from jsonb_object_keys(p_output) key) is distinct from
 array['aiModel','contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 for k,v in select key,value from jsonb_each_text(p_output) loop
 if jsonb_typeof(p_output->k)<>'string' or char_length(btrim(v)) not between 1 and
 (case when k like 'title%' then 300 when k like 'summary%' then 1000 when k='aiModel' then 100 else 200000 end) then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 p_output:=jsonb_set(p_output,array[k],to_jsonb(btrim(v)));end loop;
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs pj on pj.source_item_id=si.id
 where pj.id=p_job_id and si.source_id='myseoul_program' for update of si;
 if not found then raise exception using errcode='PT409',message='program_ai_stale';end if;
 perform machimoa_review.myseoul_ai_check(s.id,p_revision,p_facts_version);
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 if j.revision_hash is distinct from p_revision or j.processing_stage<>'ai_enrichment' or
 p_output->>'titleKo' is distinct from s.min_fields->>'title' then
 raise exception using errcode='PT409',message='program_ai_stale';end if;
 v_hash:=encode(sha256(convert_to(p_output::text,'UTF8')),'hex');
 select * into m from machimoa_review.program_candidate_inputs where job_id=p_job_id;
 if found then
 if j.status<>'completed' or m.facts_version<>p_facts_version or m.claimed_at is distinct from p_claimed_at or
 m.lease_until is distinct from p_lease_until or m.worker_id is distinct from p_worker_id or m.output_hash<>v_hash then
 raise exception using errcode='PT409',message='program_ai_stale';end if;
 return jsonb_build_object('candidateId',m.candidate_id,'outcome','duplicate');end if;
 v_now:=clock_timestamp();
 if j.status<>'claimed' or j.claimed_by is distinct from p_worker_id or j.claimed_at is distinct from p_claimed_at or
 j.claim_lease_until is distinct from p_lease_until or j.claim_lease_until<=v_now then
 raise exception using errcode='PT409',message='program_ai_lease_lost';end if;
 perform pg_advisory_xact_lock(hashtextextended('myseoul_program:'||s.external_key,0));
 if exists(select 1 from machimoa_review.curation_candidates where source='myseoul_program' and source_item_id=s.external_key
 and source_revision_hash=p_revision) then raise exception using errcode='PT409',message='program_ai_stale';end if;
 category:=f.facts->>'public_category';
 select value->'endpoints' into ap from jsonb_array_elements(f.facts->'periods'->'application') where value->>'status'='ok' limit 1;
 select value->'endpoints' into op from jsonb_array_elements(f.facts->'periods'->'operation') where value->>'status'='ok' limit 1;
 if category='program' then
 deadline_kind:=case when ap is null then 'none' else 'fixed' end;
 deadline:=left(ap->(jsonb_array_length(ap)-1)->>'value',10)::date;
 else
 event_start:=left(op->0->>'value',10)::date;
 event_end:=left(op->(jsonb_array_length(op)-1)->>'value',10)::date;
 if event_start is null or event_end is null or event_start>event_end then
 raise exception using errcode='PT422',message='event_period_required';end if;
 end if;
 v_id:=gen_random_uuid();
 update machimoa_review.curation_candidates set review_status='superseded',superseded_at=v_now,superseded_by_candidate_id=v_id
 where source='myseoul_program' and source_item_id=s.external_key and review_status='pending';
 insert into machimoa_review.curation_candidates(id,source,source_item_id,source_revision_hash,slug,category,user_category,
 title,summary,content,ai_status,title_ko,summary_ko,content_ko,ai_status_ko,title_ja,summary_ja,content_ja,ai_status_ja,
 source_url,ai_model,raw_payload,application_deadline_kind,application_deadline_on,event_start_on,event_end_on)
 values(v_id,'myseoul_program',s.external_key,p_revision,'myseoul-'||substr(encode(sha256(convert_to(s.external_key,'UTF8')),'hex'),1,32),
 coalesce(nullif(left(f.facts->>'source_category',100),''),category),category,p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',
 p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',
 p_output->>'titleJa',p_output->>'summaryJa',p_output->>'contentJa','success',f.facts->>'official_url',p_output->>'aiModel',
 jsonb_build_object('schema',f.schema_version,'profile',f.evaluated_profile,'factsVersion',f.facts_version,'sourceCategory',f.facts->'source_category','publicCategory',category),
 deadline_kind,deadline,event_start,event_end);
 insert into machimoa_review.program_candidate_inputs(candidate_id,source_item_id,revision_hash,facts_version,job_id,claimed_at,
 lease_until,worker_id,schema_version,profile,api_category,input_facts,output_hash)
 values(v_id,s.id,p_revision,f.facts_version,j.id,p_claimed_at,p_lease_until,p_worker_id,f.schema_version,f.evaluated_profile,
 coalesce(nullif(left(f.facts->>'source_category',100),''),category),f.facts,v_hash);
 perform machimoa_review.complete_processing_job(j.id,p_worker_id);
 return jsonb_build_object('candidateId',v_id,'outcome','inserted');
end $$;

create function public.fail_myseoul_program_ai(p_job_id uuid,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_error_code text) returns text
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype; sid uuid;
begin
 select si.id into sid from machimoa_review.source_items si join machimoa_review.processing_jobs pj on pj.source_item_id=si.id
 where pj.id=p_job_id and si.source_id='myseoul_program' for update of si;
 if sid is null then raise exception using errcode='PT409',message='program_ai_stale';end if;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 if j.processing_stage<>'ai_enrichment' or j.status<>'claimed' or j.claimed_at is distinct from p_claimed_at or
 j.claim_lease_until is distinct from p_lease_until or j.claimed_by is distinct from p_worker_id or j.claim_lease_until<=clock_timestamp() then
 raise exception using errcode='PT409',message='program_ai_lease_lost';end if;
 if p_error_code is null or p_error_code not in ('ai_schema_error','ai_blocked_cost_cap','ai_cost_bound_breach',
 'ai_or_enqueue_failed','ai_http_429','ai_http_404','ai_http_5xx','ai_http_4xx','ai_network','ai_unexpected_thinking') then
 p_error_code:='ai_or_enqueue_failed';end if;
 perform machimoa_review.fail_processing_job(p_job_id,p_worker_id,p_error_code);
 select status into j.status from machimoa_review.processing_jobs where id=p_job_id;
 return j.status;
end $$;

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
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
 raise exception using errcode='PT409',message='myseoul_processing_active';end if;
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
 and not exists(select 1 from machimoa_review.curation_candidates where source='myseoul_program' and source_item_id=s.external_key and source_revision_hash=s.revision_hash) then
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
 values(p_id,s.revision_hash,'ai_enrichment','queued',clock_timestamp(),clock_timestamp(),'{}')
 on conflict(source_item_id,revision_hash,processing_stage) do update set status='queued',completed_at=null
 where machimoa_review.processing_jobs.status='cancelled';
 end if;
end $$;

create or replace function public.admin_myseoul_program_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; jobs jsonb; permission jsonb; history jsonb; editable text[];
 result jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='myseoul_program';
 if not found then raise exception using errcode='PT404',message='myseoul_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash;
 if not found or f.schema_version<>'myseoul-program-facts-v1-local' or f.evaluated_profile<>'myseoul-program-v1-local' then
 raise exception using errcode='PT409',message='myseoul_contract_conflict';end if;
 -- Current-time read gate without writes. Stored review/result remain audit state.
 result:=case when f.manual_excluded then f.result else machimoa_review.myseoul_evaluate(f.facts,statement_timestamp()) end;
 select coalesce(jsonb_agg(jsonb_build_object('revision',revision_hash,'stage',processing_stage,'status',status,'reasons',reason_codes) order by revision_hash,processing_stage),'[]')
 into jobs from machimoa_review.processing_jobs where source_item_id=p_id;
 select jsonb_build_object('enabled',enabled,'permission',permission_status) into permission from machimoa_review.ingest_sources where source_id=s.source_id;
 select coalesce(array_agg(distinct field order by field),'{}') into editable
 from jsonb_array_elements_text(result->'reasons') reason cross join lateral unnest(machimoa_review.myseoul_reason_fields(reason)) field;
 select coalesce(jsonb_agg(jsonb_build_object('action',action,'actor',actor,'at',occurred_at,'note',note,'fields',changed_fields) order by id desc),'[]') into history
 from (select * from machimoa_review.admin_review_events where source_item_id=p_id order by id desc limit 25) e;
 return jsonb_build_object('id',p_id,'revision',s.revision_hash,'version',encode(sha256(convert_to(jsonb_build_array(s.revision_hash,f.facts_version,f.facts,jobs,permission)::text,'UTF8')),'hex'),
 'schema',f.schema_version,'profile',f.evaluated_profile,'factsVersion',f.facts_version,
 'source',jsonb_build_object('name',s.source_id,'title',s.min_fields->>'title','url',s.normalized_payload->>'official_url','body',s.normalized_payload->>'description'),
 'facts',f.facts,'observedFacts',f.observed_facts,'result',result,'editableFields',to_jsonb(editable),
 'status',case when f.manual_excluded or result->>'decision'='out_of_scope' then 'excluded' when result->>'decision'='review_required' then 'open' else 'resolved' end,
 'aiStatus',case when result->>'decision'<>'in_scope' or not (permission->>'enabled')::boolean or permission->>'permission' not in ('approved_noncommercial','approved_commercial') then 'blocked'
 else coalesce((select status from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=s.revision_hash and processing_stage='ai_enrichment'),'blocked') end,'history',history);
end $$;

create or replace function machimoa_review.program_candidate_guard(p_id uuid) returns void
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

create or replace function machimoa_review.canonical_source_id(p_source text) returns text
language sql stable security definer set search_path='' as $$
 select case btrim(lower(coalesce(p_source,''))) when 'youthcenter' then 'youthcenter_policy'
 when 'youthcenter_policy' then 'youthcenter_policy' when 'youthcenter_content' then 'youthcenter_content'
 when 'seoul_reservation' then 'seoul_reservation' when 'myseoul_program' then 'myseoul_program' else null end;
$$;

create or replace function machimoa_review.admin_review_snapshot(p_kind text, p_id uuid) returns jsonb
language sql stable security definer set search_path = '' as $fn$
  select pg_catalog.jsonb_build_object(
    'source', pg_catalog.to_jsonb(s), 'permission', pg_catalog.to_jsonb(src),
    'product', (select pg_catalog.to_jsonb(p) from machimoa_review.source_item_product_types p where p.source_item_id=s.id and p.revision_hash=s.revision_hash),
    'category', (select pg_catalog.to_jsonb(p) from machimoa_review.source_item_user_categories p where p.source_item_id=s.id and p.revision_hash=s.revision_hash),
    'deadline', (select pg_catalog.to_jsonb(p) from machimoa_review.source_item_application_deadlines p where p.source_item_id=s.id and p.revision_hash=s.revision_hash),
    'period', (select pg_catalog.to_jsonb(p) from machimoa_review.source_item_event_periods p where p.source_item_id=s.id and p.revision_hash=s.revision_hash),
    'jobs', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(j) order by j.processing_stage) from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash), '[]'::jsonb),
    'decisions', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d) order by d.review_type) from machimoa_review.ingest_review_decisions d where d.source_item_id=s.id and d.revision_hash=s.revision_hash), '[]'::jsonb),
    'candidate', case when p_kind='candidates' then (select pg_catalog.to_jsonb(c) from machimoa_review.curation_candidates c where c.id=p_id) end,
    'event', (select pg_catalog.max(e.id) from machimoa_review.admin_review_events e where e.source_item_id=s.id)
  ) || case when s.source_id in ('seoul_reservation','myseoul_program') then pg_catalog.jsonb_build_object(
    'program',(select pg_catalog.to_jsonb(f) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id and f.revision_hash=s.revision_hash),
    'programInput',(select pg_catalog.to_jsonb(m) from machimoa_review.program_candidate_inputs m where m.candidate_id=p_id)) else '{}'::jsonb end
   from machimoa_review.source_items s join machimoa_review.ingest_sources src on src.source_id=s.source_id
  where s.id=machimoa_review.admin_review_source(p_kind,p_id)
$fn$;

create or replace function machimoa_review.admin_review_item(p_kind text, p_id uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $fn$
declare
  v jsonb := machimoa_review.admin_review_snapshot(p_kind,p_id);
  s jsonb := v->'source'; p jsonb := v->'product'; c jsonb := v->'candidate';
  g jsonb := coalesce(p->'gate_facts','{}'::jsonb); reasons jsonb; stages text[];
  fields text[] := '{}'; history jsonb; base jsonb; is_open boolean; missing_type boolean; can_confirm_type boolean;
begin
  select coalesce(pg_catalog.jsonb_agg(distinct r.reason), '[]'::jsonb) into reasons
  from pg_catalog.jsonb_array_elements(v->'jobs') j,
       lateral pg_catalog.jsonb_array_elements_text(j->'reason_codes') r(reason)
  where j->>'processing_stage' <> 'ai_enrichment' and j->>'status' in ('queued','claimed');
  select coalesce(pg_catalog.array_agg(j->>'processing_stage'), '{}'::text[]) into stages
  from pg_catalog.jsonb_array_elements(v->'jobs') j
  where j->>'processing_stage' <> 'ai_enrichment' and j->>'status' in ('queued','claimed');
  is_open := pg_catalog.cardinality(stages)>0 and s->>'disposition'<>'non_target';
  missing_type := p is null or p = 'null'::jsonb;
  -- Since Sep 23, classification uncertainty is queued in content_review.
  -- Keep the legacy product_type_review path without permitting type overrides.
  can_confirm_type := missing_type and ('product_type_review'=any(stages) or
    ('content_review'=any(stages) and reasons ?| array['policy_lifecycle_uncertain','policy_lifecycle_conflict','end_date_absent_not_reference','product_type_unknown','product_type_unconfirmed']));
  if is_open then
    if can_confirm_type then fields := fields||array['productType']; end if;
    if can_confirm_type or
       (not missing_type and (machimoa_review.gate_facts_row_is_complete_v1(p->>'product_type',p->'gate_facts',
         p->>'assessment_schema_version',p->>'evaluated_profile',(p->>'evaluated_at')::timestamptz,'capital_v1') is not true
         or reasons ?| array['region_scope_unknown','relevance_unconfirmed'])) then
      fields := fields||array['delivery'];
      if missing_type or p->>'product_type'<>'living_guide' then fields := fields||array['scope','regions','evidence']; end if;
      if missing_type or p->>'product_type'='policy_reference' then fields := fields||array['foreignEligibility']; end if;
    end if;
    if reasons ? 'user_category_unconfirmed' and (v->>'category') is null then
      fields := fields||array['category','eventStart','eventEnd'];
    end if;
    if reasons ? 'application_deadline_unknown' then fields := fields||array['deadlineKind','deadlineOn']; end if;
  end if;
  -- Reuse original decisions and final candidate review metadata, supplement only missing edits.
  select coalesce(pg_catalog.jsonb_agg(h.entry order by h.at desc, h.tie desc),'[]'::jsonb) into history from (
    select e.occurred_at at, e.id::text tie, pg_catalog.jsonb_build_object('action',e.action,'actor',e.actor,'at',e.occurred_at,'note',e.note) entry
    from machimoa_review.admin_review_events e where e.source_item_id=(s->>'id')::uuid
      and e.revision_hash=s->>'revision_hash' and (p_kind='facts' and e.candidate_id is null or p_kind='candidates' and e.candidate_id=p_id)
    union all
    select d.reviewed_at, d.id::text, pg_catalog.jsonb_build_object('action',case when d.decision='reject' then 'exclude' else 'save_facts' end,'actor',d.reviewer,'at',d.reviewed_at,'note',coalesce(d.memo,''))
    from machimoa_review.ingest_review_decisions d where p_kind='facts' and d.source_item_id=(s->>'id')::uuid and d.revision_hash=s->>'revision_hash'
      and not exists(select 1 from machimoa_review.admin_review_events e where e.source_item_id=d.source_item_id and e.revision_hash=d.revision_hash and e.action='exclude' and e.actor::text=d.reviewer)
    union all
    select (c->>'reviewed_at')::timestamptz, 'legacy', pg_catalog.jsonb_build_object('action',case when c->>'review_status'='published' then 'publish' else 'reject' end,'actor',c->>'reviewed_by','at',c->>'reviewed_at','note',coalesce(c->>'review_notes',''))
    where p_kind='candidates' and c->>'reviewed_at' is not null and c->>'review_status' in ('published','rejected')
      and not exists(select 1 from machimoa_review.admin_review_events e where e.candidate_id=p_id and e.action in ('publish','reject'))
    order by 1 desc limit 100
  ) h;
  base := pg_catalog.jsonb_build_object('kind',p_kind,'id',p_id,'revision',s->>'revision_hash',
    'version',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(v::text,'UTF8')),'hex'),
    'source',pg_catalog.jsonb_build_object('name',s->>'source_id',
      'title',coalesce(s->'normalized_payload'->>'pstTtl',s->'normalized_payload'->>'plcyNm',s->'min_fields'->>'title','제목 확인 필요'),
      'url',coalesce(s->'normalized_payload'->>'source_url',s->'min_fields'->>'source_url',''),
      'body',pg_catalog.left(coalesce(s->'normalized_payload'->>'plain_text',''),200000)), 'history',history);
  if p_kind='facts' then return base||pg_catalog.jsonb_build_object(
    'status',case when s->>'disposition'='non_target' then 'excluded' when is_open then 'open' else 'resolved' end,
    'reasons',reasons,'editableFields',pg_catalog.to_jsonb(fields),
    'excludeAllowed',is_open and stages && array['content_review','product_type_review'],
    'restoredReviewPending',machimoa_review.admin_trash_pending(p_id,s->>'revision_hash'),
    'aiStatus',coalesce((select j->>'status' from pg_catalog.jsonb_array_elements(v->'jobs') j where j->>'processing_stage'='ai_enrichment'),'blocked'),
    'facts',pg_catalog.jsonb_build_object('productType',coalesce(p->>'product_type',''),'category',coalesce(v->'category'->>'user_category',''),
      'scope',coalesce(g->>'eligibility_scope','unknown'),'regions',coalesce(g->'eligibility_region_codes','[]'::jsonb),
      'evidence',coalesce(g->>'eligibility_region_evidence',''),'foreignEligibility',coalesce(g->>'foreign_resident_eligibility','unknown'),
      'delivery',coalesce(g->>'delivery_mode','unknown'),'deadlineKind',coalesce(v->'deadline'->>'application_deadline_kind',''),
      'deadlineOn',coalesce(v->'deadline'->>'application_deadline_on',''),'eventStart',coalesce(v->'period'->>'event_start_on',''),
      'eventEnd',coalesce(v->'period'->>'event_end_on',''))); end if;
  return base||case when s->>'source_id' in ('seoul_reservation','myseoul_program') then pg_catalog.jsonb_build_object('programInfo',machimoa_review.program_candidate_info(p_id)) else '{}'::jsonb end||pg_catalog.jsonb_build_object('status',c->>'review_status','category',coalesce(c->>'user_category',''),
    'period',coalesce(c->>'event_start_on',c->>'application_deadline_on','기간 정보 없음'),
    'publishedAt',c->'published_at','publishedId',c->'published_curation_id',
    'content',pg_catalog.jsonb_build_object('titleKo',coalesce(c->>'title_ko',c->>'title',''),'titleJa',coalesce(c->>'title_ja',''),
      'summaryKo',coalesce(c->>'summary_ko',c->>'summary',''),'summaryJa',coalesce(c->>'summary_ja',''),
      'contentKo',coalesce(c->>'content_ko',c->>'content',''),'contentJa',coalesce(c->>'content_ja','')));
end $fn$;

create or replace function machimoa_review.admin_review_candidate_action(p_action text,p_id uuid,p_revision text,p_version text,p_content jsonb,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path = '' as $fn$
declare v_id uuid; before_item jsonb; changed text[]; k text; val text; max_len integer;
begin
  v_id:=machimoa_review.admin_review_lock('candidates',p_id,p_revision,p_version,p_actor);
  if p_action='save_candidate' then
    if p_content is null or pg_catalog.jsonb_typeof(p_content)<>'object' or (select pg_catalog.count(*) from pg_catalog.jsonb_object_keys(p_content))<>6 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
    for k,val in select t.key,t.value from pg_catalog.jsonb_each_text(p_content) t loop
      max_len:=case when k in ('titleKo','titleJa') then 300 when k in ('summaryKo','summaryJa') then 1000 when k in ('contentKo','contentJa') then 200000 else 0 end;
      if pg_catalog.jsonb_typeof(p_content->k)<>'string' or val is null or pg_catalog.char_length(pg_catalog.btrim(val)) not between 1 and max_len then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
      p_content:=pg_catalog.jsonb_set(p_content,array[k],pg_catalog.to_jsonb(pg_catalog.btrim(val)));
    end loop;
    before_item:=machimoa_review.admin_review_item('candidates',p_id);
    select coalesce(pg_catalog.array_agg(t.key),'{}'::text[]) into changed from pg_catalog.jsonb_each(p_content) t where t.value is distinct from before_item->'content'->t.key;
    if pg_catalog.cardinality(changed)=0 then return before_item; end if;
    update machimoa_review.curation_candidates set title_ko=p_content->>'titleKo',title=p_content->>'titleKo',title_ja=p_content->>'titleJa',
      summary_ko=p_content->>'summaryKo',summary=p_content->>'summaryKo',summary_ja=p_content->>'summaryJa',
      content_ko=p_content->>'contentKo',content=p_content->>'contentKo',content_ja=p_content->>'contentJa' where id=p_id;
  elsif p_action='publish' then
    if exists(select 1 from machimoa_review.source_items where id=v_id and source_id in ('seoul_reservation','myseoul_program')) then
      perform machimoa_review.program_candidate_guard(p_id);
    end if;
    begin
      perform machimoa_review.publish_curation_candidate(p_id,p_actor::text,null,false);
    exception when others then raise sqlstate 'PT503' using message='review_publish_failed'; end;
  elsif p_action='reject' then
    if p_note is null or pg_catalog.char_length(pg_catalog.btrim(p_note)) not between 1 and 4000 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
    perform machimoa_review.reject_curation_candidate(p_id,p_actor::text,pg_catalog.btrim(p_note));
  else raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  insert into machimoa_review.admin_review_events(source_item_id,candidate_id,revision_hash,action,actor,note,changed_fields)
    values(v_id,p_id,p_revision,p_action,p_actor,coalesce(pg_catalog.btrim(p_note),''),coalesce(changed,'{}'::text[]));
  return machimoa_review.admin_review_item('candidates',p_id);
end $fn$;

create or replace function machimoa_review.claim_processing_jobs(
  p_stage pg_catalog.text,
  p_limit pg_catalog.int4,
  p_worker_id pg_catalog.text,
  p_lease_seconds pg_catalog.int4 default 300
)
returns table (
  job_id pg_catalog.uuid,
  source_item_id pg_catalog.uuid,
  source_id pg_catalog.text,
  external_key pg_catalog.text,
  revision_hash pg_catalog.text,
  processing_stage pg_catalog.text,
  curation_source pg_catalog.text,
  normalized_payload pg_catalog.jsonb,
  disposition pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_limit pg_catalog.int4 := coalesce(p_limit, 10);
  v_worker pg_catalog.text := pg_catalog.btrim(coalesce(p_worker_id, ''));
  v_lease pg_catalog.int4 := coalesce(p_lease_seconds, 300);
begin
  if p_stage is distinct from 'ai_enrichment' then
    return;
  end if;
  if v_limit < 1 or v_limit > 10 then
    raise exception 'invalid claim limit';
  end if;
  if pg_catalog.char_length(v_worker) not between 1 and 64 then
    raise exception 'invalid worker_id';
  end if;

  return query
  with picked as (
    select j.id
    from machimoa_review.processing_jobs as j
    join machimoa_review.source_items as si
      on si.id = j.source_item_id
     and si.revision_hash is not distinct from j.revision_hash
    where si.source_id <> 'myseoul_program'
      and j.processing_stage = 'ai_enrichment'
      and si.disposition = 'target'
      and si.body_usable is true
      and si.has_source_url is true
      and (
        (
          j.status = 'queued'
          and j.available_at <= v_now
          and (j.next_retry_at is null or j.next_retry_at <= v_now)
        )
        or (
          j.status = 'claimed'
          and j.claim_lease_until is not null
          and j.claim_lease_until <= v_now
        )
      )
      and (
        (
          exists (
            select 1
            from machimoa_review.source_item_product_types as pt
            where pt.source_item_id = j.source_item_id
              and pt.revision_hash is not distinct from j.revision_hash
              and pt.gate_facts is null
              and pt.assessment_schema_version is null
              and pt.evaluated_profile is null
              and pt.evaluated_at is null
          )
          and exists (
            select 1
            from machimoa_review.ingest_review_decisions as d
            where d.source_item_id = j.source_item_id
              and d.revision_hash is not distinct from j.revision_hash
              and d.decision = 'approve_ai'
          )
        )
        or (
          exists (
            select 1
            from machimoa_review.source_item_product_types as pt
            where pt.source_item_id = j.source_item_id
              and pt.revision_hash is not distinct from j.revision_hash
              and pt.gate_facts is not null
              and pt.gate_facts <> '{}'::pg_catalog.jsonb
              and pt.assessment_schema_version is not distinct from 'gate-facts-v1'
              and pt.evaluated_profile is not distinct from 'capital_v1'
              and pt.evaluated_at is not null
              and case
                when machimoa_review.gate_facts_row_is_complete_v1(
                  pt.product_type,
                  pt.gate_facts,
                  pt.assessment_schema_version,
                  pt.evaluated_profile,
                  pt.evaluated_at,
                  'capital_v1'
                ) then exists (
                  select 1
                  from machimoa_review.evaluate_source_item_gates(
                    si.body_usable,
                    si.has_source_url,
                    si.attachment_present,
                    pt.product_type,
                    pt.reason_codes,
                    pt.gate_facts
                  ) as ev
                  where ev.disposition is not distinct from 'target'
                )
                else false
              end
          )
        )
      )
      and machimoa_review.category_period_ready(j.source_item_id, j.revision_hash)
      and not exists (
        select 1
        from machimoa_review.processing_jobs as r
        where r.source_item_id = j.source_item_id
          and r.revision_hash is not distinct from j.revision_hash
          and r.processing_stage in (
            'region_review',
            'relevance_review',
            'content_review',
            'product_type_review'
          )
          and r.status in ('queued', 'claimed')
      )
    order by j.queued_at, j.id
    for update of j skip locked
    limit v_limit
  ),
  updated as (
    update machimoa_review.processing_jobs as j
    set
      status = 'claimed',
      claimed_at = v_now,
      claim_lease_until = v_now + (v_lease || ' seconds')::pg_catalog.interval,
      claimed_by = v_worker
    from picked
    where j.id = picked.id
    returning j.*
  )
  select
    u.id,
    u.source_item_id,
    si.source_id,
    si.external_key,
    u.revision_hash,
    u.processing_stage,
    s.legacy_curation_source,
    si.normalized_payload,
    si.disposition
  from updated as u
  join machimoa_review.source_items as si
    on si.id = u.source_item_id
  join machimoa_review.ingest_sources as s
    on s.source_id = si.source_id;
end
$function$;

create or replace function machimoa_review.publish_curation_candidate(
  p_candidate_id pg_catalog.uuid,
  p_reviewed_by pg_catalog.text,
  p_review_notes pg_catalog.text default null,
  p_allow_overwrite pg_catalog.bool default false
)
returns pg_catalog.uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_candidate_id pg_catalog.uuid := p_candidate_id;
  v_reviewed_by pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_reviewed_by, '')), '');
  v_review_notes pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_review_notes, '')), '');
  v_allow_overwrite pg_catalog.bool := coalesce(p_allow_overwrite, false);
  v_review_status pg_catalog.text;
  v_source pg_catalog.text;
  v_source_item_id pg_catalog.text;
  v_source_revision_hash pg_catalog.text;
  v_slug pg_catalog.text;
  v_category pg_catalog.text;
  v_title_ko pg_catalog.text;
  v_title_ja pg_catalog.text;
  v_summary_ko pg_catalog.text;
  v_summary_ja pg_catalog.text;
  v_content_ko pg_catalog.text;
  v_content_ja pg_catalog.text;
  v_source_url pg_catalog.text;
  v_deadline_kind pg_catalog.text;
  v_deadline_on pg_catalog.date;
  v_user_category pg_catalog.text;
  v_event_start_on pg_catalog.date;
  v_event_end_on pg_catalog.date;
  v_source_match_id pg_catalog.uuid;
  v_slug_match_id pg_catalog.uuid;
  v_slug_match_source pg_catalog.text;
  v_curation_id pg_catalog.uuid;
  v_target record;
  v_now pg_catalog.timestamptz := pg_catalog.now();
begin
  if exists(select 1 from machimoa_review.curation_candidates where id=p_candidate_id and source='myseoul_program') then
    perform 1 from machimoa_review.source_items s join machimoa_review.program_candidate_inputs m on m.source_item_id=s.id where m.candidate_id=p_candidate_id for update of s;
    perform machimoa_review.program_candidate_guard(p_candidate_id);
  end if;
  if v_candidate_id is null then
    raise exception 'candidate_id is required';
  end if;

  if v_reviewed_by is null
     or pg_catalog.char_length(v_reviewed_by) > 128 then
    raise exception
      'reviewed_by must contain 1 to 128 non-whitespace characters';
  end if;

  if v_review_notes is not null
     and pg_catalog.char_length(v_review_notes) > 4000 then
    raise exception 'review_notes length must not exceed 4000';
  end if;

  select
    c.review_status,
    pg_catalog.lower(pg_catalog.btrim(c.source)),
    pg_catalog.btrim(c.source_item_id),
    pg_catalog.btrim(c.source_revision_hash),
    pg_catalog.btrim(c.slug),
    nullif(pg_catalog.btrim(coalesce(c.category, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.title_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.title_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.summary_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.summary_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.content_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.content_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.source_url, '')), ''),
    c.application_deadline_kind,
    c.application_deadline_on,
    c.user_category,
    c.event_start_on,
    c.event_end_on
  into
    v_review_status,
    v_source,
    v_source_item_id,
    v_source_revision_hash,
    v_slug,
    v_category,
    v_title_ko,
    v_title_ja,
    v_summary_ko,
    v_summary_ja,
    v_content_ko,
    v_content_ja,
    v_source_url,
    v_deadline_kind,
    v_deadline_on,
    v_user_category,
    v_event_start_on,
    v_event_end_on
  from machimoa_review.curation_candidates as c
  where c.id = v_candidate_id
  for update;

  if not found then
    raise exception 'curation candidate % does not exist', v_candidate_id;
  end if;

  if v_review_status <> 'pending' then
    raise exception
      'curation candidate % is %, expected pending',
      v_candidate_id,
      v_review_status;
  end if;

  perform machimoa_review.assert_publish_allowed(v_source);

  if v_source !~ '^[a-z][a-z0-9_]{1,31}$' then
    raise exception 'candidate source has an invalid format';
  end if;

  if pg_catalog.char_length(v_source_item_id) not between 1 and 128 then
    raise exception 'candidate source_item_id is empty or too long';
  end if;

  if pg_catalog.char_length(v_slug) not between 1 and 128 then
    raise exception 'candidate slug is empty or too long';
  end if;

  if v_category is null
     or pg_catalog.char_length(v_category) > 100 then
    raise exception 'candidate category is required and must not exceed 100';
  end if;

  if v_title_ko is null
     or pg_catalog.char_length(v_title_ko) not between 1 and 300 then
    raise exception 'candidate title_ko is empty or too long';
  end if;

  if v_title_ja is null
     or pg_catalog.char_length(v_title_ja) not between 1 and 300 then
    raise exception 'candidate title_ja is empty or too long';
  end if;

  if v_summary_ko is null
     or pg_catalog.char_length(v_summary_ko) not between 1 and 1000 then
    raise exception
      'candidate summary_ko is required and must not exceed 1000';
  end if;

  if v_summary_ja is null
     or pg_catalog.char_length(v_summary_ja) not between 1 and 1000 then
    raise exception
      'candidate summary_ja is required and must not exceed 1000';
  end if;

  if v_content_ko is null
     or pg_catalog.char_length(v_content_ko) not between 1 and 200000 then
    raise exception 'candidate content_ko is empty or too long';
  end if;

  if v_content_ja is null
     or pg_catalog.char_length(v_content_ja) not between 1 and 200000 then
    raise exception 'candidate content_ja is empty or too long';
  end if;

  if v_source_url is null
     or v_source_url !~ '^https?://'
     or pg_catalog.char_length(v_source_url) > 2048 then
    raise exception
      'candidate source_url is required and must be an HTTP(S) URL';
  end if;

  if v_user_category not in ('policy', 'program', 'event', 'youth_space', 'living')
     or v_user_category is null then
    raise exception 'user_category_required';
  end if;
  if v_user_category in ('policy', 'program') then
    if v_deadline_kind is null
       or v_deadline_kind not in ('fixed', 'none', 'closed')
       or (v_deadline_kind = 'fixed' and v_deadline_on is null)
       or (v_deadline_kind in ('none', 'closed') and v_deadline_on is not null)
       or v_event_start_on is not null or v_event_end_on is not null then
      raise exception 'application_deadline_required';
    end if;
  elsif v_user_category = 'event' then
    if v_deadline_kind is not null or v_deadline_on is not null
       or v_event_start_on is null or v_event_end_on is null
       or v_event_start_on > v_event_end_on then
      raise exception 'event_period_required';
    end if;
  elsif v_deadline_kind is not null or v_deadline_on is not null
     or v_event_start_on is not null or v_event_end_on is not null then
    raise exception 'invalid_user_category_period';
  end if;

  for v_target in
    select
      c.id,
      c.source,
      c.source_item_id,
      c.slug
    from public.curations as c
    where (
      c.source = v_source
      and c.source_item_id = v_source_item_id
    )
    or c.slug = v_slug
    order by c.id
    for update
  loop
    if v_target.source = v_source
       and v_target.source_item_id = v_source_item_id then
      v_source_match_id := v_target.id;
    end if;

    if v_target.slug = v_slug then
      v_slug_match_id := v_target.id;
      v_slug_match_source := v_target.source;
    end if;
  end loop;

  if v_source_match_id is null and v_slug_match_id is null then
    insert into public.curations (
      slug,
      category,
      title,
      summary,
      content,
      title_ko,
      title_ja,
      summary_ko,
      summary_ja,
      content_ko,
      content_ja,
      source,
      source_item_id,
      source_url,
      application_deadline_kind,
      application_deadline_on,
      user_category,
      event_start_on,
      event_end_on,
      updated_at,
      is_published
    )
    values (
      v_slug,
      v_category,
      v_title_ko,
      v_summary_ko,
      v_content_ko,
      v_title_ko,
      v_title_ja,
      v_summary_ko,
      v_summary_ja,
      v_content_ko,
      v_content_ja,
      v_source,
      v_source_item_id,
      v_source_url,
      v_deadline_kind,
      v_deadline_on,
      v_user_category,
      v_event_start_on,
      v_event_end_on,
      v_now,
      true
    )
    returning id into v_curation_id;
  elsif v_source_match_id is not null
        and (
          v_slug_match_id is null
          or v_slug_match_id = v_source_match_id
        ) then
    update public.curations as c
    set
      slug = v_slug,
      category = v_category,
      title = v_title_ko,
      summary = v_summary_ko,
      content = v_content_ko,
      title_ko = v_title_ko,
      title_ja = v_title_ja,
      summary_ko = v_summary_ko,
      summary_ja = v_summary_ja,
      content_ko = v_content_ko,
      content_ja = v_content_ja,
      source = v_source,
      source_item_id = v_source_item_id,
      source_url = v_source_url,
      application_deadline_kind = v_deadline_kind,
      application_deadline_on = v_deadline_on,
      user_category = v_user_category,
      event_start_on = v_event_start_on,
      event_end_on = v_event_end_on,
      updated_at = v_now,
      is_published = true
    where c.id = v_source_match_id
    returning c.id into v_curation_id;
  elsif v_source_match_id is null and v_slug_match_id is not null then
    if v_slug_match_source is not null then
      raise exception
        'slug % belongs to a different sourced curation',
        v_slug;
    end if;

    if not v_allow_overwrite then
      raise exception
        'slug % belongs to a legacy curation; explicit overwrite approval is required',
        v_slug;
    end if;

    update public.curations as c
    set
      slug = v_slug,
      category = v_category,
      title = v_title_ko,
      summary = v_summary_ko,
      content = v_content_ko,
      title_ko = v_title_ko,
      title_ja = v_title_ja,
      summary_ko = v_summary_ko,
      summary_ja = v_summary_ja,
      content_ko = v_content_ko,
      content_ja = v_content_ja,
      source = v_source,
      source_item_id = v_source_item_id,
      source_url = v_source_url,
      application_deadline_kind = v_deadline_kind,
      application_deadline_on = v_deadline_on,
      user_category = v_user_category,
      event_start_on = v_event_start_on,
      event_end_on = v_event_end_on,
      updated_at = v_now,
      is_published = true
    where c.id = v_slug_match_id
    returning c.id into v_curation_id;
  else
    raise exception
      'candidate source and slug resolve to different public curations';
  end if;

  update machimoa_review.curation_candidates as c
  set
    review_status = 'published',
    review_notes = v_review_notes,
    reviewed_at = v_now,
    reviewed_by = v_reviewed_by,
    published_at = v_now,
    published_curation_id = v_curation_id
  where c.id = v_candidate_id;

  perform machimoa_review.write_publication_lineage(
    v_source,
    v_source_item_id,
    v_source_revision_hash,
    v_candidate_id,
    v_curation_id,
    v_slug,
    v_reviewed_by
  );

  return v_curation_id;
end
$function$;

do $acl$ declare f regprocedure;begin
 for f in select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='machimoa_review' and p.proname='myseoul_ai_check' or n.nspname='public'
 and p.proname in ('claim_myseoul_program_ai','finish_myseoul_program_ai','fail_myseoul_program_ai') loop
 execute format('alter function %s owner to postgres',f);
 execute format('revoke all on function %s from public,anon,authenticated,service_role',f);
 if (select n.nspname='public' from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.oid=f::oid) then execute format('grant execute on function %s to service_role',f);end if;
 end loop;end $acl$;

-- Preserve main admin integrations; My trash restoration remains outside this connection.
create or replace function machimoa_review.admin_trash_lock(p_id uuid,p_revision text,p_actor uuid) returns void
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;legacy text;publication record;
begin
 if p_id is null or p_actor is null or p_revision is null or p_revision!~'^[a-f0-9]{64}$' then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 select * into s from machimoa_review.source_items where id=p_id for update;
 if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 if s.source_id='myseoul_program' then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 if s.revision_hash is distinct from p_revision then raise sqlstate 'PT409' using message='trash_source_changed';end if;
 select legacy_curation_source into legacy from machimoa_review.ingest_sources where source_id=s.source_id for share;
 if s.source_id='seoul_reservation' then
   perform 1 from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
 end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed' and
   (s.source_id='seoul_reservation' or (revision_hash=p_revision and processing_stage='ai_enrichment' and (claim_lease_until is null or claim_lease_until>clock_timestamp())))) then
   raise sqlstate 'PT409' using message='trash_processing_active';end if;
 if legacy is not null then
   perform pg_advisory_xact_lock(hashtextextended(legacy||':'||s.external_key,0));
   perform 1 from machimoa_review.curation_candidates where source=legacy and source_item_id=s.external_key order by id for update;
 end if;
 -- Lock the actual public row; a historical published candidate is not visibility.
 -- NOWAIT avoids reversing the visibility publisher's candidate/curation lock order.
 begin
   for publication in
     select c.id,c.is_published from public.curations c
     where c.id in (select machimoa_review.admin_trash_publication_ids(p_id))
     order by c.id for share nowait
   loop
     if publication.is_published then
       raise sqlstate 'PT409' using message='trash_already_published';
     end if;
   end loop;
 exception when lock_not_available then
   raise sqlstate 'PT409' using message='review_conflict';
 end;
end $$;
create or replace function public.admin_review_ai_queue(p_offset integer default 0,p_limit integer default 25,p_watch uuid[] default '{}')
returns jsonb language plpgsql stable security definer set search_path='' as $fn$
declare result jsonb;
begin
 if p_offset is null or p_offset not between 0 and 100000 or p_limit is null or p_limit not between 1 and 25
 or p_watch is null or cardinality(p_watch)>100 or array_position(p_watch,null) is not null then
 raise sqlstate 'PT422' using message='review_invalid_input';end if;
 with projected as (
 select j.id as job_id,j.queued_at,
 jsonb_build_object(
 'jobId',j.id,'sourceItemId',s.id,'revision',j.revision_hash,
 'currentRevision',s.revision_hash=j.revision_hash,'status',j.status,
 'sourceName',s.source_id,'title',left(coalesce(s.min_fields->>'title',s.normalized_payload->>'plcyNm',s.normalized_payload->>'pstTtl','제목 확인 필요'),500),
 'completedAt',j.completed_at,'retryCount',j.retry_count,'nextRetryAt',j.next_retry_at,
 'leaseState',case when j.status<>'claimed' then 'none' when j.claim_lease_until is null then 'unknown'
 when j.claim_lease_until<=statement_timestamp() then 'expired' else 'active' end,
 'errorCode',case when j.error_code in ('ai_or_enqueue_failed','ai_blocked_cost_cap','ai_cost_bound_breach',
 'ai_refusal','ai_schema_error','ai_timeout','ai_network','ai_http_400','ai_http_401','ai_http_403','ai_http_404',
 'ai_http_429','ai_http_4xx','ai_http_5xx','ai_unexpected_thinking','ai_call_budget','ai_sampling_forbidden')
 then j.error_code else null end,
 'resultState',case when j.status<>'completed' then null
 when s.revision_hash<>j.revision_hash then 'source_changed'
 when c.id is null then 'missing'
 when c.review_status<>'pending' then 'processed'
 when exists(select 1 from machimoa_review.processing_jobs r where r.source_item_id=s.id and r.revision_hash=s.revision_hash
 and r.processing_stage<>'ai_enrichment' and r.status in ('queued','claimed')) then 'input_changed'
 when s.source_id in ('seoul_reservation','myseoul_program') and (m.candidate_id is null or f.source_item_id is null or m.facts_version<>f.facts_version) then 'input_changed'
 when s.source_id not in ('seoul_reservation','myseoul_program') and exists(select 1 from machimoa_review.admin_review_events e
 where e.source_item_id=s.id and e.revision_hash=j.revision_hash and e.action='save_facts' and e.occurred_at>c.created_at) then 'input_changed'
 when c.ai_status_ko is distinct from 'success' or c.ai_status_ja is distinct from 'success'
 or exists(select 1 from unnest(array[c.title_ko,c.summary_ko,c.content_ko,c.title_ja,c.summary_ja,c.content_ja]) v
 where coalesce(v,'') !~ '[^[:space:]   -   　﻿]') then 'unavailable'
 else 'ready' end) as entry
 from machimoa_review.processing_jobs j join machimoa_review.source_items s on s.id=j.source_item_id
 left join lateral (select ca.* from machimoa_review.curation_candidates ca
 where machimoa_review.canonical_source_id(ca.source)=s.source_id and ca.source_item_id=s.external_key
 and ca.source_revision_hash=j.revision_hash order by ca.created_at desc,ca.id desc limit 1) c on true
 left join machimoa_review.program_candidate_inputs m on m.candidate_id=c.id
 left join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=j.revision_hash
 where j.processing_stage='ai_enrichment' and s.source_id in ('youthcenter_policy','youthcenter_content','seoul_reservation','myseoul_program')
 and (j.id=any(p_watch) or s.revision_hash=j.revision_hash and j.status in ('queued','claimed','failed'))
 ), page as (select * from projected where entry->>'currentRevision'='true' and entry->>'status' in ('queued','claimed','failed')
 order by queued_at,job_id offset p_offset limit p_limit+1),
 visible as (select * from page order by queued_at,job_id limit p_limit)
 select jsonb_build_object('checkedAt',statement_timestamp(),
 'items',coalesce((select jsonb_agg(entry order by queued_at,job_id) from visible),'[]'::jsonb),
 'hasMore',(select count(*)>p_limit from page),
 'observed',coalesce((select jsonb_agg(coalesce(p.entry,jsonb_build_object('jobId',w.id,'status','missing')) order by w.id)
 from (select distinct unnest(p_watch) id) w left join projected p on p.job_id=w.id),'[]'::jsonb)) into result;
 return result;
end $fn$;

notify pgrst,'reload schema';
commit;
