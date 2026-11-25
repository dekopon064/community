begin;
set local lock_timeout='5s';

-- Used both by classification save (same transaction) and by an explicit
-- single-item recovery. Never revives a processed, held or in-flight job.
create function public.admin_queue_confirmed_classification(p_id uuid,p_revision text,
 p_classification_version bigint,p_version text) returns uuid
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; detail jsonb; job uuid;
begin
 select * into s from machimoa_review.source_items where id=p_id for update;
 if not found or s.source_id not in ('myseoul_program','seoul_reservation')
    or s.revision_hash is distinct from p_revision then
   raise sqlstate 'PT409' using message='classification_conflict';
 end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by id for update;
 detail:=public.admin_review_classification_detail(p_id);
 if detail->>'version' is distinct from p_version or p_classification_version is null
    or p_classification_version<1 or (detail->>'classificationVersion')::bigint is distinct from p_classification_version
    or not (detail->>'ready')::boolean or not (detail->>'editable')::boolean
    or jsonb_array_length(detail->'sourceReasons')<>0
    or machimoa_review.ai_recheck_pending(p_id,p_revision)
    or exists(select from machimoa_review.curation_candidates c
       where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key
       and (c.source_revision_hash=p_revision or c.review_status in ('pending','published')))
 then raise sqlstate 'PT409' using message='classification_not_ready'; end if;
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at)
 values(p_id,p_revision,'ai_enrichment','queued',statement_timestamp(),statement_timestamp())
 on conflict(source_item_id,revision_hash,processing_stage) do nothing;
 select id into job from machimoa_review.processing_jobs where source_item_id=p_id
   and revision_hash=p_revision and processing_stage='ai_enrichment' and status='queued'
   and retry_count=0 and next_retry_at is null;
 if job is null or not machimoa_review.ai_queue_executable(job) then
   raise sqlstate 'PT409' using message='classification_queue_unavailable';
 end if;
 return job;
end $$;
revoke all on function public.admin_queue_confirmed_classification(uuid,text,bigint,text) from public,anon,authenticated;
grant execute on function public.admin_queue_confirmed_classification(uuid,text,bigint,text) to service_role;

