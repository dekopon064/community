-- Corrective: enforce contact-email retention independently of body retention.
-- Public notice remains a maximum of 90 days. Internal safety cutoff is 88 days
-- from first submission receipt (created_at), not from a later purge clock.
--
-- Do not apply this file without a separate approval. This migration must
-- not enable scheduled jobs, change Edge Functions, or alter
-- mark_feedback_spam / delete_feedback.
--
-- Supabase CLI 2.116.0 linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.
-- session_user is an exact allowlist: postgres or cli_login_postgres.

begin;

do $guard$
declare
  v_schema_owner pg_catalog.name;
  v_table_missing pg_catalog.text;
  v_missing_owner pg_catalog.text;
  v_schema_acl_bad pg_catalog.text;
  v_table_acl_bad pg_catalog.text;
  v_submit pg_catalog.regprocedure;
  v_purge pg_catalog.regprocedure;
  v_submit_count pg_catalog.int4;
  v_purge_count pg_catalog.int4;
  v_owner pg_catalog.name;
  v_secdef pg_catalog.bool;
  v_config pg_catalog.text[];
  v_service_role pg_catalog.oid;
  v_fn_acl_bad pg_catalog.text;
  v_expires_exists pg_catalog.bool;
begin
  if current_user <> 'postgres'
     or session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'contact retention migration must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  if pg_catalog.to_regnamespace('machimoa_feedback') is null then
    raise exception 'schema machimoa_feedback is missing';
  end if;

  select pg_catalog.pg_get_userbyid(n.nspowner)
    into v_schema_owner
  from pg_catalog.pg_namespace as n
  where n.nspname = 'machimoa_feedback';

  if v_schema_owner is distinct from 'postgres' then
    raise exception
      'machimoa_feedback must be owned by postgres, got %',
      v_schema_owner;
  end if;

  select pg_catalog.string_agg(
           x.privilege_type
             || ':grantee='
             || x.grantee::pg_catalog.text,
           ', '
           order by x.privilege_type, x.grantee
         )
    into v_schema_acl_bad
  from pg_catalog.pg_namespace as n
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      n.nspacl,
      pg_catalog.acldefault('n'::pg_catalog."char", n.nspowner)
    )
  ) as x
  where n.nspname = 'machimoa_feedback'
    and x.privilege_type in ('USAGE', 'CREATE')
    and x.grantee is distinct from n.nspowner;

  if v_schema_acl_bad is not null then
    raise exception
      'machimoa_feedback has unexpected direct schema ACL (%)',
      v_schema_acl_bad;
  end if;

  select pg_catalog.string_agg(t.relname, ', ' order by t.relname)
    into v_table_missing
  from (
    values
      ('submissions'::pg_catalog.name),
      ('contacts'),
      ('rate_limit_events'),
      ('purge_runs')
  ) as t(relname)
  where pg_catalog.to_regclass('machimoa_feedback.' || t.relname) is null;

  if v_table_missing is not null then
    raise exception 'expected feedback tables are missing (%)', v_table_missing;
  end if;

  select pg_catalog.string_agg(c.relname, ', ' order by c.relname)
    into v_missing_owner
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and c.relname in (
      'submissions',
      'contacts',
      'rate_limit_events',
      'purge_runs'
    )
    and pg_catalog.pg_get_userbyid(c.relowner) is distinct from 'postgres';

  if v_missing_owner is not null then
    raise exception
      'feedback tables must be owned by postgres (%)',
      v_missing_owner;
  end if;

  select pg_catalog.string_agg(
           c.relname
             || ':'
             || x.privilege_type
             || ':grantee='
             || x.grantee::pg_catalog.text,
           ', '
           order by c.relname, x.privilege_type, x.grantee
         )
    into v_table_acl_bad
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      c.relacl,
      pg_catalog.acldefault('r'::pg_catalog."char", c.relowner)
    )
  ) as x
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and c.relname in (
      'submissions',
      'contacts',
      'rate_limit_events',
      'purge_runs'
    )
    and x.grantee is distinct from c.relowner;

  if v_table_acl_bad is not null then
    raise exception
      'feedback tables have unexpected direct ACL (%)',
      v_table_acl_bad;
  end if;

  select pg_catalog.count(*)::pg_catalog.int4
    into v_submit_count
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'submit_feedback';

  select pg_catalog.count(*)::pg_catalog.int4
    into v_purge_count
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'purge_feedback';

  if v_submit_count is distinct from 1
     or v_purge_count is distinct from 1 then
    raise exception
      'expected exactly one submit_feedback and one purge_feedback';
  end if;

  v_submit := pg_catalog.to_regprocedure(
    'public.submit_feedback(text,text,text,text,boolean,boolean,boolean,text,text,bytea,bytea)'
  );
  v_purge := pg_catalog.to_regprocedure(
    'public.purge_feedback()'
  );

  if v_submit is null or v_purge is null then
    raise exception
      'required submit_feedback or purge_feedback signature is missing';
  end if;

  select pg_catalog.pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
    into v_owner, v_secdef, v_config
  from pg_catalog.pg_proc as p
  where p.oid = v_submit;

  if v_owner is distinct from 'postgres'
     or v_secdef is distinct from true
     or v_config is distinct from array['search_path=""'::pg_catalog.text]
  then
    raise exception
      'submit_feedback must be postgres SECURITY DEFINER search_path=""';
  end if;

  select pg_catalog.pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
    into v_owner, v_secdef, v_config
  from pg_catalog.pg_proc as p
  where p.oid = v_purge;

  if v_owner is distinct from 'postgres'
     or v_secdef is distinct from true
     or v_config is distinct from array['search_path=""'::pg_catalog.text]
  then
    raise exception
      'purge_feedback must be postgres SECURITY DEFINER search_path=""';
  end if;

  select r.oid
    into v_service_role
  from pg_catalog.pg_roles as r
  where r.rolname = 'service_role';

  if v_service_role is null then
    raise exception 'role service_role is required';
  end if;

  select pg_catalog.string_agg(
           p.oid::pg_catalog.regprocedure::pg_catalog.text
             || ':EXECUTE:grantee='
             || x.grantee::pg_catalog.text
             || case
               when x.is_grantable then ':grant_option'
               else ''
             end,
           ', '
           order by 1
         )
    into v_fn_acl_bad
  from pg_catalog.pg_proc as p
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      p.proacl,
      pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
    )
  ) as x
  where p.oid = v_submit
    and x.privilege_type = 'EXECUTE'
    and x.grantee is distinct from p.proowner
    and x.grantee is distinct from v_service_role;

  if v_fn_acl_bad is not null then
    raise exception
      'submit_feedback has unexpected direct EXECUTE ACL (%)',
      v_fn_acl_bad;
  end if;

  if exists (
    select 1
    from pg_catalog.pg_proc as p
    cross join lateral pg_catalog.aclexplode(
      coalesce(
        p.proacl,
        pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
      )
    ) as x
    where p.oid = v_submit
      and x.privilege_type = 'EXECUTE'
      and x.grantee = v_service_role
      and x.is_grantable
  ) then
    raise exception
      'service_role must not have GRANT OPTION on submit_feedback';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_proc as p
    cross join lateral pg_catalog.aclexplode(
      coalesce(
        p.proacl,
        pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
      )
    ) as x
    where p.oid = v_submit
      and x.privilege_type = 'EXECUTE'
      and x.grantee = v_service_role
  ) then
    raise exception
      'service_role must have a direct EXECUTE grant on submit_feedback';
  end if;

  select pg_catalog.string_agg(
           p.oid::pg_catalog.regprocedure::pg_catalog.text
             || ':EXECUTE:grantee='
             || x.grantee::pg_catalog.text
             || case
               when x.is_grantable then ':grant_option'
               else ''
             end,
           ', '
           order by 1
         )
    into v_fn_acl_bad
  from pg_catalog.pg_proc as p
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      p.proacl,
      pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
    )
  ) as x
  where p.oid = v_purge
    and x.privilege_type = 'EXECUTE'
    and x.grantee is distinct from p.proowner;

  if v_fn_acl_bad is not null then
    raise exception
      'purge_feedback has unexpected direct EXECUTE ACL (%)',
      v_fn_acl_bad;
  end if;

  select exists (
    select 1
    from pg_catalog.pg_attribute as a
    join pg_catalog.pg_class as c
      on c.oid = a.attrelid
    join pg_catalog.pg_namespace as n
      on n.oid = c.relnamespace
    where n.nspname = 'machimoa_feedback'
      and c.relname = 'contacts'
      and a.attname = 'expires_at'
      and a.attnum > 0
      and not a.attisdropped
  )
    into v_expires_exists;

  if v_expires_exists then
    raise exception 'column contacts.expires_at already exists';
  end if;

  if pg_catalog.to_regclass('machimoa_feedback.contacts_expires_at_idx')
       is not null then
    raise exception
      'index machimoa_feedback.contacts_expires_at_idx already exists';
  end if;
