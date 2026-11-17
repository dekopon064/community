begin;

alter table machimoa_review.seoul_ai_no_retry_attempts add column failure_detail jsonb;

-- Only structured parser data can accompany a confirmed failure receipt.
create function machimoa_review.valid_program_failure_detail(d jsonb) returns boolean
language plpgsql immutable set search_path='' as $$
declare k text; v jsonb;
begin
 if jsonb_typeof(d) is distinct from 'object' or octet_length(d::text)>4096
 or not d ?& array['stage','code','rule','reason']
 or d - array['stage','code','rule','reason','expected','actual','location'] <> '{}'::jsonb
 or d->>'stage' not in ('claim','generation','summary','korean_validation','translation','japanese_validation','correction','candidate_completion','failure_termination','unknown')
 or d->>'rule' not in ('summary_result','translation_result','summary_payload','translation_payload','summary_facts','required_text_field','required_numeric_facts','one_line_summary','body_section','reviewed_section','announcement_date_time','session_number','session_order','session_date_time','session_activity','schedule_date','schedule_year','dated_schedule_weekday','dated_schedule_clock','reviewed_period','schedule_duration_minutes','schedule_dates','schedule_years','schedule_weekdays','schedule_times','schedule_counts','participant_quantity','reviewed_fee','assembled_fee','region_glossary','translation_currency','table_header','table_row','table_rows','table','plain_text','markdown','clock','calendar_date','calendar_weekday','cell_date_time','period_date_time','fee_role','weekly_schedule_cell','unknown')
 or d->>'reason' not in ('mismatch','missing','unsupported','missing_or_mismatched','added','duplicate','duplicate_or_out_of_order','outside_operation_period','missing_or_invalid','invalid_shape','missing_or_empty','out_of_range','unexpected_yen','unexpected_fields','invalid_object','missing_field','invalid_text','invalid_body','empty_or_too_long','unsupported_markup','unknown')
 or jsonb_typeof(d->'stage')<>'string' or jsonb_typeof(d->'code')<>'string'
 or jsonb_typeof(d->'rule')<>'string' or jsonb_typeof(d->'reason')<>'string' then return false;end if;
 foreach k in array array['expected','actual'] loop
  if d ? k and (length((d->k)::text)>1024 or (d->k)::text !~ '^([][0-9., -]|null|true|false|"(date|time|people|families|age|count|minimum|maximum|under|over|approximately|-?[0-9]{1,10}([.][0-9]{1,6})?)")+$') then return false;end if;
 end loop;
 if d ? 'location' then
  if jsonb_typeof(d->'location')<>'object' then return false;end if;
  for k,v in select * from jsonb_each(d->'location') loop
   if k in ('table','row','column','line','item') and jsonb_typeof(v)='number' and v::text ~ '^[0-9]{1,6}$' then continue; end if;
   if k='field' and v#>>'{}' in ('content_ko','title_ja','content_ja','title','body','facts','facts.audience','facts.geo_age_income','facts.amount_period_deadline','facts.how_to_apply','one_line_summary') then continue;end if;
   if k='period_role' and v#>>'{}' in ('application','operation','meeting','deadline') then continue;end if;
   return false;
  end loop;
 end if;
 return true;
end $$;
revoke all on function machimoa_review.valid_program_failure_detail(jsonb) from public,anon,authenticated,service_role;

create function machimoa_review.fail_program_with_detail(p_source text,p_job_id uuid,p_revision text,p_claimed_at timestamptz,
 p_lease_until timestamptz,p_worker_id text,p_attempt text,p_error_code text,p_failure_detail jsonb) returns text
language plpgsql set search_path='' as $$
declare outcome text;
begin
 if not machimoa_review.valid_program_failure_detail(p_failure_detail)
 or p_failure_detail->>'code' is distinct from p_error_code then
  raise sqlstate 'PT422' using message='invalid_failure_detail';end if;
 -- Serialize legacy and detailed closures in the existing source-first lock order.
 perform 1 from machimoa_review.source_items s join machimoa_review.processing_jobs j on j.source_item_id=s.id
 where j.id=p_job_id and s.source_id=p_source for update of s;
 if exists(select 1 from machimoa_review.seoul_ai_no_retry_attempts where job_id=p_job_id
  and claimed_at=p_claimed_at and closed_at is not null and failure_detail is distinct from p_failure_detail)
 then raise sqlstate 'PT409' using message='failure_detail_conflict';end if;
 outcome:=machimoa_review.fail_program_no_retry(p_source,p_job_id,p_revision,p_claimed_at,p_lease_until,p_worker_id,p_attempt,p_error_code);
 update machimoa_review.seoul_ai_no_retry_attempts set failure_detail=p_failure_detail
 where job_id=p_job_id and claimed_at=p_claimed_at and attempt=p_attempt and closed_at is not null and failure_detail is null;
 if outcome<>'failed' then raise sqlstate 'PT409' using message='failure_detail_conflict';end if;
 return outcome;
end $$;
revoke all on function machimoa_review.fail_program_with_detail(text,uuid,text,timestamptz,timestamptz,text,text,text,jsonb) from public,anon,authenticated,service_role;

-- Keep the deployed seven-argument endpoint available to existing workers.
create function public.fail_myseoul_ai_no_retry(p_job_id uuid,p_revision text,p_claimed_at timestamptz,p_lease_until timestamptz,
 p_worker_id text,p_attempt text,p_error_code text,p_failure_detail jsonb) returns text
language sql security definer set search_path='' as $$
 select machimoa_review.fail_program_with_detail('myseoul_program',p_job_id,p_revision,p_claimed_at,p_lease_until,p_worker_id,p_attempt,p_error_code,p_failure_detail)
$$;
revoke all on function public.fail_myseoul_ai_no_retry(uuid,text,timestamptz,timestamptz,text,text,text,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.fail_myseoul_ai_no_retry(uuid,text,timestamptz,timestamptz,text,text,text,jsonb) to service_role;

alter function public.admin_ai_queue_review_detail(uuid) rename to program_diagnostic_base_detail;
alter function public.program_diagnostic_base_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.program_diagnostic_base_detail(uuid) from public,anon,authenticated,service_role;
create function public.admin_ai_queue_review_detail(p_job_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare d jsonb; detail jsonb;
begin
 d:=machimoa_review.program_diagnostic_base_detail(p_job_id);
 select a.failure_detail into detail from machimoa_review.seoul_ai_no_retry_attempts a
 join machimoa_review.processing_jobs j on j.id=a.job_id and j.completed_at=a.closed_at and j.status='failed' and j.error_code=a.error_code
 where j.id=p_job_id and a.source_item_id=(d->>'sourceItemId')::uuid and a.revision_hash=d->>'revision'
 and a.input_context->>'source'=d->>'sourceName' and a.failure_detail is not null;
 return case when detail is null then d else d||jsonb_build_object('failureDetail',detail) end;
end $$;
revoke all on function public.admin_ai_queue_review_detail(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_ai_queue_review_detail(uuid) to service_role;
commit;