-- Keep the existing revision fences, classification history and explicit
-- reclassification behaviour for candidates that are already under review.
do $migration$
declare body text; anchor text;
begin
 body:=pg_get_functiondef('public.admin_review_reclassify(uuid,text,text,bigint,jsonb,jsonb,text,uuid)'::regprocedure);
 anchor:='requested_id uuid:=p_id;';
 if cardinality(string_to_array(body,anchor))<>2 then raise exception 'classification declaration changed';end if;
 body:=replace(body,anchor,anchor||' queue_on_save boolean; initial_category_missing boolean;');
 anchor:='perform machimoa_review.classification_validate(p_facts,p_filters);';
 if cardinality(string_to_array(body,anchor))<>2 then raise exception 'classification validation changed';end if;
 body:=replace(body,anchor,anchor||$part$
 initial_category_missing:=coalesce(machimoa_review.cl_base_content_filter_category(p_id,p_revision),'')
   not in ('policy','program','event','youth_space','living');
 queue_on_save:=s.source_id in ('myseoul_program','seoul_reservation') and
   (coalesce(item->>'category','')='' or
    p_classification_version>0 and initial_category_missing and exists(select from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision
        and status='queued'))
   and not machimoa_review.ai_recheck_pending(p_id,p_revision);
 if initial_category_missing and p_classification_version>0 and item->'facts'=p_facts and item->'filters'=coalesce(p_filters,'null'::jsonb)
    and item->>'note'=p_note and (item->>'ready')::boolean and s.source_id in ('myseoul_program','seoul_reservation')
    and (exists(select from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision
          and processing_stage='ai_enrichment' and status='queued')
      or exists(select from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id
          and c.source_item_id=s.external_key and c.review_status in ('pending','published'))) then
   return item;
 end if;
 if queue_on_save and exists(select from machimoa_review.curation_candidates c
   where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key
   and (c.source_revision_hash=p_revision or c.review_status in ('pending','published'))) then
   raise sqlstate 'PT409' using message='classification_conflict';
 end if;
$part$);
 anchor:='and status in (''queued'',''failed'',''completed'');';
 if cardinality(string_to_array(body,anchor))<>2 then raise exception 'classification cancellation changed';end if;
 body:=replace(body,anchor,'and (not queue_on_save or revision_hash<>p_revision) '||anchor);
 anchor:='return public.admin_review_classification_detail(requested_id);';
 if cardinality(string_to_array(body,anchor))<>2 then raise exception 'classification return changed';end if;
 body:=replace(body,anchor,$part$
 if queue_on_save and cardinality(codes)=0 and not exists(select from machimoa_review.processing_jobs
   where source_item_id=p_id and revision_hash=p_revision and processing_stage<>'ai_enrichment'
   and status in ('queued','claimed')) then
   item:=public.admin_review_classification_detail(p_id);
   perform public.admin_queue_confirmed_classification(p_id,p_revision,v,item->>'version');
 end if;
$part$||anchor);
 execute body;

 body:=pg_get_functiondef('machimoa_review.ai_recheck_base_queue(integer,integer,uuid[])'::regprocedure);
 anchor:='''currentRevision'',s.revision_hash=j.revision_hash';
 if cardinality(string_to_array(body,anchor))<>2 then raise exception 'queue projection changed';end if;
 execute replace(body,anchor,$part$'classificationVersion',(select c.classification_version from machimoa_review.review_classifications c
    where c.source_item_id=j.source_item_id and c.revision_hash=j.revision_hash),$part$||anchor);

 -- A source with no original category may have no native filter row. In
 -- that case the targeted claim captures the operator's versioned filters.
 body:=pg_get_functiondef('machimoa_review.record_program_no_retry(jsonb,text)'::regprocedure);
 anchor:='snapshot->''filterClaim''=''null''::jsonb';
 if cardinality(string_to_array(body,anchor))<>2 then raise exception 'attempt snapshot changed';end if;
 execute replace(body,anchor,$part$(snapshot->'filterClaim'='null'::jsonb and not coalesce(
   p_context->>'schema'='review-classification-ai-v1'
   and snapshot->'classificationClaim'->>'classification_version'=p_context->>'classificationVersion'
   and snapshot->'classificationClaim'->'facts'=p_context->'facts'
   and snapshot->'classificationClaim'->'filters'=p_context->'filters',false))$part$);
end $migration$;

-- Button claims can consume only the exact queued job/version they selected.
-- A stale selection yields no work and makes no provider call.
create function public.claim_queued_classification_no_retry(p_job_id uuid,p_id uuid,p_revision text,
 p_classification_version bigint,p_worker_id text,p_lease_seconds integer) returns jsonb
language plpgsql security definer set search_path='' as $$
declare src text; ctx jsonb;
begin
 select source_id into src from machimoa_review.source_items where id=p_id and revision_hash=p_revision for update;
 if src is null or src not in ('myseoul_program','seoul_reservation') then return '[]';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by id for update;
 if not exists(select from machimoa_review.processing_jobs j join machimoa_review.review_classifications c
    on c.source_item_id=j.source_item_id and c.revision_hash=j.revision_hash
    where j.id=p_job_id and j.source_item_id=p_id and j.revision_hash=p_revision and j.retry_count=0
      and j.next_retry_at is null and c.classification_version=p_classification_version)
    or not machimoa_review.ai_queue_executable(p_job_id) then return '[]';end if;
 ctx:=public.claim_reclassified_content_ai(p_id,p_revision,p_classification_version,p_worker_id,p_lease_seconds);
 return machimoa_review.record_program_no_retry(ctx,src);
end $$;
revoke all on function public.claim_queued_classification_no_retry(uuid,uuid,text,bigint,text,integer) from public,anon,authenticated;
grant execute on function public.claim_queued_classification_no_retry(uuid,uuid,text,bigint,text,integer) to service_role;

-- The native detail can still say "blocked" based on the unclassified source.
-- Reflect only a current classification job that the AI queue actually lists.
create function machimoa_review.classification_queue_detail(p_id uuid,d jsonb) returns jsonb
language sql stable set search_path='' as $$
 select case when d->>'status'='resolved' and d->>'aiStatus'='blocked' and exists(
   select from machimoa_review.processing_jobs j join machimoa_review.review_classifications c
   on c.source_item_id=j.source_item_id and c.revision_hash=j.revision_hash
   where j.source_item_id=p_id and j.revision_hash=d->>'revision'
   and j.processing_stage='ai_enrichment' and j.status='queued' and machimoa_review.ai_queue_executable(j.id))
 then d||'{"aiStatus":"queued"}'::jsonb else d end
$$;
revoke all on function machimoa_review.classification_queue_detail(uuid,jsonb) from public,anon,authenticated,service_role;
alter function public.admin_myseoul_program_detail(uuid) rename to pre_queue_myseoul_detail;
alter function public.pre_queue_myseoul_detail(uuid) set schema machimoa_review;
alter function public.admin_program_detail(uuid) rename to pre_queue_seoul_detail;
alter function public.pre_queue_seoul_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.pre_queue_myseoul_detail(uuid),machimoa_review.pre_queue_seoul_detail(uuid)
 from public,anon,authenticated,service_role;
create function public.admin_myseoul_program_detail(p_id uuid) returns jsonb language sql stable security definer set search_path='' as $$
 select machimoa_review.classification_queue_detail(p_id,machimoa_review.pre_queue_myseoul_detail(p_id))
$$;
create function public.admin_program_detail(p_id uuid) returns jsonb language sql stable security definer set search_path='' as $$
 select machimoa_review.classification_queue_detail(p_id,machimoa_review.pre_queue_seoul_detail(p_id))
$$;
revoke all on function public.admin_myseoul_program_detail(uuid),public.admin_program_detail(uuid) from public,anon,authenticated;
grant execute on function public.admin_myseoul_program_detail(uuid),public.admin_program_detail(uuid) to service_role;
commit;
