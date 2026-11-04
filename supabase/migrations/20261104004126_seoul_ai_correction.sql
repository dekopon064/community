begin;
set local lock_timeout = '5s';

-- Failed responses live outside the candidate/publication tables.
create table machimoa_review.seoul_ai_correction_drafts (
 id uuid primary key default gen_random_uuid(),
 job_id uuid not null,
 claimed_at timestamptz not null,
 output jsonb not null check (jsonb_typeof(output)='object' and octet_length(output::text)<=450000),
 stage text not null check (stage in ('summary','korean_validation','translation','japanese_validation')),
 diagnostic jsonb not null check (octet_length(diagnostic::text)<=8192),
 request_actor uuid,
 field text check (field in ('ko','ja','jaTitle')),
 before_text text,
 evidence text,
 verified_value text,
 worker text,
 requested_at timestamptz,
 started_at timestamptz,
 finished_at timestamptz,
 replacement text,
 outcome text check (outcome in ('invalid_suggestion','validation_failed','translation_missing','validated')),
 candidate_id uuid unique references machimoa_review.curation_candidates(id),
 unique (job_id,claimed_at),
 foreign key (job_id,claimed_at) references machimoa_review.seoul_ai_no_retry_attempts(job_id,claimed_at)
);
alter table machimoa_review.seoul_ai_correction_drafts enable row level security;
revoke all on machimoa_review.seoul_ai_correction_drafts from public,anon,authenticated,service_role;

create function public.fail_seoul_ai_with_draft(
 p_job_id uuid,p_revision text,p_claimed_at timestamptz,p_lease_until timestamptz,
 p_worker_id text,p_attempt text,p_error_code text,p_draft jsonb,p_stage text,p_diagnostic jsonb
) returns text language plpgsql security definer set search_path='' as $$
declare status text;
begin
 if p_error_code is distinct from 'ai_schema_error' or jsonb_typeof(p_draft) is distinct from 'object'
 or not (p_draft ?| array['ko','ja','jaTitle']) or p_draft - array['ko','koFacts','ja','jaTitle','model'] <> '{}'::jsonb then
  raise sqlstate 'PT422' using message='invalid_failure_draft';
 end if;
 status:=public.fail_seoul_ai_no_retry(p_job_id,p_revision,p_claimed_at,p_lease_until,p_worker_id,p_attempt,p_error_code);
 insert into machimoa_review.seoul_ai_correction_drafts(job_id,claimed_at,output,stage,diagnostic)
 values(p_job_id,p_claimed_at,p_draft,p_stage,p_diagnostic)
 on conflict(job_id,claimed_at) do nothing;
 if not exists(select 1 from machimoa_review.seoul_ai_correction_drafts d where d.job_id=p_job_id and d.claimed_at=p_claimed_at
 and d.output=p_draft and d.stage=p_stage and d.diagnostic=p_diagnostic) then
  raise sqlstate 'PT409' using message='failure_draft_conflict';
 end if;
 return status;
end $$;

-- Lock the source first, following the existing worker and admin lock order.
-- The old terminal attempt remains intact even when a repaired candidate is created.
create function machimoa_review.lock_seoul_ai_correction(p_id uuid)
returns machimoa_review.seoul_ai_correction_drafts language plpgsql security definer set search_path='' as $$
declare d machimoa_review.seoul_ai_correction_drafts; a machimoa_review.seoul_ai_no_retry_attempts;
 s machimoa_review.source_items; j machimoa_review.processing_jobs; live jsonb;
begin
 select * into d from machimoa_review.seoul_ai_correction_drafts where id=p_id;
 if not found then raise sqlstate 'PT404' using message='correction_draft_missing'; end if;
 select * into a from machimoa_review.seoul_ai_no_retry_attempts where job_id=d.job_id and claimed_at=d.claimed_at;
 select * into s from machimoa_review.source_items where id=a.source_item_id for update;
 select * into d from machimoa_review.seoul_ai_correction_drafts where id=p_id for update;
 if a.input_context ? 'classificationVersion' then
  if not coalesce(machimoa_review.classification_ready(s.id),false) then
   raise sqlstate 'PT409' using message='correction_classification_not_ready';
  end if;
 else
  perform machimoa_review.program_ai_check(s.id,a.revision_hash,(a.input_context->>'factsVersion')::bigint);
 end if;
 select * into j from machimoa_review.processing_jobs where id=d.job_id for update;
 perform pg_advisory_xact_lock(hashtextextended('seoul_reservation:'||s.external_key,0));
 live:=machimoa_review.seoul_ai_no_retry_snapshot(j.id);
 if s.source_id is distinct from 'seoul_reservation' or j.status is distinct from 'failed'
 or j.completed_at is distinct from a.closed_at or j.error_code is distinct from a.error_code
 or a.input_snapshot->'facts' is distinct from live->'facts'
 or a.input_snapshot->'filters' is distinct from live->'filters'
 or a.input_snapshot->'classification' is distinct from live->'classification'
 or s.revision_hash is distinct from a.revision_hash
 or (a.input_context ? 'classificationVersion') is distinct from
    (live->'classification' is distinct from 'null'::jsonb)
 or (a.input_context ? 'classificationVersion' and
     a.input_snapshot->'nativeSnapshot' is distinct from live->'nativeSnapshot')
 or exists(select 1 from machimoa_review.processing_jobs other where other.source_item_id=s.id and other.status='claimed')
 or exists(select 1 from machimoa_review.curation_candidates c
    where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key) then
  raise sqlstate 'PT409' using message='correction_input_changed';
 end if;
 return d;
