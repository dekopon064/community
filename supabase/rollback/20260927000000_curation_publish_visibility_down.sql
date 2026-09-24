-- Restore anon/authenticated curations SELECT to all rows and drop
-- set_curation_published.
-- Fail closed while any public.curations.is_published = false row exists.
-- Does not delete publication events, lineage, curations, or candidates.
-- Does not drop is_published. This file is not auto-applied.
-- To show a hidden curation again, call set_curation_published(true)
-- before this rollback.

begin;
set transaction isolation level read committed;

-- Wait for in-flight visibility calls, then prevent waiting calls from
-- continuing until the policy and function removal commit.
select pg_catalog.pg_advisory_xact_lock(20260927, 1);

-- Block visibility updates until the preflight and policy change commit.
lock table public.curations in share row exclusive mode;

do $preflight$
begin
  if current_user <> 'postgres' then
    raise exception
      'publish visibility rollback must run as postgres (current_user=%)',
      current_user;
  end if;
  if exists (
    select 1
    from public.curations as c
    where c.is_published = false
  ) then
    raise exception 'rollback_unpublished_curations_present';
  end if;
end
$preflight$;

drop function if exists machimoa_review.set_curation_published(
  pg_catalog.uuid, pg_catalog.bool, pg_catalog.text, pg_catalog.text
);

drop policy if exists "curations_public_select" on public.curations;

create policy "curations_public_select"
  on public.curations
  for select
  to anon, authenticated
  using (true);

commit;
