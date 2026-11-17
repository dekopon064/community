-- Synthetic item prepared by test_program_terminal_failure_sql.py.
begin;
select set_config('test.source_id', :'source_id', true);
select set_config('test.job_id', (select id::text from machimoa_review.processing_jobs
  where source_item_id=:'source_id'::uuid and processing_stage='ai_enrichment'), true);
select set_config('test.queue_version', public.admin_ai_queue_review_detail(current_setting('test.job_id')::uuid)->>'version', true);
savepoint fresh_queue;
set local role service_role;
do $test$
declare
  job uuid := current_setting('test.job_id')::uuid;
  d jsonb := public.admin_ai_queue_review_detail(job);
begin
  assert d->>'canExclude'='true' and d->>'canRecheck'='true';
  assert public.admin_ai_queue_exclude(job,d->>'revision',d->>'version',gen_random_uuid(),
    'period_ended',gen_random_uuid())->>'status'='cancelled';
  assert exists(select from jsonb_array_elements(public.admin_review_trash(0,25)->'items') e where e->>'sourceItemId'=d->>'sourceItemId' and e->>'note'='기간·신청 종료');
  assert public.claim_myseoul_program_ai_no_retry((d->>'sourceItemId')::uuid,d->>'revision','synthetic-worker',600)='[]'::jsonb;
end $test$;
rollback to fresh_queue;
set local role service_role;
do $test$
declare
  sid uuid := current_setting('test.source_id')::uuid;
  actor uuid := '00000000-0000-4000-8000-000000000001';
  request uuid := gen_random_uuid();
  initial jsonb := public.admin_myseoul_program_detail(sid);
  rev text := initial->>'revision';
  claim jsonb;
  job uuid;
  detail jsonb;
  retry jsonb;
  outcome jsonb;
  entry jsonb;
  restored jsonb;
begin
  claim := public.claim_myseoul_program_ai(sid,rev,'synthetic-trash-worker',600)->0;
  job := (claim->>'jobId')::uuid;
  detail := public.admin_ai_queue_review_detail(job);
  assert detail->>'status'='claimed' and detail->>'canExclude'='false';
  begin
    perform public.admin_ai_queue_exclude(job,rev,current_setting('test.queue_version'),request,'service_not_suitable',actor);
    raise exception 'stale queue screen cancelled the worker';
  exception when sqlstate 'PT409' then null;
  end;
  begin
    perform public.admin_ai_queue_exclude(job,rev,detail->>'version',request,'service_not_suitable',actor);
    raise exception 'claimed job moved';
  exception when sqlstate 'PT409' then null;
  end;
  perform public.fail_myseoul_program_ai(job,(claim->>'claimedAt')::timestamptz,
    (claim->>'leaseUntil')::timestamptz,'synthetic-trash-worker','ai_schema_error');
  retry := public.admin_ai_queue_review_detail(job);
  assert retry->>'status'='queued' and retry->>'canExclude'='true' and retry->>'canRecheck'='false';
  begin
    perform public.admin_ai_queue_exclude(job,rev,detail->>'version',request,'service_not_suitable',actor);
    raise exception 'stale version accepted';
  exception when sqlstate 'PT409' then null;
  end;
  begin
    perform public.admin_ai_queue_exclude(job,rev,retry->>'version',request,'online_application_ended',actor);
    raise exception 'retired reason accepted';
  exception when sqlstate 'PT422' then null;
  end;
  outcome := public.admin_ai_queue_exclude(job,rev,retry->>'version',request,'period_ended',actor);
  assert outcome->>'status'='cancelled' and outcome->>'canExclude'='false';
  assert public.admin_ai_queue_exclude(job,rev,retry->>'version',request,'period_ended',actor)=outcome;
  assert (outcome->'review'->'facts')=(initial->'facts');
  assert exists(select from jsonb_array_elements(outcome->'review'->'history') h where h->>'action'='exclude'
    and h->>'note'='기간·신청 종료');
  begin
    perform public.admin_ai_queue_exclude(job,rev,retry->>'version',request,'region_not_suitable',actor);
    raise exception 'different reason reused a receipt';
  exception when sqlstate 'PT409' then null;
  end;
  assert public.claim_myseoul_program_ai_no_retry(sid,rev,'synthetic-next-worker',600)='[]'::jsonb;
  select e into strict entry from jsonb_array_elements(public.admin_review_trash(0,25)->'items') e
    where e->>'sourceItemId'=sid::text;
  assert entry->>'reasonCode'='period_ended' and entry->>'note'='기간·신청 종료' and entry->>'canRestore'='true';
  begin
    perform public.admin_review_restore((entry->>'id')::uuid,rev,repeat('0',64),actor,gen_random_uuid());
    raise exception 'stale restore accepted';
  exception when sqlstate 'PT409' then null;
  end;
  restored := public.admin_review_restore((entry->>'id')::uuid,rev,entry->>'version',actor,gen_random_uuid())->'item';
  assert restored->'facts'=initial->'facts' and restored->'filterInfo'->'data'=initial->'filterInfo'->'data';
  assert (select count(*) from jsonb_array_elements(restored->'history') e where e->>'action'='exclude')=1;
  assert (select count(*) from jsonb_array_elements(restored->'history') e where e->>'action'='restore')=1;
end $test$;
reset role;
do $test$
begin
  assert exists(select from machimoa_review.admin_exclusion_episodes e,
    lateral jsonb_array_elements(e.prior_jobs) j where e.source_item_id=current_setting('test.source_id')::uuid
    and e.reason_code='period_ended' and e.note='기간·신청 종료'
    and e.restored_at is not null and j->>'status'='queued' and j->>'retry_count'='1'
    and j->>'error_code'='ai_schema_error' and j->>'claimed_at' is not null);
end $test$;
rollback;
