-- Roll back functions/permissions only. Keep bookmarks and private order records.
-- Restores Stage 2 behavior, including its known stale-request limitations.
begin;
drop function public.save_information(uuid,text);
drop function public.resume_saved_information(uuid,uuid);
drop function public.prepare_saved_information_intent(uuid);
drop function public.cancel_saved_information_intent(uuid);
create or replace function public.saved_information_state(p_curation_id pg_catalog.uuid)
returns pg_catalog.jsonb language plpgsql stable security invoker set search_path = ''
as $function$
declare v_user pg_catalog.uuid := auth.uid();
begin
  if v_user is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  if p_curation_id is null then
    raise exception using errcode = '22023', message = 'invalid_curation_id';
  end if;
  return pg_catalog.jsonb_build_object('id', p_curation_id, 'saved', exists (
    select 1 from machimoa_saved.information
      where user_id = v_user and original_curation_id = p_curation_id));
end
$function$;
create or replace function machimoa_saved.is_savable(p_row public.curations)
returns pg_catalog.bool language sql immutable security invoker set search_path = ''
as $function$
  select coalesce(p_row.is_published
    and p_row.user_category in ('policy', 'program')
    and length(btrim(p_row.title_ko)) > 0
    and length(btrim(p_row.summary_ko)) > 0
    and length(btrim(p_row.content_ko)) > 0
    and length(btrim(p_row.title_ja)) > 0
    and length(btrim(p_row.summary_ja)) > 0
    and length(btrim(p_row.content_ja)) > 0, false);
$function$;
create or replace function public.remove_saved_information(p_curation_id pg_catalog.uuid)
returns pg_catalog.jsonb language plpgsql security definer set search_path = ''
as $function$
declare v_user pg_catalog.uuid := auth.uid();
begin
  if v_user is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  if p_curation_id is null then
    raise exception using errcode = '22023', message = 'invalid_curation_id';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('saved:' || v_user::text, 0));
  insert into machimoa_saved.resume_fences(user_id, scope, cancelled_at) values (v_user, p_curation_id::text, pg_catalog.clock_timestamp()) on conflict(user_id,scope) do update set cancelled_at=excluded.cancelled_at;
  delete from machimoa_saved.information
    where user_id = v_user and original_curation_id = p_curation_id;
  return pg_catalog.jsonb_build_object('id', p_curation_id, 'saved', false);
end
$function$;
create or replace function public.cancel_saved_information_resume(p_curation_id uuid default null)
returns jsonb language plpgsql security definer set search_path = '' as $f$
declare v_user uuid := auth.uid();
begin
  if v_user is null then raise exception using errcode='42501',message='authentication_required'; end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('saved:' || v_user::text, 0));
  insert into machimoa_saved.resume_fences(user_id,scope,cancelled_at)
    values(v_user,coalesce(p_curation_id::text,'account'),pg_catalog.clock_timestamp())
    on conflict(user_id,scope) do update set cancelled_at=excluded.cancelled_at;
  return jsonb_build_object('cancelled',true);
end $f$;
grant execute on function public.save_information(uuid),public.resume_saved_information(uuid,uuid,timestamptz) to authenticated;
grant delete on machimoa_saved.information to authenticated;
commit;