end
$guard$;

alter table machimoa_feedback.contacts
  add column expires_at pg_catalog.timestamptz;

update machimoa_feedback.contacts as c
set expires_at = s.created_at + '88 days'::pg_catalog.interval
from machimoa_feedback.submissions as s
where c.submission_id = s.id;

do $backfill$
declare
  v_null_count pg_catalog.int4;
begin
  select pg_catalog.count(*)::pg_catalog.int4
    into v_null_count
  from machimoa_feedback.contacts as c
  where c.expires_at is null;

  if v_null_count is distinct from 0 then
    raise exception
      'contacts.expires_at backfill left null values (count=%)',
      v_null_count;
  end if;
end
$backfill$;

alter table machimoa_feedback.contacts
  alter column expires_at set not null;

create index contacts_expires_at_idx
  on machimoa_feedback.contacts (expires_at);

create or replace function public.submit_feedback(
  p_locale pg_catalog.text,
  p_feedback_type pg_catalog.text,
  p_topic pg_catalog.text,
  p_body pg_catalog.text,
  p_privacy_consent pg_catalog.bool,
  p_age_gate_accepted pg_catalog.bool,
  p_contact_consent pg_catalog.bool,
  p_email pg_catalog.text,
  p_privacy_notice_version pg_catalog.text,
  p_receipt_hmac pg_catalog.bytea,
  p_rate_hmac pg_catalog.bytea
)
returns table (
  submission_id pg_catalog.uuid,
  outcome pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_locale pg_catalog.text;
  v_type pg_catalog.text;
  v_topic pg_catalog.text;
  v_body pg_catalog.text;
  v_email pg_catalog.text;
  v_version pg_catalog.text;
  v_id pg_catalog.uuid;
  v_now pg_catalog.timestamptz;
begin
  v_locale := pg_catalog.btrim(coalesce(p_locale, ''));
  v_type := pg_catalog.btrim(coalesce(p_feedback_type, ''));
  v_topic := nullif(pg_catalog.btrim(coalesce(p_topic, '')), '');
  v_body := machimoa_feedback.normalize_feedback_body(p_body);
  v_version := pg_catalog.btrim(coalesce(p_privacy_notice_version, ''));
  v_email := nullif(pg_catalog.btrim(coalesce(p_email, '')), '');

  if coalesce(p_contact_consent, false) is not true then
    v_email := null;
  end if;

  if v_body is null
     or pg_catalog.char_length(v_body) < 10
     or pg_catalog.char_length(v_body) > 1000
     or v_locale not in ('ko', 'ja')
     or v_type not in (
       'hard_to_find_life_info',
       'product_opinion',
       'other_inquiry'
     )
     or (
       v_topic is not null
       and v_topic not in (
         'housing',
         'identity',
         'work',
         'education',
         'welfare',
         'participation',
         'other'
       )
     )
     or p_privacy_consent is distinct from true
     or p_age_gate_accepted is distinct from true
     or v_version !~ '^feedback-privacy-v[0-9]+$'
     or pg_catalog.char_length(v_version) > 64
     or pg_catalog.octet_length(p_receipt_hmac) is distinct from 32
     or pg_catalog.octet_length(p_rate_hmac) is distinct from 32
     or (
       v_email is not null
       and (
         pg_catalog.char_length(v_email) < 3
         or pg_catalog.char_length(v_email) > 254
         or v_email ~ '[[:space:]]'
         or v_email !~ '^[^@]+@[^@]+\.[^@]+$'
       )
     )
  then
    submission_id := null;
    outcome := 'rejected';
    return next;
    return;
  end if;

  if not machimoa_feedback.try_consume_rate_limit('submit', p_rate_hmac) then
    submission_id := null;
    outcome := 'rate_limited';
    return next;
    return;
  end if;

  v_now := pg_catalog.now();

  begin
    insert into machimoa_feedback.submissions (
      id,
      locale,
      feedback_type,
      topic,
      body,
      privacy_consent,
      age_gate_accepted,
      contact_consent,
      privacy_notice_version,
      status,
      receipt_hmac,
      created_at,
      expires_at
    )
    values (
      pg_catalog.gen_random_uuid(),
      v_locale,
      v_type,
      v_topic,
      v_body,
      true,
      true,
      coalesce(p_contact_consent, false),
      v_version,
      'normal',
      p_receipt_hmac,
      v_now,
      v_now + '178 days'::pg_catalog.interval
    )
    returning machimoa_feedback.submissions.id
      into v_id;

    if v_email is not null then
      insert into machimoa_feedback.contacts (
        submission_id,
        email,
        expires_at
      )
      values (
        v_id,
        v_email,
        v_now + '88 days'::pg_catalog.interval
      );
    end if;
  exception
    when unique_violation then
      submission_id := null;
      outcome := 'rejected';
      return next;
      return;
  end;

  submission_id := v_id;
  outcome := 'inserted';
  return next;
  return;
end
$function$;

alter function public.submit_feedback(
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.bool,
  pg_catalog.bool,
  pg_catalog.bool,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.bytea,
  pg_catalog.bytea
)
owner to postgres;

revoke all privileges
  on function public.submit_feedback(
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.bool,
    pg_catalog.bool,
    pg_catalog.bool,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.bytea,
    pg_catalog.bytea
  )
  from public, anon, authenticated, service_role;

grant execute
  on function public.submit_feedback(
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.bool,
    pg_catalog.bool,
    pg_catalog.bool,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.bytea,
    pg_catalog.bytea
  )
  to service_role;

create or replace function public.purge_feedback()
returns table (
  success pg_catalog.bool,
  deleted_submissions pg_catalog.int4,
  deleted_rate_limit_events pg_catalog.int4,
  error_code pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_started pg_catalog.timestamptz := pg_catalog.clock_timestamp();
  v_deleted_submissions pg_catalog.int4 := 0;
  v_deleted_rate_limit_events pg_catalog.int4 := 0;
  v_error_code pg_catalog.text;
  v_sqlstate pg_catalog.text;
begin
  begin
    delete from machimoa_feedback.contacts as c
    where c.expires_at <= pg_catalog.now();

    delete from machimoa_feedback.submissions as s
    where s.expires_at <= pg_catalog.now();
    get diagnostics v_deleted_submissions = row_count;

    delete from machimoa_feedback.rate_limit_events as e
    where e.created_at
      <= pg_catalog.now() - '48 hours'::pg_catalog.interval;
    get diagnostics v_deleted_rate_limit_events = row_count;

    delete from machimoa_feedback.purge_runs as r
    where r.started_at
      <= pg_catalog.now() - '29 days'::pg_catalog.interval;

    insert into machimoa_feedback.purge_runs (
      id,
      started_at,
      finished_at,
      success,
      deleted_submissions,
      deleted_rate_limit_events,
      error_code
    )
    values (
      pg_catalog.gen_random_uuid(),
      v_started,
      pg_catalog.clock_timestamp(),
      true,
      v_deleted_submissions,
      v_deleted_rate_limit_events,
      null
    );
  exception
    when query_canceled then
      v_deleted_submissions := 0;
      v_deleted_rate_limit_events := 0;
      v_error_code := 'query_canceled';
    when lock_not_available then
      v_deleted_submissions := 0;
      v_deleted_rate_limit_events := 0;
      v_error_code := 'lock_timeout';
    when deadlock_detected then
      v_deleted_submissions := 0;
      v_deleted_rate_limit_events := 0;
      v_error_code := 'lock_timeout';
    when others then
      v_deleted_submissions := 0;
      v_deleted_rate_limit_events := 0;
      get stacked diagnostics v_sqlstate = returned_sqlstate;
      if v_sqlstate = '57014' then
        v_error_code := 'query_canceled';
      elsif v_sqlstate in ('55P03', '40P01') then
        v_error_code := 'lock_timeout';
      else
        v_error_code := 'internal_error';
      end if;
  end;

  if v_error_code is not null then
    insert into machimoa_feedback.purge_runs (
      id,
      started_at,
      finished_at,
      success,
      deleted_submissions,
      deleted_rate_limit_events,
      error_code
    )
    values (
      pg_catalog.gen_random_uuid(),
      v_started,
      pg_catalog.clock_timestamp(),
      false,
      0,
      0,
      v_error_code
    );
  end if;

  success := (v_error_code is null);
  deleted_submissions := v_deleted_submissions;
  deleted_rate_limit_events := v_deleted_rate_limit_events;
  error_code := v_error_code;
  return next;
  return;
end
$function$;

alter function public.purge_feedback()
  owner to postgres;

revoke all privileges
  on function public.purge_feedback()
  from public, anon, authenticated, service_role;

do $post$
declare
  v_schema_owner pg_catalog.name;
  v_atttypid pg_catalog.oid;
  v_attnotnull pg_catalog.bool;
  v_format pg_catalog.text;
  v_index_ok pg_catalog.bool;
  v_missing_owner pg_catalog.text;
  v_schema_acl_bad pg_catalog.text;
  v_table_acl_bad pg_catalog.text;
  v_submit pg_catalog.regprocedure;
  v_purge pg_catalog.regprocedure;
  v_owner pg_catalog.name;
  v_secdef pg_catalog.bool;
  v_config pg_catalog.text[];
  v_service_role pg_catalog.oid;
  v_fn_acl_bad pg_catalog.text;
begin
  select pg_catalog.pg_get_userbyid(n.nspowner)
    into v_schema_owner
  from pg_catalog.pg_namespace as n
  where n.nspname = 'machimoa_feedback';

  if v_schema_owner is distinct from 'postgres' then
    raise exception
      'machimoa_feedback must be owned by postgres, got %',
      v_schema_owner;
  end if;

  select a.atttypid,
         a.attnotnull,
         pg_catalog.format_type(a.atttypid, a.atttypmod)
    into v_atttypid, v_attnotnull, v_format
  from pg_catalog.pg_attribute as a
  join pg_catalog.pg_class as c
    on c.oid = a.attrelid
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relname = 'contacts'
    and a.attname = 'expires_at'
    and a.attnum > 0
    and not a.attisdropped;

  if not found then
    raise exception 'column contacts.expires_at is missing';
  end if;

  if v_atttypid is distinct from 'pg_catalog.timestamptz'::pg_catalog.regtype
     or v_format is distinct from 'timestamp with time zone'
     or v_attnotnull is distinct from true
  then
    raise exception
      'contacts.expires_at must be timestamp with time zone NOT NULL';
  end if;

  select exists (
    select 1
    from pg_catalog.pg_index as ix
    join pg_catalog.pg_class as idx
      on idx.oid = ix.indexrelid
    join pg_catalog.pg_class as tbl
      on tbl.oid = ix.indrelid
    join pg_catalog.pg_namespace as n
      on n.oid = tbl.relnamespace
    join pg_catalog.pg_am as am
      on am.oid = idx.relam
    join pg_catalog.pg_attribute as a
      on a.attrelid = tbl.oid
     and a.attnum = ix.indkey[0]
    where n.nspname = 'machimoa_feedback'
      and tbl.relname = 'contacts'
      and idx.relname = 'contacts_expires_at_idx'
      and am.amname = 'btree'
      and ix.indnkeyatts = 1
      and ix.indnatts = 1
      and not ix.indisunique
      and a.attname = 'expires_at'
  )
    into v_index_ok;

  if v_index_ok is distinct from true then
    raise exception
      'index contacts_expires_at_idx must be a non-unique btree on expires_at';
  end if;

  select pg_catalog.string_agg(
           x.privilege_type
             || ':grantee='
             || x.grantee::pg_catalog.text,
           ', '
           order by x.privilege_type, x.grantee
         )
    into v_schema_acl_bad
  from pg_catalog.pg_namespace as n
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      n.nspacl,
      pg_catalog.acldefault('n'::pg_catalog."char", n.nspowner)
    )
  ) as x
  where n.nspname = 'machimoa_feedback'
    and x.privilege_type in ('USAGE', 'CREATE')
    and x.grantee is distinct from n.nspowner;

  if v_schema_acl_bad is not null then
    raise exception
      'machimoa_feedback has unexpected direct schema ACL (%)',
      v_schema_acl_bad;
  end if;

  select pg_catalog.string_agg(c.relname, ', ' order by c.relname)
    into v_missing_owner
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and c.relname in (
      'submissions',
      'contacts',
      'rate_limit_events',
      'purge_runs'
    )
    and pg_catalog.pg_get_userbyid(c.relowner) is distinct from 'postgres';

  if v_missing_owner is not null then
    raise exception
      'feedback tables must be owned by postgres (%)',
      v_missing_owner;
  end if;

  select pg_catalog.string_agg(
           c.relname
             || ':'
             || x.privilege_type
             || ':grantee='
             || x.grantee::pg_catalog.text,
           ', '
           order by c.relname, x.privilege_type, x.grantee
         )
    into v_table_acl_bad
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      c.relacl,
      pg_catalog.acldefault('r'::pg_catalog."char", c.relowner)
    )
  ) as x
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and c.relname in (
      'submissions',
      'contacts',
      'rate_limit_events',
      'purge_runs'
    )
    and x.grantee is distinct from c.relowner;

  if v_table_acl_bad is not null then
    raise exception
      'feedback tables have unexpected direct ACL (%)',
      v_table_acl_bad;
  end if;

  v_submit := pg_catalog.to_regprocedure(
    'public.submit_feedback(text,text,text,text,boolean,boolean,boolean,text,text,bytea,bytea)'
  );
  v_purge := pg_catalog.to_regprocedure(
    'public.purge_feedback()'
  );

  if v_submit is null or v_purge is null then
    raise exception
      'required submit_feedback or purge_feedback signature is missing';
  end if;

  select pg_catalog.pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
    into v_owner, v_secdef, v_config
  from pg_catalog.pg_proc as p
  where p.oid = v_submit;

  if v_owner is distinct from 'postgres'
     or v_secdef is distinct from true
     or v_config is distinct from array['search_path=""'::pg_catalog.text]
  then
    raise exception
      'submit_feedback must be postgres SECURITY DEFINER search_path=""';
  end if;

  select pg_catalog.pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
    into v_owner, v_secdef, v_config
  from pg_catalog.pg_proc as p
  where p.oid = v_purge;

  if v_owner is distinct from 'postgres'
     or v_secdef is distinct from true
     or v_config is distinct from array['search_path=""'::pg_catalog.text]
  then
    raise exception
      'purge_feedback must be postgres SECURITY DEFINER search_path=""';
  end if;

  select r.oid
    into v_service_role
  from pg_catalog.pg_roles as r
  where r.rolname = 'service_role';

  if v_service_role is null then
    raise exception 'role service_role is required';
  end if;

  select pg_catalog.string_agg(
           p.oid::pg_catalog.regprocedure::pg_catalog.text
             || ':EXECUTE:grantee='
             || x.grantee::pg_catalog.text
             || case
               when x.is_grantable then ':grant_option'
               else ''
             end,
           ', '
           order by 1
         )
    into v_fn_acl_bad
  from pg_catalog.pg_proc as p
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      p.proacl,
      pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
    )
  ) as x
  where p.oid = v_submit
    and x.privilege_type = 'EXECUTE'
    and x.grantee is distinct from p.proowner
    and x.grantee is distinct from v_service_role;

  if v_fn_acl_bad is not null then
    raise exception
      'submit_feedback has unexpected direct EXECUTE ACL (%)',
      v_fn_acl_bad;
  end if;

  if exists (
    select 1
    from pg_catalog.pg_proc as p
    cross join lateral pg_catalog.aclexplode(
      coalesce(
        p.proacl,
        pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
      )
    ) as x
    where p.oid = v_submit
      and x.privilege_type = 'EXECUTE'
      and x.grantee = v_service_role
      and x.is_grantable
  ) then
    raise exception
      'service_role must not have GRANT OPTION on submit_feedback';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_proc as p
    cross join lateral pg_catalog.aclexplode(
      coalesce(
        p.proacl,
        pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
      )
    ) as x
    where p.oid = v_submit
      and x.privilege_type = 'EXECUTE'
      and x.grantee = v_service_role
  ) then
    raise exception
      'service_role must have a direct EXECUTE grant on submit_feedback';
  end if;

  select pg_catalog.string_agg(
           p.oid::pg_catalog.regprocedure::pg_catalog.text
             || ':EXECUTE:grantee='
             || x.grantee::pg_catalog.text
             || case
               when x.is_grantable then ':grant_option'
               else ''
             end,
           ', '
           order by 1
         )
    into v_fn_acl_bad
  from pg_catalog.pg_proc as p
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      p.proacl,
      pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
    )
  ) as x
  where p.oid = v_purge
    and x.privilege_type = 'EXECUTE'
    and x.grantee is distinct from p.proowner;

  if v_fn_acl_bad is not null then
    raise exception
      'purge_feedback has unexpected direct EXECUTE ACL (%)',
      v_fn_acl_bad;
  end if;
end
$post$;

commit;