end $$;

create function public.admin_seoul_ai_draft(p_job uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('id',d.id,'stage',d.stage,'diagnostic',d.diagnostic,
 'output',d.output - array['koFacts','model'],'outcome',d.outcome,
 'requested',d.requested_at is not null,'started',d.started_at is not null,
 'repairable',d.output ? 'koFacts' and d.output ? 'model',
 'candidateId',d.candidate_id,'field',d.field,'before',d.before_text,'after',d.replacement,
 'evidence',d.evidence,'sourceUrl',coalesce(a.input_context->>'sourceUrl',a.input_context->'facts'->>'official_url'))
 from machimoa_review.seoul_ai_correction_drafts d join machimoa_review.seoul_ai_no_retry_attempts a
   on a.job_id=d.job_id and a.claimed_at=d.claimed_at
 where d.job_id=p_job order by d.claimed_at desc limit 1
$$;

create function public.admin_request_seoul_ai_correction(
 p_id uuid,p_job uuid,p_actor uuid,p_field text,p_before text,p_evidence text,p_value text
) returns jsonb language plpgsql security definer set search_path='' as $$
declare d machimoa_review.seoul_ai_correction_drafts; a machimoa_review.seoul_ai_no_retry_attempts; original text;
begin
 if p_actor is null or p_field is null or p_field not in ('ko','ja','jaTitle')
 or coalesce(char_length(p_before),0) not between 1 and 500
 or coalesce(char_length(p_evidence),0) not between 1 and 500
 or coalesce(char_length(p_value),0) not between 1 and 100
 or p_before ~ E'[\r\n]' or p_before<>btrim(p_before)
 or p_value<>btrim(p_value) or strpos(p_evidence,p_value)=0 then
  raise sqlstate 'PT422' using message='invalid_correction_scope';
 end if;
 d:=machimoa_review.lock_seoul_ai_correction(p_id);
 if d.job_id is distinct from p_job or d.requested_at is not null then
  raise sqlstate 'PT409' using message='correction_already_requested';
 end if;
 select * into a from machimoa_review.seoul_ai_no_retry_attempts where job_id=d.job_id and claimed_at=d.claimed_at;
 original:=d.output->>p_field;
 if (p_field='ko') is distinct from (d.stage in ('summary','korean_validation'))
 or original is null or not (d.output ? 'koFacts') or strpos(original,p_before)=0
 or strpos(substr(original,strpos(original,p_before)+1),p_before)>0
 or (strpos(coalesce(a.input_context->'nativeConfirmedFacts'->'programFacts'->>'description',
                a.input_context->'facts'->>'description',''),p_evidence)=0
     and strpos(coalesce(a.input_context->>'title',''),p_evidence)=0) then
  raise sqlstate 'PT422' using message='correction_evidence_or_excerpt_missing';
 end if;
 update machimoa_review.seoul_ai_correction_drafts set request_actor=p_actor,field=p_field,before_text=p_before,
 evidence=p_evidence,verified_value=p_value,requested_at=clock_timestamp() where id=p_id;
 return public.admin_seoul_ai_draft(p_job);
end $$;

create function public.claim_seoul_ai_correction(p_id uuid,p_worker text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare d machimoa_review.seoul_ai_correction_drafts; a machimoa_review.seoul_ai_no_retry_attempts;
begin
 if coalesce(char_length(p_worker),0) not between 1 and 128 then raise sqlstate 'PT422'; end if;
 d:=machimoa_review.lock_seoul_ai_correction(p_id);
 if d.requested_at is null or d.started_at is not null then return null; end if;
 select * into a from machimoa_review.seoul_ai_no_retry_attempts where job_id=d.job_id and claimed_at=d.claimed_at;
 update machimoa_review.seoul_ai_correction_drafts set worker=p_worker,started_at=clock_timestamp() where id=p_id;
 return jsonb_build_object('id',d.id,'worker',p_worker,'field',d.field,'before',d.before_text,'value',d.verified_value,
 'evidence',d.evidence,'output',d.output,'title',a.input_context->>'title','facts',a.input_context->'facts',
 'classification',case when a.input_context ? 'classificationVersion' then
   jsonb_build_object('source','seoul_reservation','facts',a.input_context->'facts','filters',a.input_context->'filters',
   'nativeConfirmedFacts',a.input_context->'nativeConfirmedFacts') end);
end $$;

create function public.complete_seoul_ai_correction(
 p_id uuid,p_worker text,p_after text,p_candidate jsonb,p_result text
) returns text language plpgsql security definer set search_path='' as $$
declare d machimoa_review.seoul_ai_correction_drafts; a machimoa_review.seoul_ai_no_retry_attempts;
 c jsonb; result jsonb; cid uuid; patched jsonb;
begin
 d:=machimoa_review.lock_seoul_ai_correction(p_id);
 if d.worker is distinct from p_worker or d.started_at is null or d.finished_at is not null then
  raise sqlstate 'PT409' using message='correction_attempt_changed';
 end if;
 if p_result is null or p_result not in ('validated','validation_failed','translation_missing','invalid_suggestion')
 or (p_result='validated') is distinct from (p_candidate is not null)
 or (p_result='invalid_suggestion') is distinct from (p_after is null)
 or (p_after is not null and (char_length(p_after) not between 1 and 500 or p_after ~ E'[\r\n]'
 or p_after=d.before_text or strpos(p_after,d.verified_value)=0)) then
  raise sqlstate 'PT422' using message='invalid_correction_result';
 end if;
 if p_result='validated' then
  select * into a from machimoa_review.seoul_ai_no_retry_attempts where job_id=d.job_id and claimed_at=d.claimed_at;
  patched:=jsonb_set(d.output,array[d.field],to_jsonb(replace(d.output->>d.field,d.before_text,p_after)));
  -- The trusted worker reassembles and validates the Korean body. The candidate
  -- must carry exactly the Japanese response with at most the requested edit.
  if btrim(p_candidate->>'titleJa') is distinct from btrim(patched->>'jaTitle')
  or btrim(p_candidate->>'contentJa') is distinct from btrim(patched->>'ja') then
   raise sqlstate 'PT422' using message='correction_candidate_scope';
  end if;
  update machimoa_review.processing_jobs set status='queued',completed_at=null where id=d.job_id;
  if a.input_context ? 'classificationVersion' then
   c:=public.claim_seoul_reclassified_ai_no_retry(a.source_item_id,a.revision_hash,
     (a.input_context->>'classificationVersion')::bigint,p_worker,600);
  else
   c:=public.claim_seoul_program_ai_no_retry(a.source_item_id,a.revision_hash,p_worker,600)->0;
  end if;
  if (c->>'jobId')::uuid is distinct from d.job_id then raise sqlstate 'PT409' using message='correction_claim_changed'; end if;
  if a.input_context ? 'classificationVersion' then
   result:=public.finish_reclassified_content_ai(d.job_id,a.revision_hash,(c->>'classificationVersion')::bigint,
    (c->>'claimedAt')::timestamptz,(c->>'leaseUntil')::timestamptz,p_worker,p_candidate);
  else
   result:=public.finish_seoul_program_ai(d.job_id,a.revision_hash,(c->>'factsVersion')::bigint,
    (c->>'claimedAt')::timestamptz,(c->>'leaseUntil')::timestamptz,p_worker,p_candidate);
  end if;
  if result->>'outcome' is distinct from 'inserted' then raise sqlstate 'PT409' using message='correction_candidate_exists'; end if;
  cid:=(result->>'candidateId')::uuid;
  if cid is null then raise sqlstate 'PT409' using message='correction_candidate_missing'; end if;
 end if;
 update machimoa_review.seoul_ai_correction_drafts set finished_at=clock_timestamp(),
  outcome=p_result,replacement=p_after,candidate_id=cid where id=p_id;
 return p_result;
end $$;

create function public.admin_seoul_ai_correction_evidence(p_candidate uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('field',d.field,'before',d.before_text,'after',d.replacement,'evidence',d.evidence,
 'sourceUrl',coalesce(a.input_context->>'sourceUrl',a.input_context->'facts'->>'official_url'))
 from machimoa_review.seoul_ai_correction_drafts d join machimoa_review.seoul_ai_no_retry_attempts a
 on a.job_id=d.job_id and a.claimed_at=d.claimed_at where d.candidate_id=p_candidate and d.outcome='validated'
$$;

revoke all on function machimoa_review.lock_seoul_ai_correction(uuid) from public,anon,authenticated,service_role;
revoke all on function public.fail_seoul_ai_with_draft(uuid,text,timestamptz,timestamptz,text,text,text,jsonb,text,jsonb),
 public.admin_seoul_ai_draft(uuid),public.admin_request_seoul_ai_correction(uuid,uuid,uuid,text,text,text,text),
 public.claim_seoul_ai_correction(uuid,text),public.complete_seoul_ai_correction(uuid,text,text,jsonb,text),
 public.admin_seoul_ai_correction_evidence(uuid) from public,anon,authenticated,service_role;
grant execute on function public.fail_seoul_ai_with_draft(uuid,text,timestamptz,timestamptz,text,text,text,jsonb,text,jsonb),
 public.admin_seoul_ai_draft(uuid),public.admin_request_seoul_ai_correction(uuid,uuid,uuid,text,text,text,text),
 public.claim_seoul_ai_correction(uuid,text),public.complete_seoul_ai_correction(uuid,text,text,jsonb,text),
 public.admin_seoul_ai_correction_evidence(uuid) to service_role;
commit;

