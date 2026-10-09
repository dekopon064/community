-- Public count and one-level replies. Existing comments/identities/receipts remain intact.
begin;
lock table machimoa_comments.residents,machimoa_comments.comments,machimoa_comments.requests,
 machimoa_comments.numeric_code_guard in access exclusive mode;
do $guard$
declare actual jsonb;
begin
 if current_user<>'postgres' then raise exception 'requires postgres'; end if;
 if to_regclass('machimoa_comments.thread_guard') is not null then raise exception 'thread contract name collision'; end if;
select jsonb_build_object(
 'schema',(select jsonb_build_array(nspowner::regrole::text,nspacl::text) from pg_namespace where nspname='machimoa_comments'),
 'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n')),p.proacl::text,p.proowner::regrole::text) order by p.oid::regprocedure::text) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_comments' or (n.nspname='public' and p.proname in ('list_information_comment_threads','list_information_comment_replies','count_information_comments','create_information_comment_reply','list_information_comments','prepare_comment_resident','create_information_comment','information_comment_request_state','remove_information_comment','admin_hide_information_comment','purge_expired_hidden_information_comments'))),
 'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relowner::regrole::text,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attacl::text,pg_get_expr(d.adbin,d.adrelid)) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where n.nspname='machimoa_comments' and a.attnum>0 and not a.attisdropped),
 'constraints',(select jsonb_agg(jsonb_build_array(c.relname,q.conname,pg_get_constraintdef(q.oid)) order by c.relname,q.conname) from pg_constraint q join pg_class c on c.oid=q.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'indexes',(select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'policies',(select jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polroles::text,p.polqual::text,p.polwithcheck::text,p.polpermissive) order by c.relname,p.polname) from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'triggers',(select jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) order by c.relname,t.tgname) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments' and not t.tgisinternal)
) into actual;
 if actual is distinct from (select installed_fingerprint from machimoa_comments.numeric_code_guard where singleton)
  or md5(actual::text)<>'6f9734075c5cae07f0caee62cc400ff5' then raise exception 'unexpected numeric comment predecessor'; end if;
 if not exists(select 1 from pg_proc where oid=to_regprocedure('machimoa_saved.is_savable(public.curations)')
   and md5(replace(prosrc,E'\r\n',E'\n'))='8ee14877d4efde127ca39106cbb0cb66'
   and proowner='postgres'::regrole and proconfig=array['search_path=""']::text[] and not prosecdef)
 then raise exception 'unexpected eligibility predecessor'; end if;
end $guard$;
create table machimoa_comments.thread_guard(singleton boolean primary key check(singleton),
 original_fingerprint jsonb not null,original_definitions jsonb not null,installed_fingerprint jsonb,records_fingerprint text);
alter table machimoa_comments.thread_guard enable row level security;
revoke all on machimoa_comments.thread_guard from public,anon,authenticated,service_role;
insert into machimoa_comments.thread_guard(singleton,original_fingerprint,original_definitions)
 select true,installed_fingerprint,jsonb_build_object(
  'machimoa_comments.list(uuid,timestamp with time zone,uuid)',pg_get_functiondef('machimoa_comments.list(uuid,timestamptz,uuid)'::regprocedure),
  'machimoa_comments.create_comment(uuid,uuid,text,text)',pg_get_functiondef('machimoa_comments.create_comment(uuid,uuid,text,text)'::regprocedure))
 from machimoa_comments.numeric_code_guard where singleton;
alter table machimoa_comments.comments add column parent_id uuid;
alter table machimoa_comments.comments add constraint comments_id_content_unique unique(id,original_curation_id);
alter table machimoa_comments.comments add constraint comments_parent_content_fk foreign key(parent_id,original_curation_id)
 references machimoa_comments.comments(id,original_curation_id);
alter table machimoa_comments.comments add constraint comments_not_self check(parent_id is distinct from id);
create index comments_root_page_idx on machimoa_comments.comments(curation_id,created_at desc,id desc) where parent_id is null;
create index comments_reply_page_idx on machimoa_comments.comments(parent_id,created_at,id) where state='live';
create function machimoa_comments.validate_parent() returns trigger language plpgsql set search_path='' as $f$
begin
 if TG_OP='UPDATE' and (new.parent_id is distinct from old.parent_id or new.original_curation_id is distinct from old.original_curation_id)
 then raise exception using errcode='22023',message='immutable_comment_thread'; end if;
 if new.parent_id is not null then
  perform 1 from machimoa_comments.comments where id=new.parent_id and parent_id is null and original_curation_id=new.original_curation_id for key share;
  if not found then raise exception using errcode='22023',message='invalid_comment_parent'; end if;
 end if;
 return new;
end $f$;
create trigger comments_parent_guard before insert or update of parent_id,original_curation_id on machimoa_comments.comments
 for each row execute function machimoa_comments.validate_parent();
