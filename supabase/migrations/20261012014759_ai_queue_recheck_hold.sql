begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- No backfill, source activation, AI execution or existing content/candidate edit.
-- Hashes are LF-normalized local predecessor definitions; fail closed on drift.
do $$ declare r record;f record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values
 ('public.admin_program_detail(uuid)','f3aaf8f65e10ff2e6e4d18cfc951ab809a84e38ec26b0bb7bc9cad2ec0407157',true,true),
 ('public.admin_myseoul_program_detail(uuid)','349b4d67fc6da33709f637009af5ff0c03eb0bf46f618bfc7e0b5de27ea2b2d3',true,true),
 ('public.admin_review_ai_queue(integer,integer,uuid[])','31ce45e7ddb9b03708d0348b0b6f1f7a173d3ca853b6f93ba828ee578cae156d',true,true),
 ('public.admin_review_classification_detail(uuid)','b4377d950f68fc9874d4fd78219ff07fa2b78325401fda6c5cd3baffb021d9bc',true,true),
 ('public.admin_review_detail(text,uuid)','37d63a28c3158bafd314ba65e4786a3a2b4d27303e0b079b064a735b36615e82',true,true),
 ('public.claim_myseoul_program_ai(uuid,text,text,integer)','d5612c3c6a95ff46ca4e88d62cd01200069424ea3f77fdfa0e2cb67715de0579',true,true),
 ('public.claim_seoul_program_ai(uuid,text,text,integer)','53cd304349a05def296b196f1eafee5ec8ef39395447ea56dc976969a2fef925',true,true),
 ('public.claim_reclassified_content_ai(uuid,text,bigint,text,integer)','ce54aa3ed8653e51fbc1b22a662c85594fcbb2e02f717ba8f4ab0fd43712dd90',true,true),
 ('machimoa_review.program_refresh(uuid,timestamp with time zone)','9697e76aafc204d340564567d60447846bda05faff28512b580e242aff7d8c28',true,false),
 ('machimoa_review.myseoul_refresh(uuid,timestamp with time zone)','7ba8661546d6d4d951ca213a8ccee0e97c3c9a83b035cf5e7b38534721d2b4e8',false,false),
 ('machimoa_review.apply_source_item_evaluation(uuid,text,text,text[],jsonb)','3f5acfcde11e8d6fdf7de9a4e3b5ba67f1dc37f357e7dad1be4d76b3da0917e7',true,false)
 ) x(signature,hash,definer,service) loop
  select * into f from pg_proc where oid=to_regprocedure(r.signature);
  if f.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(f.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash
   or pg_get_userbyid(f.proowner)<>'postgres' or f.proconfig is distinct from array['search_path=""']::text[] or f.prosecdef is distinct from r.definer
   or f.proacl::text is distinct from (case when r.service then '{postgres=X/postgres,service_role=X/postgres}' else '{postgres=X/postgres}' end)
  then raise exception 'ai_recheck_predecessor_changed: %',r.signature;end if;
 end loop;
end $$;

create table machimoa_review.ai_rechecks (
 id uuid primary key, job_id uuid not null references machimoa_review.processing_jobs(id),
 source_item_id uuid not null references machimoa_review.source_items(id),
 revision_hash text not null check(revision_hash ~ '^[a-f0-9]{64}$'),
 actor uuid not null, note text not null check(char_length(note) between 1 and 1000),
 created_at timestamptz not null default clock_timestamp(), completed_at timestamptz,
 check(completed_at is null or completed_at>=created_at)
);
create unique index ai_rechecks_one_pending on machimoa_review.ai_rechecks(source_item_id,revision_hash) where completed_at is null;
create table machimoa_review.ai_recheck_receipts (
 request_id uuid primary key, job_id uuid not null references machimoa_review.processing_jobs(id),
 action text not null check(action in ('request_recheck','complete_recheck')),
 revision text not null, expected_version text not null, actor uuid not null,
 note text not null check(char_length(btrim(note)) between 1 and 1000), response jsonb not null,
 created_at timestamptz not null default clock_timestamp()
);
create index ai_rechecks_pending_job on machimoa_review.ai_rechecks(job_id) where completed_at is null;
alter table machimoa_review.ai_rechecks enable row level security;
alter table machimoa_review.ai_recheck_receipts enable row level security;
revoke all on machimoa_review.ai_rechecks,machimoa_review.ai_recheck_receipts from public,anon,authenticated,service_role;

create function machimoa_review.ai_recheck_pending(p_id uuid,p_revision text) returns boolean
language sql stable security definer set search_path='' as $$
 select exists(select 1 from machimoa_review.ai_rechecks where source_item_id=p_id and revision_hash=p_revision and completed_at is null)
$$;

-- A refresh may persist facts/filters but cannot release a deliberate hold.
-- A concurrent claimant either wins before the request (which then conflicts),
-- or sees cancelled/not-queued state. Any attempt to claim while held is rejected.
create function machimoa_review.ai_recheck_job_guard() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if machimoa_review.ai_recheck_pending(new.source_item_id,new.revision_hash) then
  if new.status='claimed' then raise sqlstate 'PT409' using message='ai_recheck_pending';end if;
  if new.processing_stage='ai_enrichment' and new.status='queued' then
   new.status:='cancelled';new.completed_at:=clock_timestamp();
  elsif new.processing_stage='content_review' and new.status in ('queued','completed','cancelled')
   and exists(select 1 from machimoa_review.source_items where id=new.source_item_id and disposition<>'non_target') then
   new.status:='queued';new.completed_at:=null;
   new.reason_codes:=array(select distinct r from unnest(coalesce(new.reason_codes,'{}')||array['ai_recheck_requested']) r order by r);
  end if;
 end if;
 return new;
end $$;
create trigger ai_recheck_job_guard before insert or update on machimoa_review.processing_jobs
 for each row execute function machimoa_review.ai_recheck_job_guard();

-- Existing source-specific DTOs, values, editable fields and validators remain
-- authoritative. The hold only makes the review visible/open; it does not invent
-- completion or broaden what an existing fact-save RPC is allowed to change.
alter function public.admin_program_detail(uuid) rename to ai_recheck_base_program_detail;
alter function public.ai_recheck_base_program_detail(uuid) set schema machimoa_review;
alter function public.admin_myseoul_program_detail(uuid) rename to ai_recheck_base_myseoul_detail;
alter function public.ai_recheck_base_myseoul_detail(uuid) set schema machimoa_review;
create function public.admin_program_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare d jsonb;begin
 d:=machimoa_review.ai_recheck_base_program_detail(p_id);
 if d->>'status'<>'excluded' and machimoa_review.ai_recheck_pending(p_id,d->>'revision') then
  d:=d||jsonb_build_object('status','open','result',(d->'result')||jsonb_build_object('reasons',coalesce(d->'result'->'reasons','[]')||jsonb_build_array('ai_recheck_requested')));
 end if;return d;
end $$;
create function public.admin_myseoul_program_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare d jsonb;begin
 d:=machimoa_review.ai_recheck_base_myseoul_detail(p_id);
 if d->>'status'<>'excluded' and machimoa_review.ai_recheck_pending(p_id,d->>'revision') then
  d:=d||jsonb_build_object('status','open','result',(d->'result')||jsonb_build_object('reasons',coalesce(d->'result'->'reasons','[]')||jsonb_build_array('ai_recheck_requested')));
 end if;return d;
end $$;

create function public.admin_ai_queue_review_detail(p_job_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 d jsonb;h jsonb;permission jsonb;classification jsonb;ready boolean;
begin
 select * into j from machimoa_review.processing_jobs where id=p_job_id and processing_stage='ai_enrichment';
 if not found then raise sqlstate 'PT404' using message='ai_job_not_found';end if;
 select * into s from machimoa_review.source_items where id=j.source_item_id;
 if s.revision_hash is distinct from j.revision_hash then raise sqlstate 'PT409' using message='source_revision_conflict';end if;
 if s.source_id='seoul_reservation' then d:=public.admin_program_detail(s.id);
 elsif s.source_id='myseoul_program' then d:=public.admin_myseoul_program_detail(s.id);
 elsif s.source_id in ('youthcenter_policy','youthcenter_content') then d:=public.admin_review_detail('facts',s.id);
 else raise sqlstate 'PT409' using message='unsupported_source';end if;
 classification:=public.admin_review_classification_detail(s.id);
 if classification->>'active'<>'true' then classification:=null;end if;
 select to_jsonb(r) into h from machimoa_review.ai_rechecks r where r.job_id=j.id and r.completed_at is null;
 select jsonb_build_object('enabled',enabled,'permission',permission_status,'legacy',legacy_curation_source) into permission
 from machimoa_review.ingest_sources where source_id=s.source_id;
 ready:=j.status='queued' and j.retry_count=0 and j.next_retry_at is null and j.claimed_at is null
 and j.claimed_by is null and j.claim_lease_until is null and h is null and s.disposition<>'non_target'
 and permission->>'enabled'='true' and permission->>'permission' in ('approved_noncommercial','approved_commercial')
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=s.revision_hash and processing_stage<>'ai_enrichment' and status in ('queued','claimed'))
 and not exists(select 1 from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key);
 return jsonb_build_object('jobId',j.id,'sourceItemId',s.id,'sourceName',s.source_id,'revision',s.revision_hash,
 'version',encode(sha256(convert_to(jsonb_build_array(to_jsonb(j),d->>'version',classification->>'version',h,permission)::text,'UTF8')),'hex'),
 'status',j.status,'canRecheck',coalesce(ready,false),'recheckPending',h is not null,'note',coalesce(h->>'note',''),'review',d,'classification',classification);
end $$;

create function machimoa_review.ai_recheck_command(p_job_id uuid,p_revision text,p_version text,p_request_id uuid,p_note text,p_actor uuid,p_action text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 p machimoa_review.source_item_product_types%rowtype;c machimoa_review.review_classifications%rowtype;codes text[];remaining text[];d jsonb;outcome jsonb;receipt machimoa_review.ai_recheck_receipts%rowtype;legacy text;
begin
 if p_job_id is null or p_request_id is null or p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$'
 or p_version is null or p_version !~ '^[a-f0-9]{64}$' or char_length(btrim(coalesce(p_note,''))) not between 1 and 1000
 or p_action is null or p_action not in ('request_recheck','complete_recheck') then raise sqlstate 'PT422' using message='invalid_recheck';end if;
 -- Serialize receipt keys, then lock source -> facts -> jobs -> permission ->
 -- existing canonical candidate fence. Checks happen after the locks.
 perform pg_advisory_xact_lock(hashtextextended('ai-recheck-request:'||p_request_id::text,0));
 select * into receipt from machimoa_review.ai_recheck_receipts where request_id=p_request_id;
 if found then
  if receipt.job_id is distinct from p_job_id or receipt.action is distinct from p_action or receipt.revision is distinct from p_revision
  or receipt.expected_version is distinct from p_version or receipt.actor is distinct from p_actor or receipt.note is distinct from btrim(p_note)
  then raise sqlstate 'PT409' using message='request_id_conflict';end if;
  return receipt.response;
 end if;
 select * into j from machimoa_review.processing_jobs where id=p_job_id and processing_stage='ai_enrichment';
 if not found then raise sqlstate 'PT404' using message='ai_job_not_found';end if;
 select * into s from machimoa_review.source_items where id=j.source_item_id for update;
 if s.revision_hash is distinct from p_revision or j.revision_hash is distinct from p_revision then raise sqlstate 'PT409' using message='source_revision_conflict';end if;
 perform 1 from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=s.id order by revision_hash,processing_stage for update;
 select legacy_curation_source into legacy from machimoa_review.ingest_sources where source_id=s.source_id for share;
 if legacy is null then raise sqlstate 'PT409' using message='source_contract_missing';end if;
 perform pg_advisory_xact_lock(hashtextextended(legacy||':'||s.external_key,0));
 perform 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key for update;
 d:=public.admin_ai_queue_review_detail(p_job_id);
 if d->>'version' is distinct from p_version or exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 or exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
 or p_action='request_recheck' and s.disposition='non_target' then raise sqlstate 'PT409' using message='recheck_conflict';end if;
 if p_action='request_recheck' then
  if d->>'canRecheck'<>'true' then raise sqlstate 'PT409' using message='recheck_conflict';end if;
  insert into machimoa_review.ai_rechecks(id,job_id,source_item_id,revision_hash,actor,note) values(p_request_id,p_job_id,s.id,p_revision,p_actor,btrim(p_note));
  update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp() where id=p_job_id;
  insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
  values(s.id,p_revision,'content_review','queued',clock_timestamp(),clock_timestamp(),array['ai_recheck_requested'])
  on conflict(source_item_id,revision_hash,processing_stage) do update set status='queued',completed_at=null,
   reason_codes=(case when machimoa_review.processing_jobs.status='queued' then machimoa_review.processing_jobs.reason_codes else '{}'::text[] end)||array['ai_recheck_requested'];
 else
  if d->>'recheckPending'<>'true' or d->>'status'<>'cancelled' then raise sqlstate 'PT409' using message='recheck_conflict';end if;
  select array_remove(reason_codes,'ai_recheck_requested') into remaining from machimoa_review.processing_jobs
   where source_item_id=s.id and revision_hash=p_revision and processing_stage='content_review' and status='queued';
  remaining:=coalesce(remaining,'{}');
  update machimoa_review.ai_rechecks set completed_at=clock_timestamp() where job_id=p_job_id and completed_at is null;
  update machimoa_review.processing_jobs set status='completed',completed_at=clock_timestamp(),reason_codes=array_remove(reason_codes,'ai_recheck_requested')
  where source_item_id=s.id and revision_hash=p_revision and processing_stage='content_review';
  -- Re-evaluate actual facts/filters/time/permission. No forced AI-ready status.
  select * into c from machimoa_review.review_classifications where source_item_id=s.id and revision_hash=p_revision for update;
  if found then
   -- The target classification remains authoritative. Never overwrite its facts,
   -- filters or native snapshot with the native source evaluator.
   codes:=machimoa_review.classification_reasons(s.id,c.facts);
   if c.native_snapshot is distinct from machimoa_review.classification_native(s.id) then codes:=array_append(codes,'classification_input_changed');end if;
   update machimoa_review.processing_jobs set status=case when cardinality(codes)=0 then 'completed' else 'queued' end,
    completed_at=case when cardinality(codes)=0 then clock_timestamp() else null end,reason_codes=codes
    where source_item_id=s.id and revision_hash=p_revision and processing_stage='content_review';
   if machimoa_review.classification_ready(s.id) then
    update machimoa_review.processing_jobs set status='queued',completed_at=null where id=p_job_id;
   end if;
  elsif s.source_id='seoul_reservation' then perform machimoa_review.program_refresh(s.id);
  elsif s.source_id='myseoul_program' then perform machimoa_review.myseoul_refresh(s.id);
  else
   select * into p from machimoa_review.source_item_product_types where source_item_id=s.id and revision_hash=p_revision for update;
   if not found then raise sqlstate 'PT409' using message='facts_missing';end if;
   perform machimoa_review.apply_source_item_evaluation(s.id,p_revision,p.product_type,coalesce(p.reason_codes,'{}'),p.gate_facts);
  end if;
  -- Completion removes only the deliberate hold. Reasons still pending after
  -- the last formal fact save cannot be silently cleared by clicking complete.
  if cardinality(remaining)>0 and exists(select 1 from machimoa_review.source_items where id=s.id and disposition<>'non_target') then
   update machimoa_review.processing_jobs set status='queued',completed_at=null,
    reason_codes=array(select distinct r from unnest(reason_codes||remaining) r order by r)
    where source_item_id=s.id and revision_hash=p_revision and processing_stage='content_review';
  end if;
  -- A native facts refresh can queue before its filter review sync. Only a fully
  -- ready current input may remain queued; no reason/permission bypass here.
  if exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision and processing_stage<>'ai_enrichment' and status in ('queued','claimed'))
   or exists(select 1 from machimoa_review.source_items where id=s.id and disposition='non_target')
   or not exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id and enabled and permission_status in ('approved_noncommercial','approved_commercial'))
   or c.source_item_id is null and not machimoa_review.content_filter_ready(s.id,p_revision)
  then
   update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp() where id=p_job_id and status='queued';
  end if;
 end if;
 outcome:=public.admin_ai_queue_review_detail(p_job_id);
 insert into machimoa_review.ai_recheck_receipts(request_id,job_id,action,revision,expected_version,actor,note,response) values(p_request_id,p_job_id,p_action,p_revision,p_version,p_actor,btrim(p_note),outcome);
 return outcome;
