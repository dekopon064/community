-- New, lazy resident identities and content comments. No existing data writes.
begin;
do $guard$
declare predecessor record;
begin
  if current_user <> 'postgres' then raise exception 'requires postgres'; end if;
  if to_regnamespace('machimoa_comments') is not null or exists(
    select 1 from pg_proc where pronamespace='public'::regnamespace and proname in
    ('list_information_comments','prepare_comment_resident','create_information_comment','remove_information_comment',
     'information_comment_request_state','admin_hide_information_comment','purge_expired_hidden_information_comments')) then
    raise exception 'comment contract name collision';
  end if;
  select p.*,l.lanname into predecessor from pg_proc p join pg_language l on l.oid=p.prolang
    where p.oid=to_regprocedure('machimoa_saved.is_savable(public.curations)');
  if not found or md5(replace(predecessor.prosrc,E'\r\n',E'\n')) <> '8ee14877d4efde127ca39106cbb0cb66'
    or predecessor.prorettype <> 'boolean'::regtype or predecessor.lanname <> 'sql' or predecessor.provolatile <> 'i'
    or predecessor.prosecdef or predecessor.proconfig is distinct from array['search_path=""']::text[]
    or predecessor.proowner <> 'postgres'::regrole then raise exception 'unexpected public eligibility predecessor'; end if;
  if to_regprocedure('auth.uid()') is null
    or not exists(select 1 from pg_proc where oid=to_regprocedure('auth.uid()') and prorettype='uuid'::regtype)
    or to_regclass('auth.users') is null then raise exception 'missing verified auth predecessor'; end if;
end $guard$;

create schema machimoa_comments authorization postgres;
revoke all on schema machimoa_comments from public,anon,authenticated,service_role;
grant usage on schema machimoa_comments to anon,authenticated,service_role;
create table machimoa_comments.residents (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  user_id uuid unique references auth.users(id) on delete set null,
  code text not null unique check(code ~ '^[A-HJKMNP-Z2-9]{6}$'),
  last_posted_at timestamptz
);
create table machimoa_comments.comments (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  resident_id uuid not null references machimoa_comments.residents(id),
  curation_id uuid references public.curations(id) on delete set null,
  original_curation_id uuid not null,
  body text,
  state text not null default 'live' check(state in ('live','deleted','hidden')),
  created_at timestamptz not null default clock_timestamp(),
  deleted_at timestamptz,
  hidden_at timestamptz,
  hidden_until timestamptz,
  hidden_by uuid references auth.users(id) on delete set null,
  check((state='live' and body is not null and char_length(body) between 1 and 1000)
    or (state='deleted' and body is null and deleted_at is not null)
    or (state='hidden' and hidden_at is not null and hidden_until=hidden_at+interval '7 days'))
);
create index comments_live_page_idx on machimoa_comments.comments(curation_id,created_at desc,id desc) where state='live';
create index comments_hidden_expiry_idx on machimoa_comments.comments(hidden_until,id) where state='hidden' and body is not null;
create table machimoa_comments.requests (
  resident_id uuid not null references machimoa_comments.residents(id),
  request_id uuid not null,
  original_curation_id uuid not null,
  body_digest bytea not null,
  comment_id uuid not null references machimoa_comments.comments(id),
  primary key(resident_id,request_id)
);
create table machimoa_comments.install_guard(singleton boolean primary key check(singleton),fingerprint jsonb not null);
alter table machimoa_comments.residents enable row level security;
alter table machimoa_comments.comments enable row level security;
alter table machimoa_comments.requests enable row level security;
alter table machimoa_comments.install_guard enable row level security;
revoke all on all tables in schema machimoa_comments from public,anon,authenticated,service_role;

-- The shared eligibility predicate is unchanged. Writes lock the content row
-- before account/comment locks, serializing with unpublish and deletion.
create function machimoa_comments.require_content(p_id uuid,p_lock boolean default false)
returns void language plpgsql security definer set search_path='' as $f$
declare c public.curations;
begin
  if p_lock then select * into c from public.curations where id=p_id for share;
  else select * into c from public.curations where id=p_id; end if;
  if c.id is null or not machimoa_saved.is_savable(c) then
    raise exception using errcode='PT404',message='information_unavailable'; end if;
