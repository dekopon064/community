begin;
set local lock_timeout = '5s';

-- Private retention belongs to the exact terminal attempt, never the public curation.
alter table machimoa_review.seoul_ai_no_retry_attempts
  add column private_output jsonb check (octet_length(private_output::text) <= 450000);

create function public.fail_program_ai_with_draft(
  p_source text, p_job_id uuid, p_revision text, p_claimed_at timestamptz, p_lease_until timestamptz,
  p_worker_id text, p_attempt text, p_error_code text, p_failure_detail jsonb, p_draft jsonb
) returns text language plpgsql security definer set search_path='' as $$
declare previous machimoa_review.seoul_ai_no_retry_attempts; outcome text;
begin
  if p_source is distinct from 'myseoul_program' or jsonb_typeof(p_draft) is distinct from 'object'
    or octet_length(p_draft::text)>450000 or p_draft - array['ko','ja','jaTitle'] <> '{}'::jsonb
    or p_draft = '{}'::jsonb or exists(select 1 from jsonb_each(p_draft) f where jsonb_typeof(f.value)<>'string'
      or length(trim(f.value#>>'{}')) not between 1 and (case when f.key='jaTitle' then 300 else 200000 end)) then
    raise sqlstate 'PT422' using message='invalid_failure_draft';
  end if;
  perform 1 from machimoa_review.source_items s join machimoa_review.processing_jobs j on j.source_item_id=s.id
    where j.id=p_job_id and s.source_id=p_source for update of s;
  select * into previous from machimoa_review.seoul_ai_no_retry_attempts where job_id=p_job_id and claimed_at=p_claimed_at;
  if previous.closed_at is not null and previous.private_output is distinct from p_draft then
    raise sqlstate 'PT409' using message='failure_draft_conflict';
  end if;
  outcome := machimoa_review.fail_program_with_detail(p_source,p_job_id,p_revision,p_claimed_at,p_lease_until,
    p_worker_id,p_attempt,p_error_code,p_failure_detail);
  update machimoa_review.seoul_ai_no_retry_attempts set private_output=p_draft
    where job_id=p_job_id and claimed_at=p_claimed_at and attempt=p_attempt and closed_at is not null;
  if not found or outcome is distinct from 'failed' then raise sqlstate 'PT409' using message='failure_draft_conflict'; end if;
  return outcome;
end $$;

create function public.finish_program_ai_candidate_review(
  p_source text, p_job_id uuid, p_revision text, p_claimed_at timestamptz, p_lease_until timestamptz,
  p_worker_id text, p_facts_version bigint, p_output jsonb, p_review jsonb
) returns jsonb language plpgsql security definer set search_path='' as $$
declare result jsonb; cid uuid;
begin
  if jsonb_typeof(p_review) is distinct from 'object' or octet_length(p_review::text)>180000
    or jsonb_typeof(p_review->'source') is distinct from 'string' or length(p_review->>'source')>32000
    or jsonb_typeof(p_review->'issues') is distinct from 'array' or jsonb_array_length(p_review->'issues') not between 1 and 32 then
    raise sqlstate 'PT422' using message='invalid_candidate_review';
  end if;
  -- Register each new source with its own guarded finish RPC.
  if p_source is distinct from 'myseoul_program' then raise sqlstate 'PT422' using message='unsupported_source'; end if;
  result := public.finish_myseoul_program_ai(p_job_id,p_revision,p_facts_version,p_claimed_at,p_lease_until,p_worker_id,p_output);
  cid := (result->>'candidateId')::uuid;
  if result->>'outcome'='inserted' then
    insert into machimoa_review.seoul_ai_candidate_reviews(candidate_id, review) values(cid,p_review);
  elsif result->>'outcome' is distinct from 'duplicate' or not exists (
    select 1 from machimoa_review.seoul_ai_candidate_reviews where candidate_id=cid and review=p_review
  ) then raise sqlstate 'PT409' using message='candidate_review_conflict'; end if;
  return result;
end $$;

-- If no excerpt could be located, the original output hash distinguishes a
-- freshly generated finding from one that predates an operator edit.
create or replace function public.admin_seoul_ai_candidate_review(p_candidate uuid) returns jsonb
language sql stable security definer set search_path='' as $$
  select jsonb_build_object('review', (
    select case when c.source='seoul_reservation' then r.review else r.review ||
      jsonb_build_object('matchesSavedOutput', i.output_hash=encode(sha256(convert_to(jsonb_build_object(
        'titleKo',c.title_ko,'titleJa',c.title_ja,'summaryKo',c.summary_ko,'summaryJa',c.summary_ja,
        'contentKo',c.content_ko,'contentJa',c.content_ja,'aiModel',c.ai_model)::text,'UTF8')),'hex')) end
    from machimoa_review.seoul_ai_candidate_reviews r join machimoa_review.curation_candidates c on c.id=r.candidate_id
    left join machimoa_review.program_candidate_inputs i on i.candidate_id=c.id where c.id=p_candidate
  ), 'evidence',public.admin_seoul_ai_correction_evidence(p_candidate))
$$;

create function public.admin_program_ai_private_draft(p_job uuid) returns jsonb
language sql stable security definer set search_path='' as $$
  select jsonb_build_object('id',a.job_id,'stage',a.failure_detail->>'stage','diagnostic',a.failure_detail,'output',a.private_output)
  from machimoa_review.seoul_ai_no_retry_attempts a join machimoa_review.processing_jobs j
    on j.id=a.job_id and j.source_item_id=a.source_item_id and j.revision_hash=a.revision_hash
    and j.status='failed' and j.completed_at=a.closed_at and j.error_code=a.error_code
  where j.id=p_job and a.private_output is not null
$$;

revoke all on function public.fail_program_ai_with_draft(text,uuid,text,timestamptz,timestamptz,text,text,text,jsonb,jsonb),
  public.finish_program_ai_candidate_review(text,uuid,text,timestamptz,timestamptz,text,bigint,jsonb,jsonb),
  public.admin_program_ai_private_draft(uuid) from public,anon,authenticated,service_role;
grant execute on function public.fail_program_ai_with_draft(text,uuid,text,timestamptz,timestamptz,text,text,text,jsonb,jsonb),
  public.finish_program_ai_candidate_review(text,uuid,text,timestamptz,timestamptz,text,bigint,jsonb,jsonb),
  public.admin_program_ai_private_draft(uuid) to service_role;
notify pgrst, 'reload schema';
commit;
