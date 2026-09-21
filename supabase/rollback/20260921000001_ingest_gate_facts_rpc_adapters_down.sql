-- Drop public v4 upsert and public gate-facts resolve only.
-- Drop public v4 before private v4/core in 20260921000000_ingest_gate_facts_down.sql.
-- Do not drop private resolve/apply/evaluate/v4/claim functions here.
-- Do not delete curation_candidates or public.curations.
-- Apply this file before 20260921000000_ingest_gate_facts_down.sql.
-- This file is not auto-applied.
-- Fail closed if V1 gate_facts rows or living_guide product types exist.

begin;

do $preflight$
begin
  lock table machimoa_review.source_item_product_types
    in access exclusive mode;
  lock table machimoa_review.processing_jobs
    in access exclusive mode;
  if exists (
    select 1
    from machimoa_review.source_item_product_types as pt
    where pt.gate_facts is not null
       or pt.assessment_schema_version is not null
       or pt.evaluated_profile is not null
       or pt.evaluated_at is not null
  ) then
    raise exception 'rollback_gate_facts_data_present';
  end if;
  if exists (
    select 1
    from machimoa_review.source_item_product_types as pt
    where pt.product_type = 'living_guide'
  ) then
    raise exception 'rollback_gate_facts_data_present';
  end if;
end
$preflight$;

drop function if exists public.upsert_source_observations_v4(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
);
drop function if exists public.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
);

notify pgrst, 'reload schema';

commit;
