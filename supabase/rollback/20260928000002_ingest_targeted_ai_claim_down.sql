-- Rollback removes only the targeted canary adapter. The global claim path is unchanged.
drop function if exists public.claim_processing_job_for_source_item(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4
);
notify pgrst, 'reload schema';
