-- Disable resume endpoints while preserving saved data and audit/fence records.
begin;
drop function public.resume_saved_information(uuid,uuid,timestamptz);
drop function public.cancel_saved_information_resume(uuid);
create or replace function public.save_information(p_curation_id pg_catalog.uuid)
returns pg_catalog.jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_user pg_catalog.uuid := auth.uid();
  v_id pg_catalog.uuid;
  v_created pg_catalog.timestamptz;
begin
  if v_user is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  if p_curation_id is null then
    raise exception using errcode = '22023', message = 'invalid_curation_id';
  end if;
  select c.id into v_id from public.curations as c
    where c.id = p_curation_id and machimoa_saved.is_savable(c) for share;
  if v_id is null then
    -- Same response for absent, nonpublic, wrong category and incomplete content.
    raise exception using errcode = 'PT404', message = 'information_unavailable';
  end if;
  insert into machimoa_saved.information as s (user_id, original_curation_id, curation_id)
    values (v_user, v_id, v_id)
    on conflict (user_id, original_curation_id) do update
      set curation_id = excluded.curation_id
    returning s.created_at into v_created;
  return pg_catalog.jsonb_build_object('id', v_id, 'saved', true, 'savedAt', v_created);
end
$function$;
create or replace function public.remove_saved_information(p_curation_id pg_catalog.uuid)
returns pg_catalog.jsonb language plpgsql security invoker set search_path = ''
as $function$
declare v_user pg_catalog.uuid := auth.uid();
begin
  if v_user is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  if p_curation_id is null then
    raise exception using errcode = '22023', message = 'invalid_curation_id';
  end if;
  delete from machimoa_saved.information
    where user_id = v_user and original_curation_id = p_curation_id;
  return pg_catalog.jsonb_build_object('id', p_curation_id, 'saved', false);
end
$function$;
commit;
