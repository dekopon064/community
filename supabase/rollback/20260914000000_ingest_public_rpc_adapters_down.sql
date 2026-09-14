-- Drop public ingest RPC adapters only. Do not drop or recreate private
-- machimoa_review complete/finish/fail functions or ingest tables.
-- Do not delete curation_candidates or public.curations.
-- This file is not auto-applied.

begin;

drop function if exists public.get_ingest_source(pg_catalog.text);
drop function if exists public.start_ingest_run(pg_catalog.text, pg_catalog.int4);
drop function if exists public.upsert_source_observations(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
);
drop function if exists public.finish_ingest_run(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4,
  pg_catalog.bool, pg_catalog.int4
);
drop function if exists public.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
);
drop function if exists public.complete_processing_job(pg_catalog.uuid, pg_catalog.text);
drop function if exists public.fail_processing_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
);

notify pgrst, 'reload schema';

commit;