end $$;
create function public.admin_ai_queue_request_recheck(p_job_id uuid,p_revision text,p_version text,p_request_id uuid,p_note text,p_actor uuid) returns jsonb
language sql security definer set search_path='' as $$
 select machimoa_review.ai_recheck_command(p_job_id,p_revision,p_version,p_request_id,p_note,p_actor,'request_recheck')
$$;
create function public.admin_ai_queue_complete_recheck(p_job_id uuid,p_revision text,p_version text,p_request_id uuid,p_note text,p_actor uuid) returns jsonb
language sql security definer set search_path='' as $$
 select machimoa_review.ai_recheck_command(p_job_id,p_revision,p_version,p_request_id,p_note,p_actor,'complete_recheck')
$$;

-- Keep held jobs reachable after refresh, including a new browser session.
alter function public.admin_review_ai_queue(integer,integer,uuid[]) rename to ai_recheck_base_queue;
alter function public.ai_recheck_base_queue(integer,integer,uuid[]) set schema machimoa_review;
create function public.admin_review_ai_queue(p_offset integer default 0,p_limit integer default 25,p_watch uuid[] default '{}') returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare d jsonb;held jsonb;more boolean;begin
 d:=machimoa_review.ai_recheck_base_queue(p_offset,p_limit,p_watch);
 with page as (
 select j.*,h.created_at hold_created_at,h.id hold_id,s.source_id,s.min_fields,s.normalized_payload from machimoa_review.ai_rechecks h
 join machimoa_review.processing_jobs j on j.id=h.job_id join machimoa_review.source_items s on s.id=h.source_item_id
 where h.completed_at is null and s.revision_hash=h.revision_hash and j.status='cancelled'
 order by h.created_at,h.id offset p_offset limit p_limit+1), visible as (select * from page order by hold_created_at,hold_id limit p_limit)
 select coalesce((select jsonb_agg(jsonb_build_object('jobId',id,'sourceItemId',source_item_id,'revision',revision_hash,
 'currentRevision',true,'status','cancelled','sourceName',source_id,
 'title',left(coalesce(min_fields->>'title',normalized_payload->>'title','제목 확인 필요'),500),
 'completedAt',completed_at,'retryCount',retry_count,'nextRetryAt',next_retry_at,'leaseState','none','errorCode',null,'resultState',null) order by hold_created_at,hold_id) from visible),'[]'),
 (select count(*)>p_limit from page) into held,more;
 return d||jsonb_build_object('held',held,'hasMore',(d->>'hasMore')::boolean or more);
end $$;
do $$ declare r record;begin
 for r in select p.oid::regprocedure signature,n.nspname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where (n.nspname='machimoa_review' and p.proname in ('ai_recheck_pending','ai_recheck_job_guard','ai_recheck_command','ai_recheck_base_program_detail','ai_recheck_base_myseoul_detail','ai_recheck_base_queue'))
 or (n.nspname='public' and p.proname in ('admin_ai_queue_review_detail','admin_ai_queue_request_recheck','admin_ai_queue_complete_recheck','admin_program_detail','admin_myseoul_program_detail','admin_review_ai_queue')) loop
 execute format('revoke all on function %s from public,anon,authenticated,service_role',r.signature);
 if r.nspname='public' then execute format('grant execute on function %s to service_role',r.signature);end if;
 end loop;
end $$;
commit;
