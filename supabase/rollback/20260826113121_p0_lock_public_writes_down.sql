-- EMERGENCY ROLLBACK ONLY.
-- This restores the insecure public write permissions captured before the P0
-- lockdown. Do not run during normal deployment.

begin;

drop policy if exists "curations_public_select" on public.curations;
drop policy if exists "qna_entries_public_select" on public.qna_entries;

revoke all privileges on table public.curations from anon, authenticated;
revoke all privileges on table public.qna_entries from anon, authenticated;

grant select, insert, update, delete, truncate, references, trigger
  on table public.curations
  to anon, authenticated;
grant select, insert, update, delete, truncate, references, trigger
  on table public.qna_entries
  to anon, authenticated;

create policy "Enable delete for all users"
  on public.curations
  for delete
  to public
  using (true);

create policy "Enable insert for all users"
  on public.curations
  for insert
  to public
  with check (true);

create policy "Enable read access for all users"
  on public.curations
  for select
  to public
  using (true);

create policy "Enable update for all users"
  on public.curations
  for update
  to public
  using (true);

create policy "Enable insert for all users"
  on public.qna_entries
  for insert
  to public
  with check (true);

create policy "Enable read access for all users"
  on public.qna_entries
  for select
  to public
  using (true);

commit;
