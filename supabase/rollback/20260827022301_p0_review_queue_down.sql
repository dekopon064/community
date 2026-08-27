-- LOSSLESS ROLLBACK.
-- Stop all workflow runs and restore the pre-enqueue pipeline before use.
-- This removes the three review-boundary functions and restores the measured
-- pre-migration privileges on public.curations. Candidate data and review
-- schema objects remain intact.
--
-- Recovery after this script:
-- Do not re-run 20260827022301_p0_review_queue.sql. That migration creates
-- the schema and added columns and will fail if they already exist.
-- Do not run the matching cleanup to make that original migration runnable
-- again. Cleanup deletes candidate rows and the added curation source
-- columns.
-- After the failure cause is fixed, restore functions and grants with a
-- new timestamped forward migration. Do not keep a duplicate function
-- definition file that can drift from the forward path.
-- Keep the scheduled collection workflow paused until that forward
-- recovery has been applied and verified.

begin;

do $guard$
begin
  if current_user <> 'postgres' or session_user <> 'postgres' then
    raise exception
      'P0 review queue rollback must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  if pg_catalog.to_regnamespace('machimoa_review') is null then
    raise exception 'schema machimoa_review does not exist';
  end if;
end
$guard$;

drop function public.enqueue_curation_candidate(
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.jsonb,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text
);

drop function machimoa_review.publish_curation_candidate(
  pg_catalog.uuid,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.bool
);

drop function machimoa_review.reject_curation_candidate(
  pg_catalog.uuid,
  pg_catalog.text,
  pg_catalog.text
);

-- Restore the exact measured pre-migration ACL:
-- PUBLIC none; anon/authenticated SELECT; service_role all eight privileges.
revoke all privileges on table public.curations
  from public, anon, authenticated, service_role;

grant select on table public.curations
  to anon, authenticated;

grant
  select,
  insert,
  update,
  delete,
  truncate,
  references,
  trigger,
  maintain
on table public.curations
to service_role;

commit;
