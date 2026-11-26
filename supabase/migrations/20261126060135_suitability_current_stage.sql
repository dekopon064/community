-- Keep the frozen queue, decision and exclusion preconditions intact. Project current stage at read time.
create or replace function public.suitability_report(p_run uuid default null) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('id',r.id,'policy',r.policy,'readAt',r.read_at,'items',coalesce((
 select jsonb_agg(jsonb_build_object('id',i.item_id,'title',i.title,'source',i.source,'key',i.external_key,
  'queue',case when i.job_id is null then 'facts' else 'ai' end,'moved',i.moved_at is not null,
  'currentStage',case
   when s.id is null then 'unknown'
   when exists(select from machimoa_review.curation_candidates c
     where machimoa_review.canonical_source_id(c.source)=s.source_id
     and c.source_item_id=s.external_key and c.source_revision_hash=i.revision) then 'candidate'
   when i.moved_at is not null or exists(select from machimoa_review.admin_exclusion_episodes e
     where e.source_item_id=s.id and e.restored_at is null) then 'unknown'
   when j.status='queued' and machimoa_review.ai_queue_executable(j.id) then 'ai'
   when j.status='claimed' then case when j.claim_lease_until>statement_timestamp() then 'processing' else 'unknown' end
   when (case i.source when 'myseoul_program' then public.admin_myseoul_program_detail(s.id)
     when 'seoul_reservation' then public.admin_program_detail(s.id) end)->>'status'='open' then 'facts'
   else 'unknown' end,
  'reused',d.decision is not null and d.owner_run<>r.id,'state',case when d.decision is not null then 'done'
   when d.owner_run is null then 'waiting' else 'unconfirmed' end,'decision',d.decision)
  order by i.source,i.external_key) from machimoa_review.suitability_items i left join machimoa_review.suitability_decisions d
 on (d.source,d.external_key,d.revision,d.policy_hash)=(i.source,i.external_key,i.revision,r.policy_hash)
 left join machimoa_review.source_items s on (s.id,s.source_id,s.external_key,s.revision_hash)=(i.item_id,i.source,i.external_key,i.revision)
 left join machimoa_review.processing_jobs j on j.source_item_id=s.id and j.revision_hash=i.revision and j.processing_stage='ai_enrichment'
 where i.run_id=r.id),'[]')) from machimoa_review.suitability_runs r
 where r.policy_hash is not null and (p_run is null or r.id=p_run) order by r.created_at desc limit 1
$$;
