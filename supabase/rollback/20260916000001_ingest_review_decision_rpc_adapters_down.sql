-- Drop public ingest review-decision RPC adapters and public v2 upsert only.
-- Drop public v2 before private v2/core in 20260916000000_ingest_review_decisions_down.sql.
-- Do not drop or recreate private resolve/reconcile/apply/v2/claim functions here.
-- Do not delete curation_candidates or public.curations.
-- Apply this file before 20260916000000_ingest_review_decisions_down.sql.
-- This file is not auto-applied.
-- Fail closed if ingest_review_decisions rows or relevance_review jobs exist so
-- public adapters are not dropped while private core cannot roll back.

begin;

do $preflight$
begin
  lock table machimoa_review.ingest_review_decisions
    in access exclusive mode;
  lock table machimoa_review.processing_jobs
    in access exclusive mode;
  if exists (
    select 1
    from machimoa_review.ingest_review_decisions
  ) then
    raise exception 'rollback_phase2_data_present';
  end if;
  if exists (
    select 1
    from machimoa_review.processing_jobs as j
    where j.processing_stage = 'relevance_review'
  ) then
    raise exception 'rollback_phase2_data_present';
  end if;
end
$preflight$;

drop function if exists public.upsert_source_observations_v2(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
);
drop function if exists public.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
);
drop function if exists public.resolve_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
);

notify pgrst, 'reload schema';

commit;
