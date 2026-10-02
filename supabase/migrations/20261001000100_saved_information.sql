-- Account-owned bookmarks. Prepare locally; operating DB application is separate.
-- No changes to public content, ingest/review policies or administrator access.
begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception 'saved information migration requires postgres';
  end if;
  if pg_catalog.to_regclass('auth.users') is null
     or pg_catalog.to_regprocedure('auth.uid()') is null
     or pg_catalog.to_regclass('public.curations') is null then
    raise exception 'auth and public curations prerequisites are missing';
  end if;
  if not exists (select 1 from pg_catalog.pg_attribute
                 where attrelid = 'public.curations'::pg_catalog.regclass
                   and attname = 'id' and atttypid = 'uuid'::pg_catalog.regtype
                   and not attisdropped) then
    raise exception 'public.curations.id must be uuid';
  end if;
end
$guard$;

create schema machimoa_saved authorization postgres;
revoke all on schema machimoa_saved from public, anon, authenticated, service_role;
grant usage on schema machimoa_saved to authenticated;

create table machimoa_saved.information (
  user_id pg_catalog.uuid not null references auth.users(id) on delete cascade,
  original_curation_id pg_catalog.uuid not null,
  curation_id pg_catalog.uuid references public.curations(id) on delete set null,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  constraint saved_information_pk primary key (user_id, original_curation_id),
  constraint saved_information_identity_ck
    check (curation_id is null or curation_id = original_curation_id)
);
alter table machimoa_saved.information owner to postgres;
alter table machimoa_saved.information enable row level security;
revoke all on table machimoa_saved.information
  from public, anon, authenticated, service_role;
-- Inserts/updates go through the checked save function, never raw client writes.
grant select, delete on table machimoa_saved.information to authenticated;
create policy saved_information_select_own on machimoa_saved.information
  for select to authenticated using ((select auth.uid()) = user_id);
create policy saved_information_delete_own on machimoa_saved.information
  for delete to authenticated using ((select auth.uid()) = user_id);
create index saved_information_order_idx on machimoa_saved.information
  (user_id, created_at desc, original_curation_id desc);

-- Matches the app's public display gate: confirmed display category and six
-- reviewed bilingual fields. Does not fall back to the legacy source category.
create function machimoa_saved.is_savable(p_row public.curations)
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
revoke all on function machimoa_saved.is_savable(public.curations)
  from public, anon, authenticated, service_role;
grant execute on function machimoa_saved.is_savable(public.curations) to authenticated;

-- The only elevated operation. No caller-supplied owner, category or content.
-- Lock the current content row until commit to serialize against unpublish/delete.
create function public.save_information(p_curation_id pg_catalog.uuid)
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
alter function public.save_information(pg_catalog.uuid) owner to postgres;
revoke all on function public.save_information(pg_catalog.uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.save_information(pg_catalog.uuid) to authenticated;

create function public.remove_saved_information(p_curation_id pg_catalog.uuid)
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
revoke all on function public.remove_saved_information(pg_catalog.uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.remove_saved_information(pg_catalog.uuid) to authenticated;

create function public.saved_information_state(p_curation_id pg_catalog.uuid)
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
revoke all on function public.saved_information_state(pg_catalog.uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.saved_information_state(pg_catalog.uuid) to authenticated;

create function public.list_saved_information(
  p_locale pg_catalog.text default 'ko',
  p_limit pg_catalog.int4 default 25,
  p_offset pg_catalog.int4 default 0
)
returns pg_catalog.jsonb language plpgsql stable security invoker set search_path = ''
as $function$
declare
  v_user pg_catalog.uuid := auth.uid();
  v_result pg_catalog.jsonb;
begin
  if v_user is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  if p_locale is null or p_locale not in ('ko', 'ja')
     or p_limit is null or p_limit not between 1 and 100
     or p_offset is null or p_offset not between 0 and 100000 then
    raise exception using errcode = '22023', message = 'invalid_list_parameters';
  end if;
  with owned as (
    select s.* from machimoa_saved.information as s where s.user_id = v_user
      order by s.created_at desc, s.original_curation_id desc
      limit p_limit + 1 offset p_offset
  ), decorated as (
    select s.original_curation_id, s.created_at,
      pg_catalog.jsonb_build_object(
        'id', s.original_curation_id, 'savedAt', s.created_at,
        'availability', case when machimoa_saved.is_savable(c)
                             then 'available' else 'unavailable' end,
        'information', case when machimoa_saved.is_savable(c) then
          pg_catalog.jsonb_build_object(
            'slug', c.slug, 'category', c.user_category,
            'title', case when p_locale = 'ja' then c.title_ja else c.title_ko end,
            'summary', case when p_locale = 'ja' then c.summary_ja else c.summary_ko end,
            'applicationDeadlineKind', c.application_deadline_kind,
            'applicationDeadlineOn', c.application_deadline_on)
          else null end) as item
    from owned as s left join public.curations as c on c.id = s.curation_id
  ), page as (
    select * from decorated order by created_at desc, original_curation_id desc limit p_limit
  )
  select pg_catalog.jsonb_build_object(
    'items', coalesce((select pg_catalog.jsonb_agg(item order by created_at desc, original_curation_id desc)
                      from page), '[]'::pg_catalog.jsonb),
    'hasMore', (select count(*) > p_limit from owned)) into v_result;
  -- No exception-to-empty-list fallback: DB faults must reach the caller.
  return v_result;
end
$function$;
revoke all on function public.list_saved_information(pg_catalog.text, pg_catalog.int4, pg_catalog.int4)
  from public, anon, authenticated, service_role;
grant execute on function public.list_saved_information(pg_catalog.text, pg_catalog.int4, pg_catalog.int4)
  to authenticated;

commit;