end $f$;
create function machimoa_comments.normalize_body(p_body text)
returns text language sql immutable set search_path='' as $f$
  select btrim(replace(replace(p_body,E'\r\n',E'\n'),E'\r',E'\n'),
    U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF');
$f$;
create function machimoa_comments.prepare(p_curation_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $f$
declare u uuid:=auth.uid(); r machimoa_comments.residents; candidate text; raw bytea; b integer; i integer; attempt integer;
begin
  if u is null then raise exception using errcode='PT401',message='authentication_required'; end if;
  perform machimoa_comments.require_content(p_curation_id,true);
  perform 1 from auth.users where id=u for key share;
  if not found then raise exception using errcode='PT401',message='authentication_required'; end if;
  perform pg_advisory_xact_lock(1900919,hashtext(u::text));
  select * into r from machimoa_comments.residents where user_id=u;
  if found then return jsonb_build_object('code',r.code); end if;
  for attempt in 1..10 loop
    candidate:='';
    -- Rejection sampling over independent random UUID bytes; never auth UUIDs.
    while char_length(candidate)<6 loop
      raw:=uuid_send(gen_random_uuid());
      for i in 0..5 loop
        b:=get_byte(raw,i);
        if b<248 then candidate:=candidate||substr('ABCDEFGHJKMNPQRSTUVWXYZ23456789',b%31+1,1); end if;
        exit when char_length(candidate)=6;
      end loop;
    end loop;
    begin
      insert into machimoa_comments.residents(user_id,code) values(u,candidate) returning * into r;
      return jsonb_build_object('code',r.code);
    exception when unique_violation then null; end;
  end loop;
  raise exception using errcode='PT503',message='resident_unavailable';
end $f$;
create function machimoa_comments.list(p_curation_id uuid,p_before_at timestamptz default null,p_before_id uuid default null)
returns jsonb language plpgsql stable security definer set search_path='' as $f$
declare items jsonb; next_cursor jsonb; viewer_code text;
begin
  if (p_before_at is null) <> (p_before_id is null) or (p_before_at is not null and not isfinite(p_before_at)) then
    raise exception using errcode='22023',message='invalid_cursor'; end if;
  perform machimoa_comments.require_content(p_curation_id);
  select r.code into viewer_code from machimoa_comments.residents r where r.user_id=auth.uid();
  with page as (
    select c.id,r.code,c.body,c.created_at,r.user_id=auth.uid() as own,
      row_number() over(order by c.created_at desc,c.id desc) as position
    from machimoa_comments.comments c join machimoa_comments.residents r on r.id=c.resident_id
    where c.curation_id=p_curation_id and c.state='live'
      and (p_before_at is null or (c.created_at,c.id)<(p_before_at,p_before_id))
    order by c.created_at desc,c.id desc limit 21
  ) select coalesce(jsonb_agg(jsonb_build_object('id',id,'residentCode',code,'body',body,
      'createdAt',to_char(created_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
      'canDelete',coalesce(own,false)) order by position) filter(where position<=20),'[]'::jsonb),
    case when count(*)>20 then (select jsonb_build_object('at',to_char(created_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'id',id) from page where position=20) else null end
    into items,next_cursor from page;
  return jsonb_build_object('items',items,'next',next_cursor,'code',viewer_code);
end $f$;
create function machimoa_comments.create_comment(p_curation_id uuid,p_request_id uuid,p_body text,p_expected_code text)
returns jsonb language plpgsql security definer set search_path='' as $f$
declare u uuid:=auth.uid(); r machimoa_comments.residents; receipt machimoa_comments.requests;
  c machimoa_comments.comments; body text:=machimoa_comments.normalize_body(p_body); stamp timestamptz;
begin
  if u is null then raise exception using errcode='PT401',message='authentication_required'; end if;
  if p_request_id is null or p_body is null or octet_length(p_body)>8192 or char_length(body) not between 1 and 1000
    or p_body ~ E'[\x01-\x08\x0B\x0C\x0E-\x1F\x7F]' then
    raise exception using errcode='22023',message='invalid_comment'; end if;
  perform machimoa_comments.require_content(p_curation_id,true);
  select * into r from machimoa_comments.residents where user_id=u for update;
  if not found or p_expected_code is distinct from r.code then
    raise exception using errcode='PT428',message='identity_changed'; end if;
  select * into receipt from machimoa_comments.requests where resident_id=r.id and request_id=p_request_id;
  if found then
    if receipt.original_curation_id<>p_curation_id or receipt.body_digest<>sha256(convert_to(body,'UTF8')) then
      raise exception using errcode='PT409',message='request_conflict'; end if;
    select * into c from machimoa_comments.comments where id=receipt.comment_id;
    return jsonb_build_object('outcome','accepted','commentId',c.id,'state',c.state);
  end if;
  stamp:=clock_timestamp();
  if r.last_posted_at is not null and stamp<r.last_posted_at+interval '30 seconds' then
    raise exception using errcode='PT429',message='rate_limited'; end if;
  insert into machimoa_comments.comments(resident_id,curation_id,original_curation_id,body,created_at)
    values(r.id,p_curation_id,p_curation_id,body,stamp) returning * into c;
  insert into machimoa_comments.requests values(r.id,p_request_id,p_curation_id,sha256(convert_to(body,'UTF8')),c.id);
  update machimoa_comments.residents set last_posted_at=stamp where id=r.id;
  return jsonb_build_object('outcome','accepted','commentId',c.id,'state',c.state);
end $f$;
create function machimoa_comments.request_state(p_curation_id uuid,p_request_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $f$
declare c machimoa_comments.comments;
begin
  if auth.uid() is null then raise exception using errcode='PT401',message='authentication_required'; end if;
  if p_request_id is null then raise exception using errcode='22023',message='invalid_request'; end if;
  perform machimoa_comments.require_content(p_curation_id);
  select c1.* into c from machimoa_comments.requests q join machimoa_comments.residents r on r.id=q.resident_id
    join machimoa_comments.comments c1 on c1.id=q.comment_id
    where r.user_id=auth.uid() and q.request_id=p_request_id and q.original_curation_id=p_curation_id;
  if not found then return jsonb_build_object('outcome','absent'); end if;
  return jsonb_build_object('outcome','accepted','commentId',c.id,'state',c.state);
end $f$;
create function machimoa_comments.remove_comment(p_curation_id uuid,p_comment_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $f$
declare c machimoa_comments.comments;
begin
  if auth.uid() is null then raise exception using errcode='PT401',message='authentication_required'; end if;
  perform machimoa_comments.require_content(p_curation_id,true);
  select c1.* into c from machimoa_comments.comments c1 join machimoa_comments.residents r on r.id=c1.resident_id
    where c1.id=p_comment_id and c1.curation_id=p_curation_id and r.user_id=auth.uid() for update of c1;
  if not found then raise exception using errcode='PT404',message='information_unavailable'; end if;
  update machimoa_comments.comments set state='deleted',body=null,deleted_at=coalesce(deleted_at,clock_timestamp()) where id=c.id;
  return jsonb_build_object('outcome','deleted');
end $f$;
create function machimoa_comments.hide_comment(p_curation_id uuid,p_comment_id uuid,p_actor uuid)
returns jsonb language plpgsql security definer set search_path='' as $f$
declare c machimoa_comments.comments; stamp timestamptz:=clock_timestamp();
begin
  -- Only service_role can execute this helper/wrapper. Actor is supplied after
  -- the application's existing requireAdmin check, never by the browser.
  if p_actor is null or not exists(select 1 from auth.users where id=p_actor) then
    raise exception using errcode='PT403',message='forbidden'; end if;
  perform machimoa_comments.require_content(p_curation_id,true);
  select * into c from machimoa_comments.comments where id=p_comment_id and curation_id=p_curation_id for update;
  if not found or c.state='deleted' then raise exception using errcode='PT404',message='information_unavailable'; end if;
  if c.state='live' then
    update machimoa_comments.comments set state='hidden',hidden_at=stamp,hidden_until=stamp+interval '7 days',hidden_by=p_actor where id=c.id;
  end if;
  return jsonb_build_object('outcome','hidden');
end $f$;
create function machimoa_comments.purge_hidden(p_limit integer default 100)
returns integer language plpgsql security definer set search_path='' as $f$
declare affected integer;
begin
  if p_limit is null or p_limit<1 or p_limit>500 then raise exception using errcode='22023',message='invalid_limit'; end if;
  with expired as (select id from machimoa_comments.comments where state='hidden' and body is not null
      and hidden_until<=clock_timestamp() order by hidden_until,id limit p_limit for update skip locked)
  update machimoa_comments.comments c set body=null from expired where c.id=expired.id;
  get diagnostics affected=row_count;
  return affected;
end $f$;
create function public.list_information_comments(p_curation_id uuid,p_before_at timestamptz default null,p_before_id uuid default null)
returns jsonb language sql stable security invoker set search_path='' as $f$ select machimoa_comments.list(p_curation_id,p_before_at,p_before_id); $f$;
create function public.prepare_comment_resident(p_curation_id uuid)
returns jsonb language sql security invoker set search_path='' as $f$ select machimoa_comments.prepare(p_curation_id); $f$;
create function public.create_information_comment(p_curation_id uuid,p_request_id uuid,p_body text,p_expected_code text)
returns jsonb language sql security invoker set search_path='' as $f$ select machimoa_comments.create_comment(p_curation_id,p_request_id,p_body,p_expected_code); $f$;
create function public.information_comment_request_state(p_curation_id uuid,p_request_id uuid)
returns jsonb language sql stable security invoker set search_path='' as $f$ select machimoa_comments.request_state(p_curation_id,p_request_id); $f$;
create function public.remove_information_comment(p_curation_id uuid,p_comment_id uuid)
returns jsonb language sql security invoker set search_path='' as $f$ select machimoa_comments.remove_comment(p_curation_id,p_comment_id); $f$;
create function public.admin_hide_information_comment(p_curation_id uuid,p_comment_id uuid,p_actor uuid)
returns jsonb language sql security invoker set search_path='' as $f$ select machimoa_comments.hide_comment(p_curation_id,p_comment_id,p_actor); $f$;
create function public.purge_expired_hidden_information_comments(p_limit integer default 100)
returns integer language sql security invoker set search_path='' as $f$ select machimoa_comments.purge_hidden(p_limit); $f$;
revoke all on all functions in schema machimoa_comments from public,anon,authenticated,service_role;
revoke all on function public.list_information_comments(uuid,timestamptz,uuid),public.prepare_comment_resident(uuid),
  public.create_information_comment(uuid,uuid,text,text),public.information_comment_request_state(uuid,uuid),
  public.remove_information_comment(uuid,uuid),public.admin_hide_information_comment(uuid,uuid,uuid),
  public.purge_expired_hidden_information_comments(integer) from public,anon,authenticated,service_role;
grant execute on function public.list_information_comments(uuid,timestamptz,uuid),machimoa_comments.list(uuid,timestamptz,uuid) to anon,authenticated;
grant execute on function public.prepare_comment_resident(uuid),public.create_information_comment(uuid,uuid,text,text),
  public.information_comment_request_state(uuid,uuid),public.remove_information_comment(uuid,uuid),
  machimoa_comments.prepare(uuid),machimoa_comments.create_comment(uuid,uuid,text,text),
  machimoa_comments.request_state(uuid,uuid),machimoa_comments.remove_comment(uuid,uuid) to authenticated;
grant execute on function public.admin_hide_information_comment(uuid,uuid,uuid),public.purge_expired_hidden_information_comments(integer),
  machimoa_comments.hide_comment(uuid,uuid,uuid),machimoa_comments.purge_hidden(integer) to service_role;

insert into machimoa_comments.install_guard(singleton,fingerprint)
select true,jsonb_build_object(
 'schema',(select jsonb_build_array(nspowner::regrole::text,nspacl::text) from pg_namespace where nspname='machimoa_comments'),
 'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n')),p.proacl::text,p.proowner::regrole::text) order by p.oid::regprocedure::text) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_comments' or (n.nspname='public' and p.proname in ('list_information_comments','prepare_comment_resident','create_information_comment','information_comment_request_state','remove_information_comment','admin_hide_information_comment','purge_expired_hidden_information_comments'))),
 'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relowner::regrole::text,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attacl::text,pg_get_expr(d.adbin,d.adrelid)) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where n.nspname='machimoa_comments' and a.attnum>0 and not a.attisdropped),
 'constraints',(select jsonb_agg(jsonb_build_array(c.relname,q.conname,pg_get_constraintdef(q.oid)) order by c.relname,q.conname) from pg_constraint q join pg_class c on c.oid=q.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'indexes',(select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'policies',(select jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polroles::text,p.polqual::text,p.polwithcheck::text,p.polpermissive) order by c.relname,p.polname) from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'triggers',(select jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) order by c.relname,t.tgname) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments' and not t.tgisinternal)
);
notify pgrst,'reload schema';
commit;
