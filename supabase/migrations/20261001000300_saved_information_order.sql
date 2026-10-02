-- Independent review M1/M2/L1: DB-ordered invalidation and issued intentions.
-- Prepare locally only. No operating migration application in this task.
begin;
do $$ begin if current_user <> 'postgres' then raise exception 'requires postgres'; end if; end $$;

create sequence machimoa_saved.operation_order;
alter table machimoa_saved.resume_fences add column cancelled_order bigint not null default 0;
create table machimoa_saved.intent_orders (
  token uuid primary key default gen_random_uuid(), curation_id uuid not null,
  issued_order bigint not null default nextval('machimoa_saved.operation_order'),
  created_at timestamptz not null default clock_timestamp(), cancelled_order bigint);
create index intent_orders_created_idx on machimoa_saved.intent_orders(created_at);
alter table machimoa_saved.intent_orders enable row level security;
revoke all on machimoa_saved.intent_orders, machimoa_saved.operation_order from public,anon,authenticated,service_role;
-- All fences already present invalidate any pre-upgrade, unregistered intent.
update machimoa_saved.resume_fences set cancelled_order = nextval('machimoa_saved.operation_order');

-- Exactly ECMAScript String.trim whitespace (U+0085/U+200B are not included).
create or replace function machimoa_saved.is_savable(p_row public.curations)
returns bool language sql immutable security invoker set search_path = '' as $f$
  select coalesce(p_row.is_published and p_row.user_category in ('policy','program')
    and length(btrim(p_row.title_ko, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.summary_ko, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.content_ko, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.title_ja, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.summary_ja, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.content_ja, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0, false);
$f$;

-- No caller can bypass the version contract or the removal fence.
revoke execute on function public.save_information(uuid),public.resume_saved_information(uuid,uuid,timestamptz) from public,anon,authenticated,service_role;
revoke delete on machimoa_saved.information from authenticated;

create function machimoa_saved.current_version(p_user uuid,p_curation uuid)
returns text language sql stable set search_path = '' as $f$
  select coalesce(max(cancelled_order),0)::text from machimoa_saved.resume_fences
    where user_id=p_user and scope in ('account',p_curation::text);
$f$;
revoke all on function machimoa_saved.current_version(uuid,uuid) from public,anon,authenticated,service_role;

create or replace function public.saved_information_state(p_curation_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $f$
declare v_user uuid := auth.uid();
begin
  if v_user is null then raise exception using errcode='42501',message='authentication_required'; end if;
  if p_curation_id is null then raise exception using errcode='22023',message='invalid_curation_id'; end if;
  return jsonb_build_object('id',p_curation_id,'saved',exists(select 1 from machimoa_saved.information where user_id=v_user and original_curation_id=p_curation_id),
    'version',machimoa_saved.current_version(v_user,p_curation_id));
end $f$;

create function public.save_information(p_curation_id uuid,p_version text)
returns jsonb language plpgsql security definer set search_path = '' as $f$
declare v_user uuid := auth.uid(); v_state jsonb; v_saved jsonb;
begin
  if v_user is null then raise exception using errcode='42501',message='authentication_required'; end if;
  if p_curation_id is null then raise exception using errcode='22023',message='invalid_curation_id'; end if;
  perform pg_advisory_xact_lock(hashtextextended('saved:'||v_user::text,0));
  v_state := public.saved_information_state(p_curation_id);
  if p_version is distinct from v_state->>'version' then return v_state || jsonb_build_object('outcome','stale'); end if;
  v_saved := public.save_information(p_curation_id);
  return v_saved || jsonb_build_object('version',v_state->>'version');
end $f$;

create or replace function public.remove_saved_information(p_curation_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $f$
declare v_user uuid := auth.uid();
begin
  if v_user is null then raise exception using errcode='42501',message='authentication_required'; end if;
  if p_curation_id is null then raise exception using errcode='22023',message='invalid_curation_id'; end if;
  perform pg_advisory_xact_lock(hashtextextended('saved:'||v_user::text,0));
  insert into machimoa_saved.resume_fences(user_id,scope,cancelled_at,cancelled_order)
    values(v_user,p_curation_id::text,clock_timestamp(),nextval('machimoa_saved.operation_order'))
    on conflict(user_id,scope) do update set cancelled_at=excluded.cancelled_at,cancelled_order=excluded.cancelled_order;
  delete from machimoa_saved.information where user_id=v_user and original_curation_id=p_curation_id;
  return public.saved_information_state(p_curation_id);
end $f$;

create or replace function public.cancel_saved_information_resume(p_curation_id uuid default null)
returns jsonb language plpgsql security definer set search_path = '' as $f$
declare v_user uuid := auth.uid();
begin
  if v_user is null then raise exception using errcode='42501',message='authentication_required'; end if;
  perform pg_advisory_xact_lock(hashtextextended('saved:'||v_user::text,0));
  insert into machimoa_saved.resume_fences(user_id,scope,cancelled_at,cancelled_order)
    values(v_user,coalesce(p_curation_id::text,'account'),clock_timestamp(),nextval('machimoa_saved.operation_order'))
    on conflict(user_id,scope) do update set cancelled_at=excluded.cancelled_at,cancelled_order=excluded.cancelled_order;
  return jsonb_build_object('cancelled',true);
end $f$;

-- Public preparation issues a secret nonce for one currently public post only.
-- It neither reads personal bookmarks nor stores one. Auth is required to consume.
create function public.prepare_saved_information_intent(p_curation_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $f$
declare v_token uuid; v_id uuid;
begin
  select c.id into v_id from public.curations c where c.id=p_curation_id and machimoa_saved.is_savable(c) for share;
  if v_id is null then raise exception using errcode='PT404',message='information_unavailable'; end if;
  insert into machimoa_saved.intent_orders(curation_id) values(v_id) returning token into v_token;
  return jsonb_build_object('token',v_token);
end $f$;

-- Possession of the secret nonce permits cancellation only, never personal reads.
create function public.cancel_saved_information_intent(p_intent_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $f$
begin
  update machimoa_saved.intent_orders set cancelled_order=nextval('machimoa_saved.operation_order')
    where token=p_intent_id and cancelled_order is null;
  return jsonb_build_object('cancelled',true);
end $f$;

create function public.resume_saved_information(p_intent_id uuid,p_curation_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $f$
declare v_user uuid := auth.uid(); v_intent machimoa_saved.intent_orders; v_inserted uuid; v_saved jsonb; v_outcome text;
begin
  if v_user is null then raise exception using errcode='42501',message='authentication_required'; end if;
  if p_intent_id is null or p_curation_id is null then raise exception using errcode='22023',message='invalid_intent'; end if;
  perform pg_advisory_xact_lock(hashtextextended('saved:'||v_user::text,0));
  select * into v_intent from machimoa_saved.intent_orders where token=p_intent_id and curation_id=p_curation_id for update;
  if not found or v_intent.created_at <= clock_timestamp()-interval '15 minutes' then return jsonb_build_object('outcome','expired'); end if;
  if v_intent.cancelled_order is not null then return jsonb_build_object('outcome','cancelled'); end if;
  if exists(select 1 from machimoa_saved.resume_receipts where token=p_intent_id) then return jsonb_build_object('outcome','consumed'); end if;
  if exists(select 1 from machimoa_saved.resume_fences where user_id=v_user and scope in ('account',p_curation_id::text) and cancelled_order >= v_intent.issued_order) then
    return jsonb_build_object('outcome','cancelled'); end if;
  insert into machimoa_saved.resume_receipts(token,user_id,curation_id,outcome)
    values(p_intent_id,v_user,p_curation_id,'processing') on conflict(token) do nothing returning token into v_inserted;
  if v_inserted is null then return jsonb_build_object('outcome','consumed'); end if;
  begin
    v_saved := public.save_information(p_curation_id,machimoa_saved.current_version(v_user,p_curation_id)); v_outcome := 'saved';
  exception when sqlstate 'PT404' then v_outcome := 'unavailable'; when others then v_outcome := 'failed'; end;
  update machimoa_saved.resume_receipts set outcome=v_outcome where token=p_intent_id and user_id=v_user;
  return jsonb_build_object('outcome',v_outcome) || case when v_outcome='saved' then v_saved else '{}'::jsonb end;
end $f$;
revoke all on function public.cancel_saved_information_intent(uuid),public.prepare_saved_information_intent(uuid),public.save_information(uuid,text),public.resume_saved_information(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.prepare_saved_information_intent(uuid),public.cancel_saved_information_intent(uuid) to anon,authenticated;
grant execute on function public.save_information(uuid,text),public.resume_saved_information(uuid,uuid) to authenticated;
commit;
