-- EMERGENCY DESTRUCTIVE CLEANUP ONLY.
-- Export machimoa_review.curation_candidates and verify the export before use.
-- The matching lossless down script must complete first. This script deletes
-- all candidate and review-history data and removes the added curation fields.

begin;

do $guard$
begin
  if current_user <> 'postgres' or session_user <> 'postgres' then
    raise exception
      'P0 review queue cleanup must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  if pg_catalog.to_regnamespace('machimoa_review') is null then
    raise exception 'schema machimoa_review does not exist';
  end if;

  if pg_catalog.to_regprocedure(
       'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text)'
     ) is not null
     or pg_catalog.to_regprocedure(
       'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'
     ) is not null
     or pg_catalog.to_regprocedure(
       'machimoa_review.reject_curation_candidate(uuid,text,text)'
     ) is not null then
    raise exception
      'run 20260827022301_p0_review_queue_down.sql before cleanup';
  end if;
end
$guard$;

drop trigger curation_candidates_set_updated_at
  on machimoa_review.curation_candidates;

drop function machimoa_review.set_candidate_updated_at();

-- The table drop removes only its owned indexes, constraints, composite type,
-- and identity sequence. External dependencies cause this transaction to fail.
drop table machimoa_review.curation_candidates;

do $schema_guard$
declare
  v_remaining pg_catalog.text;
begin
  select pg_catalog.string_agg(o.object_identity, ', ' order by o.object_identity)
    into v_remaining
  from (
    select
      'relation ' || c.relname as object_identity
    from pg_catalog.pg_class as c
    join pg_catalog.pg_namespace as n
      on n.oid = c.relnamespace
    where n.nspname = 'machimoa_review'

    union all

    select
      'function '
      || p.proname
      || '('
      || pg_catalog.pg_get_function_identity_arguments(p.oid)
      || ')' as object_identity
    from pg_catalog.pg_proc as p
    join pg_catalog.pg_namespace as n
      on n.oid = p.pronamespace
    where n.nspname = 'machimoa_review'

    union all

    select
      'type ' || t.typname as object_identity
    from pg_catalog.pg_type as t
    join pg_catalog.pg_namespace as n
      on n.oid = t.typnamespace
    where n.nspname = 'machimoa_review'
  ) as o;

  if v_remaining is not null then
    raise exception
      'machimoa_review contains unexpected objects: %; resolve manually',
      v_remaining;
  end if;
end
$schema_guard$;

drop schema machimoa_review;

drop index public.curations_source_item_uk;

alter table public.curations
  drop constraint curations_source_pair_ck;

alter table public.curations
  drop column source,
  drop column source_item_id,
  drop column source_url,
  drop column updated_at;

commit;
