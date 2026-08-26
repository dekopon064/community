-- P0 security lockdown: public clients may read, but may not write.
-- Captured pre-change state:
--   supabase/audit/2026-08-26_pre_p0_state.md
-- Emergency rollback (intentionally outside migrations):
--   supabase/rollback/20260826113121_p0_lock_public_writes_down.sql

begin;

do $$
begin
  if not exists (
    select 1
    from pg_roles
    where rolname = 'service_role'
      and rolbypassrls
  ) then
    raise exception 'P0 migration aborted: service_role must bypass RLS';
  end if;
end
$$;

-- Remove the captured public write/read policies.
drop policy if exists "Enable delete for all users" on public.curations;
drop policy if exists "Enable insert for all users" on public.curations;
drop policy if exists "Enable read access for all users" on public.curations;
drop policy if exists "Enable update for all users" on public.curations;
drop policy if exists "Enable insert for all users" on public.qna_entries;
drop policy if exists "Enable read access for all users" on public.qna_entries;

-- Make table grants explicitly read-only for both public API roles.
revoke all privileges on table public.curations from anon, authenticated;
revoke all privileges on table public.qna_entries from anon, authenticated;

grant select on table public.curations to anon, authenticated;
grant select on table public.qna_entries to anon, authenticated;

create policy "curations_public_select"
  on public.curations
  for select
  to anon, authenticated
  using (true);

create policy "qna_entries_public_select"
  on public.qna_entries
  for select
  to anon, authenticated
  using (true);

commit;
