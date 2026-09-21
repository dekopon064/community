-- Drop public product_type RPC adapters and public v3 upsert only.
-- Drop public v3 before private v3/core in 20260918000000_ingest_product_type_down.sql.
-- Do not drop private resolve/apply/ensure/v3/claim functions here.
-- Do not delete curation_candidates or public.curations.
-- Apply this file before 20260918000000_ingest_product_type_down.sql.
-- This file is not auto-applied.
-- Fail closed if confirmed product_type rows or product_type_review jobs exist.

begin;

do $preflight$
begin
  lock table machimoa_review.source_item_product_types
    in access exclusive mode;
  lock table machimoa_review.processing_jobs
    in access exclusive mode;
  if exists (
    select 1
    from machimoa_review.source_item_product_types
  ) then
    raise exception 'rollback_product_type_data_present';
  end if;
  if exists (
    select 1
    from machimoa_review.processing_jobs as j
    where j.processing_stage = 'product_type_review'
  ) then
    raise exception 'rollback_product_type_data_present';
  end if;
end
$preflight$;

drop function if exists public.upsert_source_observations_v3(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
);
drop function if exists public.resolve_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
);

notify pgrst, 'reload schema';

commit;
