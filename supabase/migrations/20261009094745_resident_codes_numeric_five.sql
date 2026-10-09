-- One-time display-code transition; stable resident IDs and receipts survive.
begin;
lock table machimoa_comments.residents,machimoa_comments.comments,machimoa_comments.requests,machimoa_comments.install_guard in access exclusive mode;
do $guard$
declare actual jsonb;
begin
 if current_user<>'postgres' then raise exception 'requires postgres'; end if;
 if to_regclass('machimoa_comments.numeric_code_guard') is not null or to_regclass('machimoa_comments.numeric_code_backup') is not null
  or to_regprocedure('machimoa_comments.random_numeric_code()') is not null
  or to_regprocedure('machimoa_comments.numeric_records_fingerprint()') is not null then raise exception 'numeric code contract name collision'; end if;
 if (select count(*) from machimoa_comments.install_guard)<>1 then raise exception 'missing comment predecessor'; end if;
select jsonb_build_object(
 'schema',(select jsonb_build_array(nspowner::regrole::text,nspacl::text) from pg_namespace where nspname='machimoa_comments'),
 'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n')),p.proacl::text,p.proowner::regrole::text) order by p.oid::regprocedure::text) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_comments' or (n.nspname='public' and p.proname in ('list_information_comments','prepare_comment_resident','create_information_comment','information_comment_request_state','remove_information_comment','admin_hide_information_comment','purge_expired_hidden_information_comments'))),
 'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relowner::regrole::text,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attacl::text,pg_get_expr(d.adbin,d.adrelid)) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where n.nspname='machimoa_comments' and a.attnum>0 and not a.attisdropped),
 'constraints',(select jsonb_agg(jsonb_build_array(c.relname,q.conname,pg_get_constraintdef(q.oid)) order by c.relname,q.conname) from pg_constraint q join pg_class c on c.oid=q.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'indexes',(select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'policies',(select jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polroles::text,p.polqual::text,p.polwithcheck::text,p.polpermissive) order by c.relname,p.polname) from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'triggers',(select jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) order by c.relname,t.tgname) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments' and not t.tgisinternal)
) into actual;
 if actual is distinct from (select fingerprint from machimoa_comments.install_guard where singleton)
  or md5(actual::text)<>'b925dc54c2a24fc98885fe7ecc6e2a16' then raise exception 'unexpected comment predecessor'; end if;
 if not exists(select 1 from pg_proc p join pg_language l on l.oid=p.prolang
  where p.oid=to_regprocedure('machimoa_saved.is_savable(public.curations)')
  and md5(replace(p.prosrc,E'\r\n',E'\n'))='8ee14877d4efde127ca39106cbb0cb66'
  and p.prorettype='boolean'::regtype and l.lanname='sql' and p.provolatile='i' and not p.prosecdef
  and p.proowner='postgres'::regrole and p.proconfig=array['search_path=""']::text[])
  or not exists(select 1 from pg_proc where oid=to_regprocedure('auth.uid()') and prorettype='uuid'::regtype)
  or to_regclass('auth.users') is null then raise exception 'unexpected eligibility/auth predecessor'; end if;
 if (select count(*) from machimoa_comments.residents)>100000 then raise exception 'resident numeric code space insufficient'; end if;
end $guard$;
create table machimoa_comments.numeric_code_backup(
 resident_id uuid primary key references machimoa_comments.residents(id),
 old_code text not null unique check(old_code ~ '^[A-HJKMNP-Z2-9]{6}$'),
 new_code text not null unique check(new_code ~ '^[0-9]{5}$')
);
create table machimoa_comments.numeric_code_guard(
 singleton boolean primary key check(singleton),original_fingerprint jsonb not null,original_prepare text not null,
 installed_fingerprint jsonb,records_fingerprint text
);
alter table machimoa_comments.numeric_code_backup enable row level security;
alter table machimoa_comments.numeric_code_guard enable row level security;
revoke all on machimoa_comments.numeric_code_backup,machimoa_comments.numeric_code_guard from public,anon,authenticated,service_role;
insert into machimoa_comments.numeric_code_guard(singleton,original_fingerprint,original_prepare)
 select true,fingerprint,pg_get_functiondef('machimoa_comments.prepare(uuid)'::regprocedure) from machimoa_comments.install_guard where singleton;
-- Finite random permutation of the complete pool: unique assignment even near capacity.
-- Random scores are independent of account/resident IDs; no sequential codes.
with pool as materialized(
 select lpad(value::text,5,'0') code,gen_random_uuid() random_order from generate_series(0,99999) value
), codes as(select code,row_number() over(order by random_order,code) position from pool),
 residents as(select id,code,row_number() over(order by id) position from machimoa_comments.residents)
