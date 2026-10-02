-- Disable feature access while preserving every bookmark. Operating use needs
-- separate approval. Do not add DROP SCHEMA/TABLE CASCADE or purge saved rows.
begin;
do $guard$
begin
  if current_user <> 'postgres' then raise exception 'rollback requires postgres'; end if;
end
$guard$;
drop function public.list_saved_information(pg_catalog.text, pg_catalog.int4, pg_catalog.int4);
drop function public.saved_information_state(pg_catalog.uuid);
drop function public.remove_saved_information(pg_catalog.uuid);
drop function public.save_information(pg_catalog.uuid);
revoke all on function machimoa_saved.is_savable(public.curations)
  from public, anon, authenticated, service_role;
revoke all on table machimoa_saved.information from public, anon, authenticated, service_role;
revoke all on schema machimoa_saved from public, anon, authenticated, service_role;
commit;
