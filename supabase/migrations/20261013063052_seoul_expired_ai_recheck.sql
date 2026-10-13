begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
-- Explicit expired-attempt cancellation only. No backfill, automatic retry,
-- source activation, candidate creation or confirmed facts mutation.
do $$ declare p record; begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 select * into p from pg_proc where oid=to_regprocedure('public.admin_ai_queue_review_detail(uuid)');
 if p.oid is null or pg_get_userbyid(p.proowner)<>'postgres'
 or p.proconfig is distinct from array['search_path=""']::text[] or not p.prosecdef
 or p.proacl::text is distinct from '{postgres=X/postgres,service_role=X/postgres}'
 or encode(sha256(convert_to(replace(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'1956f15aacd2e0b6fe22512464ca825bc4b50dc3bc09074f944fdda4d58c54e0'
 then raise exception 'seoul_expired_predecessor_changed';end if;
 select * into p from pg_proc where oid=to_regprocedure('machimoa_review.ai_recheck_command(uuid,text,text,uuid,text,uuid,text)');
 if p.oid is null or pg_get_userbyid(p.proowner)<>'postgres'
 or p.proconfig is distinct from array['search_path=""']::text[] or not p.prosecdef
 or p.proacl::text is distinct from '{postgres=X/postgres}'
 or encode(sha256(convert_to(replace(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'dfa6b478db572131071c6593b5ca6387b493da61258237d7d1f18af13d1f2d0e'
 then raise exception 'seoul_expired_recheck_changed';end if;
end $$;

create table machimoa_review.seoul_expired_ai_receipts (
 request_id uuid primary key,
 job_id uuid not null references machimoa_review.processing_jobs(id),
 actor uuid not null, input jsonb not null, prior_attempt jsonb not null,
 response jsonb not null, created_at timestamptz not null default clock_timestamp()
);
alter table machimoa_review.seoul_expired_ai_receipts enable row level security;
revoke all on machimoa_review.seoul_expired_ai_receipts from public,anon,authenticated,service_role;

-- Opaque request fence: includes the exact worker/claim/lease, current review
-- version and immutable claim input. No claim identity is sent to public prose.
create function machimoa_review.seoul_expired_ai_attempt(p_job_id uuid,p_review_version text) returns text
language plpgsql stable security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 f machimoa_review.content_filter_claim_inputs%rowtype;c machimoa_review.review_classification_claims%rowtype;
begin
 select * into j from machimoa_review.processing_jobs where id=p_job_id and processing_stage='ai_enrichment';
 select * into s from machimoa_review.source_items where id=j.source_item_id and source_id='seoul_reservation';
 if s.id is null or s.revision_hash is distinct from j.revision_hash or s.disposition='non_target'
 or j.status<>'claimed' or j.claimed_at is null or j.claim_lease_until is null or j.claimed_by is null
 or j.claim_lease_until>statement_timestamp() or j.completed_at is not null
 or j.retry_count<>0 or j.next_retry_at is not null
 or machimoa_review.ai_recheck_pending(s.id,s.revision_hash)
 or exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and id<>j.id and status='claimed')
 or exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
 or exists(select 1 from machimoa_review.program_candidate_inputs where job_id=j.id)
 or exists(select 1 from machimoa_review.review_classification_candidates where job_id=j.id)
 or not exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id and enabled and permission_status in ('approved_noncommercial','approved_commercial'))
 then return null;end if;
 select * into f from machimoa_review.content_filter_claim_inputs where job_id=j.id and claimed_at=j.claimed_at;
 if f.job_id is null or f.source_item_id is distinct from s.id or f.revision_hash is distinct from s.revision_hash
 or f.worker_id is distinct from j.claimed_by or f.lease_until is distinct from j.claim_lease_until then return null;end if;
 select * into c from machimoa_review.review_classification_claims where job_id=j.id and claimed_at=j.claimed_at;
 if exists(select 1 from machimoa_review.review_classifications where source_item_id=s.id and revision_hash=s.revision_hash)
 and (c.job_id is null or c.source_item_id is distinct from s.id or c.revision_hash is distinct from s.revision_hash
 or c.worker_id is distinct from j.claimed_by or c.lease_until is distinct from j.claim_lease_until) then return null;end if;
 return encode(sha256(convert_to(jsonb_build_array('seoul-expired-attempt-v1',to_jsonb(j),p_review_version,to_jsonb(f),to_jsonb(c))::text,'UTF8')),'hex');
end $$;
revoke all on function machimoa_review.seoul_expired_ai_attempt(uuid,text) from public,anon,authenticated,service_role;

alter function public.admin_ai_queue_review_detail(uuid) rename to seoul_expired_base_detail;
alter function public.seoul_expired_base_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.seoul_expired_base_detail(uuid) from public,anon,authenticated,service_role;
create function public.admin_ai_queue_review_detail(p_job_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare d jsonb;a text;begin
 d:=machimoa_review.seoul_expired_base_detail(p_job_id);
 a:=machimoa_review.seoul_expired_ai_attempt(p_job_id,d->>'version');
 return d||jsonb_build_object('expiredCancellation',case when a is not null then jsonb_build_object('attempt',a) else null end);
end $$;
revoke all on function public.admin_ai_queue_review_detail(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_ai_queue_review_detail(uuid) to service_role;

create function public.admin_seoul_ai_cancel_expired(p_job_id uuid,p_revision text,p_version text,p_attempt text,p_request_id uuid,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 r machimoa_review.seoul_expired_ai_receipts%rowtype;d jsonb;outcome jsonb;legacy text;input jsonb;prior jsonb;
begin
 p_note:=btrim(coalesce(p_note,''));
 if p_job_id is null or p_request_id is null or p_actor is null
 or p_revision is null or p_revision !~ '^[a-f0-9]{64}$'
 or p_version is null or p_version !~ '^[a-f0-9]{64}$'
 or p_attempt is null or p_attempt !~ '^[a-f0-9]{64}$' or char_length(p_note)>1000
 then raise sqlstate 'PT422' using message='invalid_expired_cancel';end if;
 -- Shared receipt lock then the existing source -> facts -> jobs -> permission
 -- -> canonical candidate order. Completion/claimers lock the same source.
 perform pg_advisory_xact_lock(hashtextextended('ai-recheck-request:'||p_request_id::text,0));
 select * into j from machimoa_review.processing_jobs where id=p_job_id and processing_stage='ai_enrichment';
 select * into s from machimoa_review.source_items where id=j.source_item_id and source_id='seoul_reservation' for update;
 if s.id is null then raise sqlstate 'PT404' using message='expired_job_not_found';end if;
 perform 1 from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=s.id order by revision_hash,processing_stage for update;
 select * into j from machimoa_review.processing_jobs where id=p_job_id;
 select legacy_curation_source into legacy from machimoa_review.ingest_sources where source_id=s.source_id for share;
 if legacy is null then raise sqlstate 'PT409' using message='source_contract_missing';end if;
 perform pg_advisory_xact_lock(hashtextextended(legacy||':'||s.external_key,0));
 perform 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key for update;
 input:=jsonb_build_array(p_revision,p_version,p_attempt,p_note);
 select * into r from machimoa_review.seoul_expired_ai_receipts where request_id=p_request_id;
 if found then
  if r.job_id is distinct from p_job_id or r.actor is distinct from p_actor or r.input is distinct from input
  then raise sqlstate 'PT409' using message='request_id_conflict';end if;
  d:=public.admin_ai_queue_review_detail(p_job_id);
  if d->>'version' is distinct from r.response->>'version' or j.status<>'cancelled'
  then raise sqlstate 'PT409' using message='expired_cancel_superseded';end if;
  return r.response;
 end if;
 if exists(select 1 from machimoa_review.ai_recheck_receipts where request_id=p_request_id)
 or exists(select 1 from machimoa_review.ai_rechecks where id=p_request_id)
 then raise sqlstate 'PT409' using message='request_id_conflict';end if;
 d:=public.admin_ai_queue_review_detail(p_job_id);
 if s.revision_hash is distinct from p_revision or j.revision_hash is distinct from p_revision
 or d->>'version' is distinct from p_version
 or d->'expiredCancellation'->>'attempt' is distinct from p_attempt
 then raise sqlstate 'PT409' using message='expired_cancel_conflict';end if;
 prior:=to_jsonb(j);
 -- Reuse the deliberate hold and source-specific fact editor. No queued
 -- intermediate state; cancellation + fact-review opening are atomic.
 insert into machimoa_review.ai_rechecks(id,job_id,source_item_id,revision_hash,actor,note)
 values(p_request_id,j.id,s.id,p_revision,p_actor,p_note);
 update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp(),
 claimed_at=null,claimed_by=null,claim_lease_until=null where id=j.id;
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
 values(s.id,p_revision,'content_review','queued',clock_timestamp(),clock_timestamp(),array['ai_recheck_requested'])
 on conflict(source_item_id,revision_hash,processing_stage) do update set status='queued',completed_at=null,
 reason_codes=(case when machimoa_review.processing_jobs.status='queued' then machimoa_review.processing_jobs.reason_codes else '{}'::text[] end)||array['ai_recheck_requested'];
 outcome:=public.admin_ai_queue_review_detail(p_job_id);
 if outcome->>'status'<>'cancelled' or outcome->>'recheckPending'<>'true'
 or not (outcome->'review'->'editableFields') ? 'description'
 then raise sqlstate 'PT409' using message='expired_recheck_unavailable';end if;
 insert into machimoa_review.seoul_expired_ai_receipts(request_id,job_id,actor,input,prior_attempt,response)
 values(p_request_id,j.id,p_actor,input,prior,outcome);
 return outcome;
end $$;
revoke all on function public.admin_seoul_ai_cancel_expired(uuid,text,text,text,uuid,text,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_seoul_ai_cancel_expired(uuid,text,text,text,uuid,text,uuid) to service_role;
commit;
