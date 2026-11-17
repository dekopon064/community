begin;
-- One attempt receipt per claim. Existing Seoul receipts and draft references stay valid.

create function machimoa_review.program_no_retry_snapshot(p_job_id uuid,p_source text) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('job',to_jsonb(j),'source',to_jsonb(s),
 'facts',(select to_jsonb(f) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id and f.revision_hash=j.revision_hash),
 'filters',(select to_jsonb(f) from machimoa_review.source_item_content_filters f where f.source_item_id=s.id and f.revision_hash=j.revision_hash),
 'classification',(select to_jsonb(c) from machimoa_review.review_classifications c where c.source_item_id=s.id and c.revision_hash=j.revision_hash),
 'nativeSnapshot',machimoa_review.classification_native(s.id),
 'filterClaim',(select to_jsonb(f) from machimoa_review.content_filter_claim_inputs f where f.job_id=j.id and f.claimed_at=j.claimed_at),
 'classificationClaim',(select to_jsonb(c) from machimoa_review.review_classification_claims c where c.job_id=j.id and c.claimed_at=j.claimed_at))
 from machimoa_review.processing_jobs j join machimoa_review.source_items s on s.id=j.source_item_id
 where j.id=p_job_id and j.processing_stage='ai_enrichment' and s.source_id=p_source
$$;

revoke all on function machimoa_review.program_no_retry_snapshot(uuid,text) from public,anon,authenticated,service_role;