insert into machimoa_comments.numeric_code_backup(resident_id,old_code,new_code)
 select r.id,r.code,c.code from residents r join codes c using(position);
alter table machimoa_comments.residents drop constraint residents_code_check;
update machimoa_comments.residents r set code=b.new_code from machimoa_comments.numeric_code_backup b where b.resident_id=r.id;
alter table machimoa_comments.residents add constraint residents_code_check check(code ~ '^[0-9]{5}$');
create function machimoa_comments.random_numeric_code()
returns text language plpgsql volatile set search_path='' as $f$
declare candidate text:='';raw bytea;b integer;i integer;round integer;
begin
 -- Bounded rejection sampling; 250 is divisible by ten, eliminating modulo bias.
 for round in 1..16 loop
  raw:=uuid_send(gen_random_uuid());
  for i in 0..5 loop
   b:=get_byte(raw,i);
   if b<250 then candidate:=candidate||(b%10)::text; end if;
   if char_length(candidate)=5 then return candidate; end if;
  end loop;
 end loop;
 raise exception using errcode='PT503',message='resident_unavailable';
end $f$;
revoke all on function machimoa_comments.random_numeric_code() from public,anon,authenticated,service_role;
create or replace function machimoa_comments.prepare(p_curation_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $f$
declare u uuid:=auth.uid(); r machimoa_comments.residents; candidate text; attempt integer;
begin
  if u is null then raise exception using errcode='PT401',message='authentication_required'; end if;
  perform machimoa_comments.require_content(p_curation_id,true);
  perform 1 from auth.users where id=u for key share;
  if not found then raise exception using errcode='PT401',message='authentication_required'; end if;
  perform pg_advisory_xact_lock(1900919,hashtext(u::text));
  select * into r from machimoa_comments.residents where user_id=u;
  if found then return jsonb_build_object('code',r.code); end if;
  for attempt in 1..10 loop
    candidate:=machimoa_comments.random_numeric_code();
    begin
      insert into machimoa_comments.residents(user_id,code) values(u,candidate) returning * into r;
      return jsonb_build_object('code',r.code);
    exception when unique_violation then null; end;
  end loop;
  raise exception using errcode='PT503',message='resident_unavailable';
end $f$;

-- A digest only: no copied comment bodies or social profiles.
create function machimoa_comments.numeric_records_fingerprint()
returns text language sql stable set search_path='' as $f$
 select md5(jsonb_build_array(
  (select md5(coalesce(string_agg(md5(to_jsonb(r)::text),'' order by id),'')) from machimoa_comments.residents r),
  (select md5(coalesce(string_agg(md5(to_jsonb(c)::text),'' order by id),'')) from machimoa_comments.comments c),
  (select md5(coalesce(string_agg(md5(to_jsonb(q)::text),'' order by resident_id,request_id),'')) from machimoa_comments.requests q),
  (select md5(coalesce(string_agg(md5(to_jsonb(b)::text),'' order by resident_id),'')) from machimoa_comments.numeric_code_backup b)
 )::text);
$f$;
revoke all on function machimoa_comments.numeric_records_fingerprint() from public,anon,authenticated,service_role;
update machimoa_comments.numeric_code_guard set installed_fingerprint=(select jsonb_build_object(
 'schema',(select jsonb_build_array(nspowner::regrole::text,nspacl::text) from pg_namespace where nspname='machimoa_comments'),
 'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n')),p.proacl::text,p.proowner::regrole::text) order by p.oid::regprocedure::text) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_comments' or (n.nspname='public' and p.proname in ('list_information_comments','prepare_comment_resident','create_information_comment','information_comment_request_state','remove_information_comment','admin_hide_information_comment','purge_expired_hidden_information_comments'))),
 'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relowner::regrole::text,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attacl::text,pg_get_expr(d.adbin,d.adrelid)) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where n.nspname='machimoa_comments' and a.attnum>0 and not a.attisdropped),
 'constraints',(select jsonb_agg(jsonb_build_array(c.relname,q.conname,pg_get_constraintdef(q.oid)) order by c.relname,q.conname) from pg_constraint q join pg_class c on c.oid=q.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'indexes',(select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'policies',(select jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polroles::text,p.polqual::text,p.polwithcheck::text,p.polpermissive) order by c.relname,p.polname) from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'triggers',(select jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) order by c.relname,t.tgname) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments' and not t.tgisinternal)
)),records_fingerprint=machimoa_comments.numeric_records_fingerprint() where singleton;
notify pgrst,'reload schema';
commit;
