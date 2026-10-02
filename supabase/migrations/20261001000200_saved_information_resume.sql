-- Stage 2: consume login-save intentions and fence stale requests after removal/logout.
-- Only for a separately reviewed operating rollout. No content/admin policy changes.
begin;
do $$ begin if current_user <> 'postgres' then raise exception 'requires postgres'; end if; end $$;
create table machimoa_saved.resume_receipts (
  token uuid primary key, user_id uuid not null references auth.users(id) on delete cascade,
  curation_id uuid not null, outcome text not null check(outcome in ('processing','saved','unavailable','failed')),
  created_at timestamptz not null default now());
create index resume_receipts_owner_idx on machimoa_saved.resume_receipts(user_id,created_at);
create table machimoa_saved.resume_fences (
  user_id uuid not null references auth.users(id) on delete cascade, scope text not null,
  cancelled_at timestamptz not null, primary key(user_id,scope));
alter table machimoa_saved.resume_receipts enable row level security;
alter table machimoa_saved.resume_fences enable row level security;
revoke all on machimoa_saved.resume_receipts,machimoa_saved.resume_fences from public,anon,authenticated,service_role;
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
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('saved:' || v_user::text, 0));
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

create function public.cancel_saved_information_resume(p_curation_id uuid default null)
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

create function public.resume_saved_information(p_intent_id uuid,p_curation_id uuid,p_issued_at timestamptz)
returns jsonb language plpgsql security definer set search_path = '' as $f$
declare v_user uuid := auth.uid(); v_inserted uuid; v_saved jsonb; v_outcome text;
begin
  if v_user is null then raise exception using errcode='42501',message='authentication_required'; end if;
  if p_intent_id is null or p_curation_id is null or p_issued_at is null then
    raise exception using errcode='22023',message='invalid_intent'; end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('saved:' || v_user::text, 0));
  if p_issued_at > pg_catalog.clock_timestamp()+interval '5 seconds'
     or p_issued_at <= pg_catalog.clock_timestamp()-interval '15 minutes' then
    return jsonb_build_object('outcome','expired'); end if;
  if exists(select 1 from machimoa_saved.resume_fences where user_id=v_user
      and scope in ('account',p_curation_id::text) and cancelled_at >= p_issued_at) then
    return jsonb_build_object('outcome','cancelled'); end if;
  insert into machimoa_saved.resume_receipts(token,user_id,curation_id,outcome)
    values(p_intent_id,v_user,p_curation_id,'processing') on conflict(token) do nothing returning token into v_inserted;
  if v_inserted is null then return jsonb_build_object('outcome','consumed'); end if;
  -- Failure rolls back the save subtransaction, but consumes the old intention.
  -- A deliberate retry calls save_information rather than replaying this token.
  begin
    v_saved := public.save_information(p_curation_id); v_outcome := 'saved';
  exception when sqlstate 'PT404' then v_outcome := 'unavailable';
    when others then v_outcome := 'failed';
  end;
  update machimoa_saved.resume_receipts set outcome=v_outcome where token=p_intent_id and user_id=v_user;
  return jsonb_build_object('outcome',v_outcome) || case when v_outcome='saved' then v_saved else '{}'::jsonb end;
end $f$;
revoke all on function public.cancel_saved_information_resume(uuid), public.resume_saved_information(uuid,uuid,timestamptz) from public,anon,authenticated,service_role;
grant execute on function public.cancel_saved_information_resume(uuid), public.resume_saved_information(uuid,uuid,timestamptz) to authenticated;
commit;
