begin;
set local lock_timeout='5s';

alter table machimoa_review.seoul_ai_no_retry_attempts add column response_hold jsonb;

-- Terminal for scheduling, separately identifiable as an uncertain response for review.
-- Use the existing no-retry closure for ownership, lease, candidate and version checks.
create function public.hold_program_ai_response(p_source text,p_job_id uuid,p_revision text,
 p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_attempt text,p_evidence jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare closed timestamptz; prior jsonb; stored jsonb; result text;
begin
 if (jsonb_typeof(p_evidence)='object'
     and p_evidence ?& array['stage','code','completedSeen']
     and p_evidence-array['stage','code','completedSeen']='{}'::jsonb
     and p_evidence->>'stage' in ('summary','translation','correction')
     and ((p_evidence->>'code'='stream_missing_completed' and p_evidence->'completedSeen'='false'::jsonb)
       or (p_evidence->>'code'='invalid_terminal_output_item' and jsonb_typeof(p_evidence->'completedSeen')='boolean')
       or (p_evidence->>'code' in ('invalid_completed_output','conflicting_terminal_output','duplicate_completed_event')
           and p_evidence->'completedSeen'='true'::jsonb))) is not true then
   raise sqlstate 'PT422' using message='invalid_response_hold';
 end if;
 perform 1 from machimoa_review.source_items s join machimoa_review.processing_jobs j on j.source_item_id=s.id
 where j.id=p_job_id and s.source_id=p_source for update of s;
 select closed_at,response_hold into closed,prior from machimoa_review.seoul_ai_no_retry_attempts
 where job_id=p_job_id and claimed_at=p_claimed_at;
 if closed is not null and prior is distinct from p_evidence then
   raise sqlstate 'PT409' using message='response_hold_conflict';
 end if;
 result:=machimoa_review.fail_program_no_retry(p_source,p_job_id,p_revision,p_claimed_at,
   p_lease_until,p_worker_id,p_attempt,'ai_or_enqueue_failed');
 if result is distinct from 'failed' then raise sqlstate 'PT409' using message='response_hold_conflict'; end if;
 if closed is null then
   update machimoa_review.seoul_ai_no_retry_attempts set response_hold=p_evidence
   where job_id=p_job_id and claimed_at=p_claimed_at and attempt=p_attempt and closed_at is not null
     and response_hold is null returning response_hold into stored;
 else
   stored:=prior;
 end if;
 if stored is distinct from p_evidence then raise sqlstate 'PT409' using message='response_hold_conflict'; end if;
 return jsonb_build_object('outcome','held','jobId',p_job_id,'revision',p_revision,'attempt',p_attempt,'evidence',stored);
end $$;
revoke all on function public.hold_program_ai_response(text,uuid,text,timestamptz,timestamptz,text,text,jsonb)
 from public,anon,authenticated,service_role;
grant execute on function public.hold_program_ai_response(text,uuid,text,timestamptz,timestamptz,text,text,jsonb) to service_role;

-- Keep the existing queue membership, ordering and recheck path. Annotate only the
-- exact closed attempt, so an older hold cannot label a later attempt on the job.
do $$ declare d text; marker text:='''errorCode'',case when j.error_code in'; begin
 d:=pg_get_functiondef('machimoa_review.ai_recheck_base_queue(integer,integer,uuid[])'::regprocedure);
 if cardinality(string_to_array(d,marker))<>2 then raise exception 'response_hold_queue_contract_changed'; end if;
 execute replace(d,marker,'''errorCode'',case when j.status=''failed'' and exists (
   select 1 from machimoa_review.seoul_ai_no_retry_attempts a where a.job_id=j.id
   and a.revision_hash=j.revision_hash and a.closed_at=j.completed_at and a.response_hold is not null)
   then ''ai_response_held'' when j.error_code in');
end $$;
commit;
