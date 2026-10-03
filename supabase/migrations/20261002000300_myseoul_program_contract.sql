-- Local, isolated validation only. No default runners/AI/UI are connected.
begin;
do $$ begin if current_user <> 'postgres' then raise exception 'postgres_required'; end if; end $$;

alter table machimoa_review.ingest_sources drop constraint ingest_sources_connector_ck;
alter table machimoa_review.ingest_sources add constraint ingest_sources_connector_ck
 check(connector_type in ('rest','rss','cursor','public_homepage_partial'));
alter table machimoa_review.source_item_program_facts drop constraint source_item_program_facts_schema_version_check;
alter table machimoa_review.source_item_program_facts drop constraint source_item_program_facts_evaluated_profile_check;
alter table machimoa_review.source_item_program_facts add constraint program_facts_schema_profile_pair_ck check(
 (schema_version='program-scope-v1-local' and evaluated_profile='program_capital_v1_local') or
 (schema_version='myseoul-program-facts-v1-local' and evaluated_profile='myseoul-program-v1-local'));
alter table machimoa_review.ingest_runs add column run_summary jsonb
 check(run_summary is null or jsonb_typeof(run_summary)='object' and octet_length(run_summary::text)<=4000);
insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source)
 values('myseoul_program','myseoulplus','content','public_homepage_partial',false,'testing_only','myseoul_program');
insert into machimoa_review.source_sync_state(source_id) values('myseoul_program');

