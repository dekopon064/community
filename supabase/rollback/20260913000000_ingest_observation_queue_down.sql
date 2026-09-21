-- Drop ingest observation objects. Do not delete curation_candidates or
-- public.curations. Apply this file after
-- 20260913000001_publish_permission_lineage_down.sql so the restored publish
-- function no longer depends on ingest helpers. This file is not auto-applied.

begin;

drop function if exists machimoa_review.set_source_permission(
  text, text, text, text, text
);
drop function if exists machimoa_review.fail_processing_job(uuid, text, text);
drop function if exists machimoa_review.complete_processing_job(uuid, text);
drop function if exists machimoa_review.claim_processing_jobs(text, int, text, int);
drop function if exists machimoa_review.finish_ingest_run(uuid, text, text, int, bool, int);
drop function if exists machimoa_review.upsert_source_observations(text, uuid, jsonb, jsonb);
drop function if exists machimoa_review.jsonb_has_forbidden_attachment(jsonb);
drop function if exists machimoa_review.start_ingest_run(text, int);
drop function if exists machimoa_review.canonical_source_id(text);

drop table if exists machimoa_review.processing_jobs;
drop table if exists machimoa_review.source_items;
drop table if exists machimoa_review.ingest_runs;
drop table if exists machimoa_review.source_relationships;
drop table if exists machimoa_review.source_publication_events;
drop table if exists machimoa_review.source_publications;
drop table if exists machimoa_review.source_permission_events;
drop table if exists machimoa_review.source_sync_state;
drop table if exists machimoa_review.ingest_sources;

commit;