create or replace function machimoa_comments.list(p_curation_id uuid,p_before_at timestamptz default null,p_before_id uuid default null)
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
    where c.curation_id=p_curation_id and c.state='live' and c.parent_id is null
      and (p_before_at is null or (c.created_at,c.id)<(p_before_at,p_before_id))
    order by c.created_at desc,c.id desc limit 21
  ) select coalesce(jsonb_agg(jsonb_build_object('id',id,'residentCode',code,'body',body,
      'createdAt',to_char(created_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
      'canDelete',coalesce(own,false)) order by position) filter(where position<=20),'[]'::jsonb),
    case when count(*)>20 then (select jsonb_build_object('at',to_char(created_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'id',id) from page where position=20) else null end
    into items,next_cursor from page;
  return jsonb_build_object('items',items,'next',next_cursor,'code',viewer_code);
end $f$;
create function machimoa_comments.create_thread_comment(p_curation_id uuid,p_request_id uuid,p_body text,p_expected_code text,p_parent_id uuid)
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
    if receipt.original_curation_id<>p_curation_id or receipt.body_digest<>sha256(convert_to(body,'UTF8')) or p_parent_id is distinct from (select parent_id from machimoa_comments.comments where id=receipt.comment_id) then
      raise exception using errcode='PT409',message='request_conflict'; end if;
    select * into c from machimoa_comments.comments where id=receipt.comment_id;
    return jsonb_build_object('outcome','accepted','commentId',c.id,'state',c.state);
  end if;
  if p_parent_id is not null then
    perform 1 from machimoa_comments.comments where id=p_parent_id and curation_id=p_curation_id and parent_id is null and state='live' for update;
    if not found then raise exception using errcode='PT410',message='parent_unavailable'; end if;
  end if;
  stamp:=clock_timestamp();
  if r.last_posted_at is not null and stamp<r.last_posted_at+interval '30 seconds' then
    raise exception using errcode='PT429',message='rate_limited'; end if;
  insert into machimoa_comments.comments(resident_id,curation_id,original_curation_id,body,created_at,parent_id)
    values(r.id,p_curation_id,p_curation_id,body,stamp,p_parent_id) returning * into c;
  insert into machimoa_comments.requests values(r.id,p_request_id,p_curation_id,sha256(convert_to(body,'UTF8')),c.id);
  update machimoa_comments.residents set last_posted_at=stamp where id=r.id;
  return jsonb_build_object('outcome','accepted','commentId',c.id,'state',c.state);
end $f$;

create or replace function machimoa_comments.create_comment(p_curation_id uuid,p_request_id uuid,p_body text,p_expected_code text)
returns jsonb language sql security definer set search_path='' as $f$
 select machimoa_comments.create_thread_comment(p_curation_id,p_request_id,p_body,p_expected_code,null); $f$;
create function machimoa_comments.thread_list(p_curation_id uuid,p_parent_id uuid,p_at timestamptz,p_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $f$
declare items jsonb;next_cursor jsonb;viewer_code text;parent_state text;
begin
 if (p_at is null)<>(p_id is null) or (p_at is not null and not isfinite(p_at)) then
  raise exception using errcode='22023',message='invalid_cursor'; end if;
 perform machimoa_comments.require_content(p_curation_id);
 if p_parent_id is not null then
  select state into parent_state from machimoa_comments.comments where id=p_parent_id and curation_id=p_curation_id and parent_id is null
   and (state='live' or exists(select 1 from machimoa_comments.comments child where child.parent_id=p_parent_id and child.state='live'));
  if not found then raise exception using errcode='PT404',message='information_unavailable'; end if;
 end if;
 select code into viewer_code from machimoa_comments.residents where user_id=auth.uid();
 with page as materialized (
  select c.*,r.code,r.user_id=auth.uid() own,
   (select count(*) from machimoa_comments.comments child where child.parent_id=c.id and child.state='live') reply_count
  from machimoa_comments.comments c join machimoa_comments.residents r on r.id=c.resident_id
  where c.curation_id=p_curation_id and (
   (p_parent_id is null and c.parent_id is null and (c.state='live' or exists(select 1 from machimoa_comments.comments child where child.parent_id=c.id and child.state='live'))
    and (p_at is null or (c.created_at,c.id)<(p_at,p_id))) or
   (p_parent_id is not null and c.parent_id=p_parent_id and c.state='live' and (p_at is null or (c.created_at,c.id)>(p_at,p_id))))
  order by case when p_parent_id is null then c.created_at end desc,case when p_parent_id is null then c.id end desc,
   case when p_parent_id is not null then c.created_at end,case when p_parent_id is not null then c.id end limit 21
 ), numbered as (select *,row_number() over(order by
   case when p_parent_id is null then created_at end desc,case when p_parent_id is null then id end desc,
   case when p_parent_id is not null then created_at end,case when p_parent_id is not null then id end) position from page)
 select coalesce(jsonb_agg(jsonb_build_object('id',id,'state',state,'residentCode',case when state='live' then code end,
  'body',case when state='live' then body end,'createdAt',to_char(created_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'canDelete',state='live' and coalesce(own,false),'replyCount',reply_count) order by position) filter(where position<=20),'[]'::jsonb),
  case when count(*)>20 then (select jsonb_build_object('at',to_char(created_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'id',id) from numbered where position=20) end
 into items,next_cursor from numbered;
 return jsonb_build_object('items',items,'next',next_cursor,'code',viewer_code,'parentState',parent_state);
end $f$;
create function machimoa_comments.public_count(p_curation_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $f$
begin
 perform machimoa_comments.require_content(p_curation_id);
 return jsonb_build_object('count',(select count(*) from machimoa_comments.comments where curation_id=p_curation_id and state='live'));
end $f$;
create function public.list_information_comment_threads(p_curation_id uuid,p_before_at timestamptz default null,p_before_id uuid default null)
returns jsonb language sql stable security invoker set search_path='' as $f$ select machimoa_comments.thread_list(p_curation_id,null,p_before_at,p_before_id); $f$;
create function public.list_information_comment_replies(p_curation_id uuid,p_parent_id uuid,p_after_at timestamptz default null,p_after_id uuid default null)
returns jsonb language sql stable security invoker set search_path='' as $f$ select machimoa_comments.thread_list(p_curation_id,p_parent_id,p_after_at,p_after_id); $f$;
create function public.count_information_comments(p_curation_id uuid)
returns jsonb language sql stable security invoker set search_path='' as $f$ select machimoa_comments.public_count(p_curation_id); $f$;
create function public.create_information_comment_reply(p_curation_id uuid,p_request_id uuid,p_body text,p_expected_code text,p_parent_id uuid)
returns jsonb language plpgsql security invoker set search_path='' as $f$
begin
 if p_parent_id is null then raise exception using errcode='22023',message='invalid_comment_parent'; end if;
 return machimoa_comments.create_thread_comment(p_curation_id,p_request_id,p_body,p_expected_code,p_parent_id);
end $f$;
revoke all on function machimoa_comments.validate_parent(),machimoa_comments.create_thread_comment(uuid,uuid,text,text,uuid),
 machimoa_comments.thread_list(uuid,uuid,timestamptz,uuid),machimoa_comments.public_count(uuid),
 public.list_information_comment_threads(uuid,timestamptz,uuid),public.list_information_comment_replies(uuid,uuid,timestamptz,uuid),
 public.count_information_comments(uuid),public.create_information_comment_reply(uuid,uuid,text,text,uuid) from public,anon,authenticated,service_role;
grant execute on function machimoa_comments.thread_list(uuid,uuid,timestamptz,uuid),machimoa_comments.public_count(uuid),
 public.list_information_comment_threads(uuid,timestamptz,uuid),public.list_information_comment_replies(uuid,uuid,timestamptz,uuid),
 public.count_information_comments(uuid) to anon,authenticated;
grant execute on function machimoa_comments.create_thread_comment(uuid,uuid,text,text,uuid),public.create_information_comment_reply(uuid,uuid,text,text,uuid) to authenticated;
update machimoa_comments.thread_guard set installed_fingerprint=(select jsonb_build_object(
 'schema',(select jsonb_build_array(nspowner::regrole::text,nspacl::text) from pg_namespace where nspname='machimoa_comments'),
 'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n')),p.proacl::text,p.proowner::regrole::text) order by p.oid::regprocedure::text) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_comments' or (n.nspname='public' and p.proname in ('list_information_comment_threads','list_information_comment_replies','count_information_comments','create_information_comment_reply','list_information_comments','prepare_comment_resident','create_information_comment','information_comment_request_state','remove_information_comment','admin_hide_information_comment','purge_expired_hidden_information_comments'))),
 'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relowner::regrole::text,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attacl::text,pg_get_expr(d.adbin,d.adrelid)) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where n.nspname='machimoa_comments' and a.attnum>0 and not a.attisdropped),
 'constraints',(select jsonb_agg(jsonb_build_array(c.relname,q.conname,pg_get_constraintdef(q.oid)) order by c.relname,q.conname) from pg_constraint q join pg_class c on c.oid=q.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'indexes',(select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'policies',(select jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polroles::text,p.polqual::text,p.polwithcheck::text,p.polpermissive) order by c.relname,p.polname) from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'triggers',(select jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) order by c.relname,t.tgname) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments' and not t.tgisinternal)
)),records_fingerprint=machimoa_comments.numeric_records_fingerprint() where singleton;
notify pgrst,'reload schema';
commit;