create function machimoa_review.myseoul_strings(v jsonb) returns boolean
language sql immutable set search_path='' as $$
 select case when jsonb_typeof(v)='array' then jsonb_array_length(v)<=200 and not exists(
 select 1 from jsonb_array_elements(v) x where jsonb_typeof(x)<>'string' or char_length(x#>>'{}')>4000
 or (x#>>'{}') ~ '<[/!A-Za-z][^>]*>') else false end
$$;

create function machimoa_review.myseoul_url(v text) returns boolean
language sql immutable set search_path='' as $$
 select coalesce(v ~ '^https://global[.]seoul[.]go[.]kr/hmpg/ecpr/prgm/prgmDetail[.]do\?cntr_no=[A-F0-9]{32}&prgrm_no=[A-F0-9]{32}&lang=ko$',false)
$$;

create function machimoa_review.myseoul_validate(f jsonb) returns void
language plpgsql set search_path='' as $$
declare k text; entry jsonb; endpoint jsonb; dt timestamptz; start_at timestamptz; end_at timestamptz;
 required text[]:=array['schema_version','revision_contract','description','official_url','public_category','issues','scope_exclusions',
 'activity_evidence','residence_scope','residence_evidence','qualification_note','target','residence','age','companion','language','conditions',
 'purpose','venue','delivery_mode','activity_region','application_actor','fees','periods','session_evidence','meeting_evidence',
 'application_methods','application_links','source_status','source_category','early_close_evidence','capacity_raw','capacity_value',
 'missing','conflicts','evidence','source_revision','parser_version'];
begin
 if f is null or jsonb_typeof(f)<>'object' or not f ?& required or
 (select count(*) from jsonb_object_keys(f))<>cardinality(required) or octet_length(f::text)>300000
 then raise exception using errcode='PT422',message='invalid_myseoul_facts';end if;
 if f->>'schema_version' is distinct from 'myseoul-program-facts-v1-local' or
 f->>'parser_version' is distinct from 'myseoul-html-v2-local' or f->>'revision_contract' is distinct from 'myseoul-semantic-v2' or
 not machimoa_review.myseoul_url(f->>'official_url') or f->>'source_revision' !~ '^[a-f0-9]{64}$' or
 f->>'public_category' not in ('program','event','unknown') or
 f->>'delivery_mode' not in ('offline','online','mixed','unknown','course_unresolved') or
 f->>'application_actor' not in ('individual','institution_only','unknown') or
 f->>'activity_region' not in ('capital','noncapital','unknown') or
 f->>'residence_scope' not in ('nationwide','includes_capital','capital','noncapital_only','unknown')
 then raise exception using errcode='PT422',message='invalid_myseoul_profile';end if;
 foreach k in array array['schema_version','revision_contract','description','official_url','public_category','qualification_note','target',
 'residence','purpose','venue','delivery_mode','activity_region','application_actor','source_revision','parser_version','residence_scope'] loop
 if jsonb_typeof(f->k)<>'string' or char_length(f->>k)>60000 or (f->>k) ~ '<[/!A-Za-z][^>]*>' then
 raise exception using errcode='PT422',message='invalid_myseoul_text';end if;end loop;
 if jsonb_typeof(f->'source_category') not in ('string','null') or char_length(f->>'source_category')>500 or
 (f->>'source_category') ~ '<[/!A-Za-z][^>]*>' or f->'capacity_value'<>'null'::jsonb then
 raise exception using errcode='PT422',message='invalid_myseoul_metadata';end if;
 foreach k in array array['activity_evidence','residence_evidence','age','companion','language','conditions','session_evidence',
 'meeting_evidence','application_methods','application_links','source_status','early_close_evidence','capacity_raw','missing','scope_exclusions'] loop
 if not machimoa_review.myseoul_strings(f->k) then raise exception using errcode='PT422',message='invalid_myseoul_array';end if;end loop;
 for entry in select value from jsonb_array_elements(f->'application_links') loop
 if (entry#>>'{}') !~ '^https://[^/@[:space:]?#]+(/[^[:space:]]*)?$' or (entry#>>'{}') ~* '(token|secret|password|api[_-]?key)=' then
 raise exception using errcode='PT422',message='invalid_application_link';end if;end loop;
 foreach k in array array['issues','fees','conflicts','evidence'] loop
 if jsonb_typeof(f->k)<>'array' or jsonb_array_length(f->k)>200 then
 raise exception using errcode='PT422',message='invalid_myseoul_structure';end if;end loop;
 for entry in select value from jsonb_array_elements(f->'issues') loop
 if jsonb_typeof(entry)<>'object' or (select count(*) from jsonb_object_keys(entry))<>3 or not entry ?& array['code','field','evidence']
 or jsonb_typeof(entry->'code') is distinct from 'string' or jsonb_typeof(entry->'field') is distinct from 'string'
 or coalesce(entry->>'code','') !~ '^[a-z_]+(:[a-z_]+)?$' or coalesce(entry->>'field','') !~ '^[a-z_]+$'
 or not machimoa_review.myseoul_strings(entry->'evidence') then raise exception using errcode='PT422',message='invalid_myseoul_issue';end if;end loop;
 if (select count(distinct value->>'code') from jsonb_array_elements(f->'issues'))<>jsonb_array_length(f->'issues') then
 raise exception using errcode='PT422',message='duplicate_myseoul_issue';end if;
 for entry in select value from jsonb_array_elements(f->'evidence') loop
 if jsonb_typeof(entry)<>'object' or not entry ?& array['field','label','value','origin'] or
 (select count(*) from jsonb_object_keys(entry))<>4 or jsonb_typeof(entry->'field') is distinct from 'string' or
 jsonb_typeof(entry->'label') is distinct from 'string' or jsonb_typeof(entry->'value') is distinct from 'string' or
 jsonb_typeof(entry->'origin') is distinct from 'string' or entry->>'origin' not in ('header','body') or
 char_length(entry->>'field')>100 or char_length(entry->>'label')>100 or char_length(entry->>'value')>4000 or
 entry->>'value' ~ '<[/!A-Za-z][^>]*>' then raise exception using errcode='PT422',message='invalid_myseoul_evidence';end if;end loop;
 for entry in select value from jsonb_array_elements(f->'conflicts') loop
 if jsonb_typeof(entry)<>'object' or not entry ?& array['field','labels','header','body'] or
 (select count(*) from jsonb_object_keys(entry))<>4 or jsonb_typeof(entry->'field') is distinct from 'string' or char_length(entry->>'field')>100 or
 not machimoa_review.myseoul_strings(entry->'labels') or not machimoa_review.myseoul_strings(entry->'header') or not machimoa_review.myseoul_strings(entry->'body') then
 raise exception using errcode='PT422',message='invalid_myseoul_conflict';end if;end loop;
 for entry in select value from jsonb_array_elements(f->'fees') loop
 if jsonb_typeof(entry)<>'object' or (select count(*) from jsonb_object_keys(entry))<>2 or not entry ?& array['component','evidence']
 or jsonb_typeof(entry->'component')<>'string' or entry->>'component' not in ('tuition','admission','materials','extra_fee') or not machimoa_review.myseoul_strings(entry->'evidence')
 or jsonb_array_length(entry->'evidence')=0 then raise exception using errcode='PT422',message='invalid_myseoul_fee';end if;end loop;
 if jsonb_typeof(f->'periods')<>'object' or (select count(*) from jsonb_object_keys(f->'periods'))<>2
 or not (f->'periods') ?& array['application','operation'] then raise exception using errcode='PT422',message='invalid_myseoul_periods';end if;
 foreach k in array array['application','operation'] loop
 if jsonb_typeof(f->'periods'->k)<>'array' or jsonb_array_length(f->'periods'->k)>50 then
 raise exception using errcode='PT422',message='invalid_myseoul_periods';end if;
 for entry in select value from jsonb_array_elements(f->'periods'->k) loop
 if jsonb_typeof(entry)<>'object' or not entry ?& array['raw','status','endpoints','origin','label'] or
 (select count(*) from jsonb_object_keys(entry))<>5 or jsonb_typeof(entry->'raw')<>'string' or char_length(entry->>'raw')>4000 or
 jsonb_typeof(entry->'status') is distinct from 'string' or entry->>'status' not in ('ok','unparsed','missing') or
 jsonb_typeof(entry->'origin') is distinct from 'string' or entry->>'origin' not in ('header','body','operator') or
 jsonb_typeof(entry->'label')<>'string' or char_length(entry->>'label')>100 or
 jsonb_typeof(entry->'endpoints')<>'array' or jsonb_array_length(entry->'endpoints')>50 or
 entry->>'status'='ok' and jsonb_array_length(entry->'endpoints') not between 1 and 2 then
 raise exception using errcode='PT422',message='invalid_myseoul_period';end if;
 for endpoint in select value from jsonb_array_elements(entry->'endpoints') loop
 if jsonb_typeof(endpoint)<>'object' or not endpoint ?& array['value','precision'] or (select count(*) from jsonb_object_keys(endpoint))<>2
 or jsonb_typeof(endpoint->'value') is distinct from 'string' or jsonb_typeof(endpoint->'precision') is distinct from 'string' or endpoint->>'precision' not in ('day','minute') or
 (endpoint->>'precision'='day' and endpoint->>'value' !~ '^\d{4}-\d{2}-\d{2}$') or
 (endpoint->>'precision'='minute' and endpoint->>'value' !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+09:00$') then
 raise exception using errcode='PT422',message='invalid_myseoul_precision';end if;
 begin dt:=(endpoint->>'value')::timestamp at time zone 'Asia/Seoul';
 exception when others then raise exception using errcode='PT422',message='invalid_myseoul_date';end;
 end loop;
 if entry->>'status'='ok' then
 start_at:=machimoa_review.myseoul_boundary(entry->'endpoints'->0,false);
 end_at:=machimoa_review.myseoul_boundary(entry->'endpoints'->(jsonb_array_length(entry->'endpoints')-1),true);
 if start_at>end_at then raise exception using errcode='PT422',message='invalid_myseoul_period_order';end if;end if;
 end loop;end loop;
end $$;

create function machimoa_review.myseoul_boundary(e jsonb, is_end boolean) returns timestamptz
language sql immutable set search_path='' as $$
 select case when e->>'precision'='day' then ((e->>'value')::date + case when is_end then 1 else 0 end)::timestamp at time zone 'Asia/Seoul'
 else (e->>'value')::timestamptz end
$$;

-- Narrow equivalents only, matching the extractor. No inferred amount totals.
create function machimoa_review.myseoul_comparison(field text,v text) returns jsonb
language plpgsql immutable set search_path='' as $$
declare m text[]; kind text;
begin
 if field='status' then
 if v ~ '^(신청|접수|모집)[[:space:]]*중$|^추가[[:space:]]*모집[[:space:]]*(중)?$' then return jsonb_build_array('status','open');end if;
 if v ~ '^(신청|접수|모집)[[:space:]]*(종료|마감)$|^예약[[:space:]]*마감$' then return jsonb_build_array('status','closed');end if;
 end if;
 if field in ('tuition','admission','materials','extra_fee') then
 if v='무료' then return jsonb_build_array('krw',0);end if;
 m:=regexp_match(v,'^([0-9]+|[0-9]{1,3}(,[0-9]{3})+)[[:space:]]*원([[:space:]]*\([[:space:]]*(수강료|입장료|재료비|부대비)[[:space:]]*\))?$');
 if m is not null then kind:=case m[4] when '수강료' then 'tuition' when '입장료' then 'admission' when '재료비' then 'materials' when '부대비' then 'extra_fee' else field end;
 if kind=field then return jsonb_build_array('krw',replace(m[1],',','')::numeric);end if;end if;end if;
 return jsonb_build_array('raw',v);
end $$;

create function machimoa_review.myseoul_evaluate(f jsonb,p_now timestamptz) returns jsonb
language plpgsql set search_path='' as $$
declare reasons text[]:=array(select value->>'code' from jsonb_array_elements(f->'issues'));
 exclusions text[]:=array(select jsonb_array_elements_text(f->'scope_exclusions')); app text:='unknown'; mode text:=f->>'delivery_mode';
 k text; p jsonb; app_period jsonb; op_period jsonb; endpoint jsonb; boundary timestamptz; decision text; quality text; scope text; status text;
begin
 perform machimoa_review.myseoul_validate(f);
 if p_now is null then raise exception using errcode='PT422',message='evaluation_time_required';end if;
 if f->>'application_actor'='institution_only' then exclusions:=array_append(exclusions,'institution_only');end if;
 if char_length(btrim(f->>'description'))<20 then reasons:=array_append(reasons,'description_missing');end if;
 if btrim(f->>'target')='' then reasons:=array_append(reasons,'target_missing');end if;
 if f->>'application_actor'='unknown' then reasons:=array_append(reasons,'application_actor_unknown');end if;
 if f->>'public_category'='unknown' then reasons:=array_append(reasons,'category_unresolved');end if;
 if mode in ('unknown','course_unresolved') then reasons:=array_append(reasons,case when mode='unknown' then 'delivery_mode_unknown' else 'course_modes_unresolved' end);end if;
 if mode in ('offline','mixed') then
 if f->>'activity_region'='noncapital' then exclusions:=array_append(exclusions,'noncapital_venue');
 elsif f->>'activity_region'<>'capital' or f->'activity_evidence'='[]'::jsonb or btrim(f->>'venue')='' then reasons:=array_append(reasons,'activity_region_unknown');end if;end if;
 if mode='online' then
 if f->>'residence_scope'='noncapital_only' then exclusions:=array_append(exclusions,'online_noncapital_only');
 elsif f->>'residence_scope' not in ('nationwide','includes_capital','capital') or f->'residence_evidence'='[]'::jsonb then reasons:=array_append(reasons,'online_residence_unknown');end if;end if;
 if f->'application_methods'='[]'::jsonb then reasons:=array_append(reasons,'application_method_missing');end if;
 if f->'fees'='[]'::jsonb or exists(select 1 from jsonb_array_elements(f->'fees') fee cross join lateral jsonb_array_elements_text(fee->'evidence') v
 where v !~ '무료|[0-9][0-9,]*[[:space:]]*원|별도[[:space:]]*(부담|납부)') then reasons:=array_append(reasons,'fee_unknown');end if;
 for k in select fee->>'component' from jsonb_array_elements(f->'fees') fee cross join lateral jsonb_array_elements_text(fee->'evidence') v
 group by fee->>'component' having count(distinct machimoa_review.myseoul_comparison(fee->>'component',v))>1 loop
 reasons:=array_append(reasons,'source_fact_conflict:'||k);end loop;
 foreach k in array array['application','operation'] loop
 if exists(select 1 from jsonb_array_elements(f->'periods'->k) v where v->>'status'<>'ok') or k='operation' and not exists(
 select 1 from jsonb_array_elements(f->'periods'->k) v where v->>'status'='ok') then reasons:=array_append(reasons,k||'_period_unknown');end if;
 if (select count(distinct v->'endpoints') from jsonb_array_elements(f->'periods'->k) v where v->>'status'='ok')>1 then reasons:=array_append(reasons,'source_fact_conflict:'||k);end if;end loop;
 if (select count(distinct machimoa_review.myseoul_comparison('status',v)) from jsonb_array_elements_text(f->'source_status') v)>1 then reasons:=array_append(reasons,'source_fact_conflict:status');end if;
 select value into app_period from jsonb_array_elements(f->'periods'->'application') where value->>'status'='ok' limit 1;
 select value into op_period from jsonb_array_elements(f->'periods'->'operation') where value->>'status'='ok' limit 1;
 status:=array_to_string(array(select jsonb_array_elements_text(f->'source_status')),E'\n');
 if status ~ '접수[[:space:]]*종료|모집[[:space:]]*종료|예약[[:space:]]*마감|접수[[:space:]]*마감|신청[[:space:]]*(마감|종료)' then app:='closed';
 elsif app_period is not null then
 endpoint:=app_period->'endpoints'->(jsonb_array_length(app_period->'endpoints')-1);
 boundary:=machimoa_review.myseoul_boundary(endpoint,true);
 app:=case when p_now<machimoa_review.myseoul_boundary(app_period->'endpoints'->0,false) then 'not_started'
 when endpoint->>'precision'='day' and p_now>=boundary or endpoint->>'precision'='minute' and p_now>boundary then 'closed' else 'open' end;
 elsif status ~ '접수[[:space:]]*중|모집[[:space:]]*중|신청[[:space:]]*중|추가[[:space:]]*모집|현장[[:space:]]*접수' then app:='open';
 else reasons:=array_append(reasons,'application_period_unknown');end if;
 if op_period is not null then endpoint:=op_period->'endpoints'->(jsonb_array_length(op_period->'endpoints')-1);
 boundary:=machimoa_review.myseoul_boundary(endpoint,true);
 if endpoint->>'precision'='day' and p_now>=boundary or endpoint->>'precision'='minute' and p_now>boundary then app:='ended';end if;end if;
 if reasons && array['source_fact_conflict:application','source_fact_conflict:operation','source_fact_conflict:status'] then app:='unknown';end if;
 if app='unknown' then reasons:=array_append(reasons,'application_state_unknown');end if;
 select coalesce(array_agg(code order by ord),'{}') into reasons from (select code,min(ord) ord from unnest(reasons) with ordinality q(code,ord) group by code) q;
 select coalesce(array_agg(code order by ord),'{}') into exclusions from (select code,min(ord) ord from unnest(exclusions) with ordinality q(code,ord) group by code) q;
 scope:=case when cardinality(exclusions)>0 then 'excluded' when reasons && array['target_missing','application_actor_unknown','delivery_mode_unknown',
 'course_modes_unresolved','activity_region_unknown','online_residence_unknown','category_unresolved','nationality_or_visa_unresolved'] then 'unknown' else 'included' end;
 quality:=case when exists(select 1 from unnest(reasons) r where r like 'source_fact_conflict:%') then 'conflict' when cardinality(reasons)>0 then 'insufficient' else 'sufficient' end;
 decision:=case when cardinality(exclusions)>0 then 'out_of_scope' when cardinality(reasons)>0 then 'review_required' when app='open' then 'in_scope' else 'not_currently_available' end;
 reasons:=exclusions||reasons;
 if app in ('closed','not_started','ended') then reasons:=array_append(reasons,case when app='ended' then 'operation_ended' else 'application_'||app end);end if;
 select coalesce(array_agg(code order by ord),'{}') into reasons from (select code,min(ord) ord from unnest(reasons) with ordinality q(code,ord) group by code) q;
 return jsonb_build_object('decision',decision,'disposition',case when cardinality(exclusions)>0 then 'non_target' when decision='in_scope' then 'target' else 'observe_only' end,
 'scope',scope,'application',app,'quality',quality,'public_category',f->>'public_category','reasons',to_jsonb(reasons),'ai_status','blocked');
end $$;

create function machimoa_review.myseoul_reason_fields(reason text) returns text[]
language sql immutable set search_path='' as $$
 select case
 when reason='description_missing' then array['description']
 when reason='target_missing' then array['target','conditions','application_actor']
 when reason='application_actor_unknown' then array['application_actor','target','conditions']
 when reason in ('delivery_mode_unknown','course_modes_unresolved','activity_region_unknown') then array['delivery_mode','activity_region','venue','activity_evidence']
 when reason='online_residence_unknown' then array['residence_scope','residence','residence_evidence']
 when reason='category_unresolved' then array['public_category','purpose']
 when reason='nationality_or_visa_unresolved' then array['qualification_note']
 when reason in ('application_period_unknown','operation_period_unknown') then array['periods','session_evidence']
 when reason='application_method_missing' then array['application_methods','application_links']
 when reason in ('fee_unknown','fee_components_unresolved') then array['fees']
 when reason='application_state_unknown' then array['source_status','periods']
 when reason='source_fact_conflict:application_method' then array['application_methods','application_links']
 when reason in ('source_fact_conflict:application','source_fact_conflict:operation') then array['periods','session_evidence']
 when reason='source_fact_conflict:target' then array['target','conditions']
 when reason='source_fact_conflict:mode' then array['delivery_mode','activity_evidence']
 when reason='source_fact_conflict:venue' then array['venue','activity_region','activity_evidence']
 when reason='source_fact_conflict:status' then array['source_status','periods']
 when reason in ('source_fact_conflict:tuition','source_fact_conflict:admission','source_fact_conflict:materials','source_fact_conflict:extra_fee') then array['fees']
 else '{}'::text[] end
$$;

create function machimoa_review.myseoul_refresh(p_id uuid,p_now timestamptz default clock_timestamp()) returns void
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
 where source_item_id=p_id and status in ('queued','failed') and (revision_hash<>s.revision_hash or processing_stage<>'content_review' or v_result->>'decision'<>'review_required');
 if v_result->>'decision'='review_required' then
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
 values(p_id,s.revision_hash,'content_review','queued',clock_timestamp(),clock_timestamp(),array(select jsonb_array_elements_text(v_result->'reasons')))
 on conflict(source_item_id,revision_hash,processing_stage) do update set reason_codes=excluded.reason_codes,status='queued',completed_at=null
 where machimoa_review.processing_jobs.status in ('queued','cancelled','failed');end if;
 -- No AI insertion, including enabled/approved sources. Worker connection is separate.
end $$;

create function public.observe_myseoul_program(p_run_id uuid,p_items jsonb,p_next_checkpoint jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare entry jsonb; r record; sid uuid; existing machimoa_review.source_item_program_facts%rowtype; outcomes jsonb:='[]';
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
 select f.* into existing from machimoa_review.source_item_program_facts f join machimoa_review.source_items s on s.id=f.source_item_id
 where s.source_id='myseoul_program' and s.external_key=entry->>'external_key' and f.revision_hash=entry->>'revision_hash';
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
 perform machimoa_review.myseoul_refresh(sid);
 outcomes:=outcomes||jsonb_build_array(jsonb_build_object('id',sid,'outcome',r.outcome,'revision',entry->>'revision_hash'));
 end loop;return outcomes;
end $$;

create function public.finish_myseoul_run(p_run_id uuid,p_summary jsonb,p_requests integer,p_batches integer) returns jsonb
language plpgsql security definer set search_path='' as $$
declare k text; v integer; state text;
begin
 if p_summary is null or jsonb_typeof(p_summary)<>'object' or not p_summary ?& array['coverage','source_complete','homepage_scope_complete','discovered','processed','omitted','stop_reason']
 or (select count(*) from jsonb_object_keys(p_summary))<>7 or p_summary->>'coverage' is distinct from 'homepage_education_only' or
 p_summary->'source_complete' is distinct from 'false'::jsonb or jsonb_typeof(p_summary->'homepage_scope_complete')<>'boolean' or
 p_summary->>'stop_reason' not in ('homepage_scope_complete','discovery_budget_limit') or
 p_requests is null or p_requests not between 1 and 21 or p_batches is null or p_batches not between 0 and 20 then
 raise exception using errcode='PT422',message='invalid_myseoul_summary';end if;
 foreach k in array array['discovered','processed','omitted'] loop
 if jsonb_typeof(p_summary->k)<>'number' or p_summary->>k !~ '^[0-9]+$' or (p_summary->>k)::numeric>10000 then
 raise exception using errcode='PT422',message='invalid_myseoul_counts';end if;end loop;
 if (p_summary->>'processed')::integer+(p_summary->>'omitted')::integer<>(p_summary->>'discovered')::integer or
 (p_summary->>'homepage_scope_complete')::boolean is distinct from ((p_summary->>'omitted')::integer=0)
 or ((p_summary->>'homepage_scope_complete')::boolean) is distinct from (p_summary->>'stop_reason'='homepage_scope_complete') then
 raise exception using errcode='PT422',message='invalid_myseoul_coverage';end if;
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and active_run_id=p_run_id and lease_owner=p_run_id and lease_expires_at>clock_timestamp() for update;
 if not found then raise exception using errcode='PT409',message='myseoul_lease_lost';end if;
 perform 1 from machimoa_review.ingest_runs where id=p_run_id and source_id='myseoul_program' and status='running';
 if not found then raise exception using errcode='PT409',message='myseoul_run_conflict';end if;
 state:=case when (p_summary->>'homepage_scope_complete')::boolean then 'complete' else 'incomplete' end;
 perform machimoa_review.finish_ingest_run(p_run_id,state,p_summary->>'stop_reason',p_requests,false,p_batches);
 update machimoa_review.ingest_runs set run_summary=p_summary where id=p_run_id;
 return jsonb_build_object('status',state,'summary',p_summary);
end $$;

create function public.admin_myseoul_program_detail(p_id uuid) returns jsonb
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
 'aiStatus','blocked','history',history);
end $$;

create function machimoa_review.myseoul_admin_lock(p_id uuid,p_revision text,p_version text,p_actor uuid) returns jsonb
language plpgsql set search_path='' as $$
declare item jsonb;
begin
 if p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$' then
 raise exception using errcode='PT422',message='invalid_myseoul_command';end if;
 perform 1 from machimoa_review.source_items where id=p_id and source_id='myseoul_program' for update;
 if not found then raise exception using errcode='PT404',message='myseoul_not_found';end if;
 perform 1 from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 perform 1 from machimoa_review.ingest_sources where source_id='myseoul_program' for share;
 item:=public.admin_myseoul_program_detail(p_id);
 if item->>'revision'<>p_revision or item->>'version'<>p_version then raise exception using errcode='PT409',message='myseoul_version_conflict';end if;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
 raise exception using errcode='PT409',message='myseoul_processing_active';end if;
 if item->>'status'<>'open' or not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='content_review' and status='queued') then
 raise exception using errcode='PT409',message='myseoul_already_processed';end if;
 return item;
end $$;

-- Keep old signatures/ACL/body behavior for every other source. My facts must
-- never reach the legacy 11-field editor. Main has moved the legacy exclusion
-- body behind its SQL trash wrapper; preserve that wrapper and guard its callee.
do $$ declare r record; definition text; guard text;begin
 for r in select p.oid,p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where (n.nspname='public' and p.proname in ('admin_review_detail','admin_review_save_facts'))
 or (n.nspname='machimoa_review' and p.proname='admin_review_exclude_before_trash') loop
 definition:=pg_get_functiondef(r.oid);
 guard:=case when r.proname='admin_review_detail' then 'p_kind=''facts'' and ' else '' end ||
 'exists(select 1 from machimoa_review.source_items where id=p_id and source_id=''myseoul_program'')';
 if definition !~ E'\nbegin\n' then raise exception 'legacy_guard_anchor_missing';end if;
 definition:=regexp_replace(definition,E'\nbegin\n',E'\nbegin\n if '||guard||
 E' then raise exception using errcode=''PT409'',message=''myseoul_specific_contract_required'';end if;\n');
 execute definition;
 end loop;
end $$;

create function public.admin_myseoul_program_save(p_id uuid,p_revision text,p_version text,p_patch jsonb,p_resolve text[],p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item jsonb; f jsonb; r text; k text; changed text[]:='{}'; result jsonb;
 issue jsonb; old_issue jsonb; same_fee boolean;
begin
 if p_patch is null or jsonb_typeof(p_patch)<>'object' or p_resolve is null or cardinality(p_resolve)>30
 or char_length(btrim(coalesce(p_note,''))) not between 1 and 4000 then raise exception using errcode='PT422',message='invalid_myseoul_command';end if;
 item:=machimoa_review.myseoul_admin_lock(p_id,p_revision,p_version,p_actor);
 for k in select jsonb_object_keys(p_patch) loop
 if not (item->'editableFields') ? k then raise exception using errcode='PT422',message='myseoul_field_read_only';end if;
 if p_patch->k is distinct from item->'facts'->k then changed:=array_append(changed,k);end if;end loop;
 if cardinality(changed)=0 then raise exception using errcode='PT422',message='myseoul_change_required';end if;
 f:=(item->'facts')||p_patch;
 foreach r in array p_resolve loop
 if r is null or not (item->'result'->'reasons') ? r or not changed && machimoa_review.myseoul_reason_fields(r) then
 raise exception using errcode='PT422',message='myseoul_reason_not_resolved';end if;
 -- A whole periods/fees replacement must not resolve an unrelated sub-issue.
 if r in ('application_period_unknown','source_fact_conflict:application') and f->'periods'->'application' is not distinct from item->'facts'->'periods'->'application' or
 r in ('operation_period_unknown','source_fact_conflict:operation') and f->'periods'->'operation' is not distinct from item->'facts'->'periods'->'operation' then
 raise exception using errcode='PT422',message='myseoul_related_change_required';end if;
 if r like 'source_fact_conflict:%' and split_part(r,':',2) in ('tuition','admission','materials','extra_fee') then
 if (select coalesce(jsonb_agg(value),'[]') from jsonb_array_elements(f->'fees') where value->>'component'=split_part(r,':',2)) is not distinct from
 (select coalesce(jsonb_agg(value),'[]') from jsonb_array_elements(item->'facts'->'fees') where value->>'component'=split_part(r,':',2)) then
 raise exception using errcode='PT422',message='myseoul_related_change_required';end if;end if;
 if r='nationality_or_visa_unresolved' and char_length(btrim(f->>'qualification_note'))<10 then
 raise exception using errcode='PT422',message='qualification_evidence_required';end if;
 f:=jsonb_set(f,'{issues}',coalesce((select jsonb_agg(value) from jsonb_array_elements(f->'issues') where value->>'code'<>r),'[]'));
 end loop;
 perform machimoa_review.myseoul_validate(f);
 result:=machimoa_review.myseoul_evaluate(f,clock_timestamp());
 foreach r in array p_resolve loop
 if result->'reasons' ? r then raise exception using errcode='PT422',message='myseoul_fact_still_missing';end if;
 -- All resolutions require recorded operator evidence; raw extraction remains.
 if r in ('category_unresolved') and char_length(btrim(f->>'purpose'))<10 or
 r in ('delivery_mode_unknown','course_modes_unresolved','activity_region_unknown','source_fact_conflict:mode','source_fact_conflict:venue') and f->'activity_evidence'='[]'::jsonb or
 r='fee_components_unresolved' and exists(select 1 from jsonb_array_elements(f->'fees') fee where fee->>'component'='extra_fee'
 and exists(select 1 from jsonb_array_elements_text(fee->'evidence') v where (v ~ '수강료' and v ~ '입장료') or (v ~ '재료비' and v ~ '입장료') or (v ~ '수강료' and v ~ '재료비'))) then
 raise exception using errcode='PT422',message='myseoul_evidence_required';end if;
 end loop;
 update machimoa_review.source_item_program_facts set facts=f,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,p_note,changed||array(select 'resolved:'||v from unnest(p_resolve) v));
 perform machimoa_review.myseoul_refresh(p_id);
 return public.admin_myseoul_program_detail(p_id);
end $$;

create function public.admin_myseoul_program_exclude(p_id uuid,p_revision text,p_version text,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
begin
 if char_length(btrim(coalesce(p_note,''))) not between 1 and 4000 then raise exception using errcode='PT422',message='invalid_myseoul_command';end if;
 perform machimoa_review.myseoul_admin_lock(p_id,p_revision,p_version,p_actor);
 update machimoa_review.source_item_program_facts set manual_excluded=true,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'exclude',p_actor,p_note,array['service_scope']);
 perform machimoa_review.myseoul_refresh(p_id);
 return public.admin_myseoul_program_detail(p_id);
end $$;

-- Common admin_review_list already discovers My content_review once; no new list.
do $$ declare r record;begin
 for r in select p.oid::regprocedure signature,n.nspname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='machimoa_review' and p.proname like 'myseoul_%' or n.nspname='public' and p.proname in
 ('observe_myseoul_program','finish_myseoul_run','admin_myseoul_program_detail','admin_myseoul_program_save','admin_myseoul_program_exclude') loop
 execute format('revoke all on function %s from public,anon,authenticated,service_role',r.signature);
 if r.nspname='public' then execute format('grant execute on function %s to service_role',r.signature);end if;
 end loop;
end $$;
commit;