create function machimoa_review.record_program_no_retry(p_context jsonb,p_source text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;snapshot jsonb;attempt text;begin
 select * into j from machimoa_review.processing_jobs where id=(p_context->>'jobId')::uuid for update;
 if j.status is distinct from 'claimed' or j.claimed_by is distinct from p_context->>'workerId'
 or j.claimed_at is distinct from (p_context->>'claimedAt')::timestamptz
 or j.claim_lease_until is distinct from (p_context->>'leaseUntil')::timestamptz
 or j.claim_lease_until<=clock_timestamp() or p_context->>'source' is distinct from p_source
 then raise sqlstate 'PT409' using message='no_retry_claim_conflict';end if;
 snapshot:=machimoa_review.program_no_retry_snapshot(j.id,p_source);
 if snapshot is null or snapshot->'filterClaim'='null'::jsonb
 then raise sqlstate 'PT409' using message='no_retry_snapshot_missing';end if;
 attempt:=encode(sha256(convert_to(jsonb_build_array('program-ai-no-retry-v1',p_source,p_context,snapshot)::text,'UTF8')),'hex');
 insert into machimoa_review.seoul_ai_no_retry_attempts(job_id,claimed_at,lease_until,worker_id,source_item_id,revision_hash,attempt,input_context,input_snapshot)
 values(j.id,j.claimed_at,j.claim_lease_until,j.claimed_by,j.source_item_id,j.revision_hash,attempt,p_context,snapshot);
 return p_context||jsonb_build_object('failurePolicy',jsonb_build_object('policy','no_retry','attempt',attempt));
end $$;

revoke all on function machimoa_review.record_program_no_retry(jsonb,text) from public,anon,authenticated,service_role;

create function machimoa_review.fail_program_no_retry(p_source text,p_job_id uuid,p_revision text,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_attempt text,p_error_code text) returns text
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 a machimoa_review.seoul_ai_no_retry_attempts%rowtype;legacy text;closed timestamptz;begin
 if p_job_id is null or p_claimed_at is null or p_lease_until is null or p_worker_id is null
 or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_attempt is null or p_attempt !~ '^[a-f0-9]{64}$'
 or p_error_code is null or p_error_code not in ('ai_schema_error','ai_blocked_cost_cap','ai_cost_bound_breach',
 'ai_or_enqueue_failed','ai_http_429','ai_http_404','ai_http_5xx','ai_http_4xx','ai_unexpected_thinking',
 'ai_refusal','ai_http_400','ai_http_401','ai_http_403','ai_call_budget','ai_sampling_forbidden')
 then raise sqlstate 'PT422' using message='no_retry_invalid';end if;
 -- Same source -> facts -> jobs -> permission -> candidate lock order as the
 -- existing recheck/cancellation path; all checks after taking those locks.
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs pj on pj.source_item_id=si.id
 where pj.id=p_job_id and si.source_id=p_source for update of si;
 if s.id is null then raise sqlstate 'PT409' using message='no_retry_attempt_conflict';end if;
 perform 1 from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=s.id order by revision_hash,processing_stage for update;
 select * into j from machimoa_review.processing_jobs where id=p_job_id;
 select legacy_curation_source into legacy from machimoa_review.ingest_sources where source_id=s.source_id
 and enabled and permission_status in ('approved_noncommercial','approved_commercial') for share;
 if legacy is null then raise sqlstate 'PT409' using message='no_retry_attempt_conflict';end if;
 perform pg_advisory_xact_lock(hashtextextended(legacy||':'||s.external_key,0));
 perform 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key for update;
 select * into a from machimoa_review.seoul_ai_no_retry_attempts where job_id=p_job_id and claimed_at=p_claimed_at for update;
 if a.job_id is null or a.input_context->>'source' is distinct from p_source or a.source_item_id is distinct from s.id or a.revision_hash is distinct from p_revision
 or a.lease_until is distinct from p_lease_until or a.worker_id is distinct from p_worker_id or a.attempt is distinct from p_attempt
 or s.revision_hash is distinct from p_revision or j.revision_hash is distinct from p_revision
 then raise sqlstate 'PT409' using message='no_retry_attempt_conflict';end if;
 if a.closed_at is not null then
  if a.error_code is distinct from p_error_code or j.status<>'failed' or j.completed_at is distinct from a.closed_at
  or j.claimed_at is not null or j.claimed_by is not null or j.claim_lease_until is not null
  then raise sqlstate 'PT409' using message='no_retry_attempt_superseded';end if;
  return 'failed';
 end if;
 if j.status<>'claimed' or j.completed_at is not null or j.claimed_at is distinct from p_claimed_at
 or j.claimed_by is distinct from p_worker_id or j.claim_lease_until is distinct from p_lease_until
 or j.claim_lease_until<=clock_timestamp() or machimoa_review.ai_recheck_pending(s.id,p_revision)
 or machimoa_review.program_no_retry_snapshot(j.id,p_source) is distinct from a.input_snapshot
 or exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
 or exists(select 1 from machimoa_review.program_candidate_inputs where job_id=j.id)
 or exists(select 1 from machimoa_review.review_classification_candidates where job_id=j.id)
 then raise sqlstate 'PT409' using message='no_retry_attempt_conflict';end if;
 closed:=clock_timestamp();
 -- retry_count counts retry registrations; one terminal failure adds none.
 -- The immutable input_snapshot retains the old worker/claim/lease and versions.
 update machimoa_review.processing_jobs set status='failed',error_code=p_error_code,completed_at=closed,
 claimed_at=null,claimed_by=null,claim_lease_until=null,next_retry_at=null where id=j.id;
 update machimoa_review.seoul_ai_no_retry_attempts set closed_at=closed,error_code=p_error_code
 where job_id=j.id and claimed_at=p_claimed_at;
 return 'failed';
end $$;

revoke all on function machimoa_review.fail_program_no_retry(text,uuid,text,timestamptz,timestamptz,text,text,text) from public,anon,authenticated,service_role;

create or replace function machimoa_review.seoul_ai_no_retry_snapshot(p_job_id uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select machimoa_review.program_no_retry_snapshot(p_job_id,'seoul_reservation')
$$;
revoke all on function machimoa_review.seoul_ai_no_retry_snapshot(uuid) from public,anon,authenticated,service_role;

create or replace function machimoa_review.seoul_ai_no_retry_record(p_context jsonb) returns jsonb
language sql security definer set search_path='' as $$
 select machimoa_review.record_program_no_retry(p_context,'seoul_reservation')
$$;
revoke all on function machimoa_review.seoul_ai_no_retry_record(jsonb) from public,anon,authenticated,service_role;

create or replace function public.fail_seoul_ai_no_retry(p_job_id uuid,p_revision text,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_attempt text,p_error_code text) returns text
language sql security definer set search_path='' as $$
 select machimoa_review.fail_program_no_retry('seoul_reservation',p_job_id,p_revision,p_claimed_at,p_lease_until,p_worker_id,p_attempt,p_error_code)
$$;
revoke all on function public.fail_seoul_ai_no_retry(uuid,text,timestamptz,timestamptz,text,text,text) from public,anon,authenticated,service_role;
grant execute on function public.fail_seoul_ai_no_retry(uuid,text,timestamptz,timestamptz,text,text,text) to service_role;

create function public.fail_myseoul_ai_no_retry(p_job_id uuid,p_revision text,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_attempt text,p_error_code text) returns text
language sql security definer set search_path='' as $$
 select machimoa_review.fail_program_no_retry('myseoul_program',p_job_id,p_revision,p_claimed_at,p_lease_until,p_worker_id,p_attempt,p_error_code)
$$;
revoke all on function public.fail_myseoul_ai_no_retry(uuid,text,timestamptz,timestamptz,text,text,text) from public,anon,authenticated,service_role;
grant execute on function public.fail_myseoul_ai_no_retry(uuid,text,timestamptz,timestamptz,text,text,text) to service_role;

create function public.claim_myseoul_program_ai_no_retry(p_source_item_id uuid,p_revision text,p_worker_id text,p_lease_seconds integer) returns jsonb
language plpgsql security definer set search_path='' as $$
declare result jsonb;begin
 result:=public.claim_myseoul_program_ai(p_source_item_id,p_revision,p_worker_id,p_lease_seconds);
 if jsonb_array_length(result)=0 then return result;end if;
 if jsonb_array_length(result)<>1 then raise sqlstate 'PT409' using message='no_retry_claim_conflict';end if;
 return jsonb_build_array(machimoa_review.record_program_no_retry(result->0,'myseoul_program'));
end $$;

revoke all on function public.claim_myseoul_program_ai_no_retry(uuid,text,text,integer) from public,anon,authenticated,service_role;
grant execute on function public.claim_myseoul_program_ai_no_retry(uuid,text,text,integer) to service_role;

alter function public.fail_myseoul_program_ai(uuid,timestamptz,timestamptz,text,text) rename to myseoul_no_retry_base_fail;
alter function public.myseoul_no_retry_base_fail(uuid,timestamptz,timestamptz,text,text) set schema machimoa_review;
revoke all on function machimoa_review.myseoul_no_retry_base_fail(uuid,timestamptz,timestamptz,text,text) from public,anon,authenticated,service_role;
create function public.fail_myseoul_program_ai(p_job_id uuid,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_error_code text) returns text
language plpgsql security definer set search_path='' as $$
begin
 perform 1 from machimoa_review.source_items s join machimoa_review.processing_jobs j on j.source_item_id=s.id
 where j.id=p_job_id for update of s;
 if exists(select 1 from machimoa_review.seoul_ai_no_retry_attempts where job_id=p_job_id and claimed_at=p_claimed_at)
 then raise sqlstate 'PT409' using message='no_retry_policy_required';end if;
 return machimoa_review.myseoul_no_retry_base_fail(p_job_id,p_claimed_at,p_lease_until,p_worker_id,p_error_code);
end $$;
revoke all on function public.fail_myseoul_program_ai(uuid,timestamptz,timestamptz,text,text) from public,anon,authenticated,service_role;
grant execute on function public.fail_myseoul_program_ai(uuid,timestamptz,timestamptz,text,text) to service_role;

-- Preserve the currently installed detail implementation (including later
-- operator actions); only add recheck eligibility for new terminal receipts.
alter function public.admin_ai_queue_review_detail(uuid) rename to program_terminal_base_detail;
alter function public.program_terminal_base_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.program_terminal_base_detail(uuid) from public,anon,authenticated,service_role;
create function public.admin_ai_queue_review_detail(p_job_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare d jsonb;j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;begin
 d:=machimoa_review.program_terminal_base_detail(p_job_id);
 select * into j from machimoa_review.processing_jobs where id=p_job_id;
 select * into s from machimoa_review.source_items where id=j.source_item_id;
 if s.source_id<>'seoul_reservation' and j.status='failed' and j.revision_hash=s.revision_hash
 and j.claimed_at is null and j.claimed_by is null and j.claim_lease_until is null
 and j.next_retry_at is null and s.disposition<>'non_target'
 and exists(select 1 from machimoa_review.seoul_ai_no_retry_attempts a where a.job_id=j.id
  and a.input_context->>'source'=s.source_id and a.revision_hash=j.revision_hash and a.closed_at=j.completed_at and a.error_code=j.error_code
  and (a.input_snapshot->'job'->>'retry_count')::integer=j.retry_count)
 and exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id and enabled and permission_status in ('approved_noncommercial','approved_commercial'))
 and not machimoa_review.ai_recheck_pending(s.id,s.revision_hash)
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 and not exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
 then d:=d||jsonb_build_object('canRecheck',true);end if;
 return d;
end $$;
revoke all on function public.admin_ai_queue_review_detail(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_ai_queue_review_detail(uuid) to service_role;

commit;
