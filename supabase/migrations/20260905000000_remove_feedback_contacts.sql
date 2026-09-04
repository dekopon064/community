-- Corrective: make private feedback a one-way flow without contact details.
-- The two earlier feedback migrations stay immutable. This migration removes
-- contacts, contact_consent, and the 11-argument submit RPC, then installs the
-- final 9-argument submit RPC.
--
-- Do not apply this file without separate approval. It must not enable pg_cron,
-- create jobs, alter secrets, or change the delete/rate-limit contract.

begin;

do $guard$
declare
  v_schema_owner pg_catalog.name;
  v_schema_acl_bad pg_catalog.text;
  v_table_names pg_catalog.text;
  v_table_owner_bad pg_catalog.text;
  v_table_acl_bad pg_catalog.text;
  v_policy_count pg_catalog.int4;
  v_column_ok pg_catalog.bool;
  v_index_ok pg_catalog.bool;
  v_submit_old pg_catalog.regprocedure;
  v_submit_new pg_catalog.regprocedure;
  v_delete pg_catalog.regprocedure;
  v_spam pg_catalog.regprocedure;
  v_purge pg_catalog.regprocedure;
  v_normalize pg_catalog.regprocedure;
  v_rate pg_catalog.regprocedure;
  v_service_role pg_catalog.oid;
  v_function_bad pg_catalog.text;
  v_function_acl_bad pg_catalog.text;
begin
  if current_user <> 'postgres'
     or session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'feedback contact removal must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  select pg_catalog.pg_get_userbyid(n.nspowner)
    into v_schema_owner
  from pg_catalog.pg_namespace as n
  where n.nspname = 'machimoa_feedback';

  if v_schema_owner is distinct from 'postgres' then
    raise exception
      'machimoa_feedback must exist and be owned by postgres';
  end if;

  select pg_catalog.string_agg(
           x.privilege_type || ':grantee=' || x.grantee::pg_catalog.text,
           ', ' order by x.privilege_type, x.grantee
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

  select pg_catalog.string_agg(c.relname, ',' order by c.relname)
    into v_table_names
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r';

  if v_table_names is distinct from
       'contacts,purge_runs,rate_limit_events,submissions' then
    raise exception
      'expected the four pre-B feedback tables, got %',
      coalesce(v_table_names, '<none>');
  end if;

  select pg_catalog.string_agg(c.relname, ', ' order by c.relname)
    into v_table_owner_bad
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and pg_catalog.pg_get_userbyid(c.relowner) is distinct from 'postgres';

  if v_table_owner_bad is not null then
    raise exception
      'feedback tables must be owned by postgres (%)',
      v_table_owner_bad;
  end if;

  select pg_catalog.string_agg(
           c.relname || ':' || x.privilege_type
             || ':grantee=' || x.grantee::pg_catalog.text,
           ', ' order by c.relname, x.privilege_type, x.grantee
         )
    into v_table_acl_bad
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      c.relacl,
      pg_catalog.acldefault('r'::pg_catalog."char", c.relowner)
    )
  ) as x
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and x.grantee is distinct from c.relowner;

  if v_table_acl_bad is not null then
    raise exception
      'feedback tables have unexpected direct ACL (%)',
      v_table_acl_bad;
  end if;

  if exists (
    select 1
    from pg_catalog.pg_class as c
    join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
    where n.nspname = 'machimoa_feedback'
      and c.relkind = 'r'
      and (not c.relrowsecurity or c.relforcerowsecurity)
  ) then
    raise exception 'feedback tables must have RLS enabled and FORCE RLS disabled';
  end if;

  select pg_catalog.count(*)::pg_catalog.int4
    into v_policy_count
  from pg_catalog.pg_policy as p
  join pg_catalog.pg_class as c on c.oid = p.polrelid
  join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback';

  if v_policy_count is distinct from 0 then
    raise exception 'feedback tables must not have RLS policies';
  end if;

  select exists (
    select 1
    from pg_catalog.pg_attribute as a
    where a.attrelid = 'machimoa_feedback.submissions'::pg_catalog.regclass
      and a.attname = 'contact_consent'
      and a.atttypid = 'pg_catalog.bool'::pg_catalog.regtype
      and a.attnotnull
      and a.attnum > 0
      and not a.attisdropped
  ) into v_column_ok;

  if v_column_ok is distinct from true then
    raise exception 'submissions.contact_consent boolean NOT NULL is missing';
  end if;

  select exists (
    select 1
    from pg_catalog.pg_attribute as a
    where a.attrelid = 'machimoa_feedback.contacts'::pg_catalog.regclass
      and a.attname = 'expires_at'
      and a.atttypid = 'pg_catalog.timestamptz'::pg_catalog.regtype
      and a.attnotnull
      and a.attnum > 0
      and not a.attisdropped
  ) into v_column_ok;

  if v_column_ok is distinct from true then
    raise exception 'contacts.expires_at timestamptz NOT NULL is missing';
  end if;

  select exists (
    select 1
    from pg_catalog.pg_index as ix
    join pg_catalog.pg_class as idx on idx.oid = ix.indexrelid
    join pg_catalog.pg_class as tbl on tbl.oid = ix.indrelid
    join pg_catalog.pg_namespace as n on n.oid = tbl.relnamespace
    join pg_catalog.pg_am as am on am.oid = idx.relam
    join pg_catalog.pg_attribute as a
      on a.attrelid = tbl.oid and a.attnum = ix.indkey[0]
    where n.nspname = 'machimoa_feedback'
      and tbl.relname = 'contacts'
      and idx.relname = 'contacts_expires_at_idx'
      and am.amname = 'btree'
      and ix.indnkeyatts = 1
      and ix.indnatts = 1
      and not ix.indisunique
      and a.attname = 'expires_at'
  ) into v_index_ok;

  if v_index_ok is distinct from true then
    raise exception 'contacts_expires_at_idx contract is missing';
  end if;

  if (
    select pg_catalog.count(*)
    from pg_catalog.pg_proc as p
    join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname = 'submit_feedback'
  ) is distinct from 1::pg_catalog.int8 then
    raise exception 'expected exactly one pre-B submit_feedback overload';
  end if;

  if (
    select pg_catalog.count(*)
    from pg_catalog.pg_proc as p
    join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
    where (n.nspname = 'public' and p.proname in (
      'submit_feedback',
      'delete_feedback',
      'mark_feedback_spam',
      'purge_feedback'
    ))
    or (n.nspname = 'machimoa_feedback' and p.proname in (
      'normalize_feedback_body',
      'try_consume_rate_limit'
    ))
  ) is distinct from 6::pg_catalog.int8 then
    raise exception 'expected exactly six pre-B feedback functions';
  end if;

  v_submit_old := pg_catalog.to_regprocedure(
    'public.submit_feedback(text,text,text,text,boolean,boolean,boolean,text,text,bytea,bytea)'
  );
  v_submit_new := pg_catalog.to_regprocedure(
    'public.submit_feedback(text,text,text,text,boolean,boolean,text,bytea,bytea)'
  );
  v_delete := pg_catalog.to_regprocedure('public.delete_feedback(bytea,bytea)');
  v_spam := pg_catalog.to_regprocedure('public.mark_feedback_spam(uuid)');
  v_purge := pg_catalog.to_regprocedure('public.purge_feedback()');
  v_normalize := pg_catalog.to_regprocedure(
    'machimoa_feedback.normalize_feedback_body(text)'
  );
  v_rate := pg_catalog.to_regprocedure(
    'machimoa_feedback.try_consume_rate_limit(text,bytea)'
  );

  if v_submit_old is null
     or v_submit_new is not null
     or v_delete is null
     or v_spam is null
     or v_purge is null
     or v_normalize is null
     or v_rate is null then
    raise exception 'pre-B feedback function signatures do not match';
  end if;

  select r.oid into v_service_role
  from pg_catalog.pg_roles as r
  where r.rolname = 'service_role';

  if v_service_role is null then
    raise exception 'role service_role is required';
  end if;

  select pg_catalog.string_agg(
           p.oid::pg_catalog.regprocedure::pg_catalog.text,
           ', ' order by p.oid::pg_catalog.regprocedure::pg_catalog.text
         )
    into v_function_bad
  from pg_catalog.pg_proc as p
  where p.oid in (
    v_submit_old::pg_catalog.oid,
    v_delete::pg_catalog.oid,
    v_spam::pg_catalog.oid,
    v_purge::pg_catalog.oid,
    v_normalize::pg_catalog.oid,
    v_rate::pg_catalog.oid
  )
    and (
      pg_catalog.pg_get_userbyid(p.proowner) is distinct from 'postgres'
      or p.prosecdef is distinct from (
        p.oid in (
          v_submit_old::pg_catalog.oid,
          v_delete::pg_catalog.oid,
          v_spam::pg_catalog.oid,
          v_purge::pg_catalog.oid
        )
      )
      or p.proconfig is distinct from array['search_path=""'::pg_catalog.text]
    );

  if v_function_bad is not null then
    raise exception 'feedback function security contract differs (%)', v_function_bad;
  end if;

  select pg_catalog.string_agg(
           p.oid::pg_catalog.regprocedure::pg_catalog.text
             || ':EXECUTE:grantee=' || x.grantee::pg_catalog.text
             || case when x.is_grantable then ':grant_option' else '' end,
           ', ' order by p.oid::pg_catalog.regprocedure::pg_catalog.text, x.grantee
         )
    into v_function_acl_bad
  from pg_catalog.pg_proc as p
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      p.proacl,
      pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
    )
  ) as x
  where p.oid in (
    v_submit_old::pg_catalog.oid,
    v_delete::pg_catalog.oid,
    v_spam::pg_catalog.oid,
    v_purge::pg_catalog.oid,
    v_normalize::pg_catalog.oid,
    v_rate::pg_catalog.oid
  )
    and x.privilege_type = 'EXECUTE'
    and x.grantee is distinct from p.proowner
    and not (
      p.oid in (v_submit_old::pg_catalog.oid, v_delete::pg_catalog.oid)
      and x.grantee = v_service_role
      and not x.is_grantable
    );

  if v_function_acl_bad is not null then
    raise exception
      'feedback functions have unexpected direct EXECUTE ACL (%)',
      v_function_acl_bad;
  end if;

  if not exists (
       select 1
       from pg_catalog.aclexplode(
         coalesce(
           (select p.proacl from pg_catalog.pg_proc as p
            where p.oid = v_submit_old::pg_catalog.oid),
           pg_catalog.acldefault(
             'f'::pg_catalog."char",
             (select p.proowner from pg_catalog.pg_proc as p
              where p.oid = v_submit_old::pg_catalog.oid)
           )
         )
       ) as x
       where x.privilege_type = 'EXECUTE'
         and x.grantee = v_service_role
         and not x.is_grantable
     )
     or not exists (
       select 1
       from pg_catalog.pg_proc as p
       cross join lateral pg_catalog.aclexplode(
         coalesce(
           p.proacl,
           pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
         )
       ) as x
       where p.oid = v_delete::pg_catalog.oid
         and x.privilege_type = 'EXECUTE'
         and x.grantee = v_service_role
         and not x.is_grantable
     ) then
    raise exception 'service_role direct submit/delete EXECUTE is missing';
  end if;
end
$guard$;

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

drop function public.submit_feedback(
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
);

alter table machimoa_feedback.submissions
  drop column contact_consent;

drop table machimoa_feedback.contacts;

create function public.submit_feedback(
  p_locale pg_catalog.text,
  p_feedback_type pg_catalog.text,
  p_topic pg_catalog.text,
  p_body pg_catalog.text,
  p_privacy_consent pg_catalog.bool,
  p_age_gate_accepted pg_catalog.bool,
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
  v_version pg_catalog.text;
  v_id pg_catalog.uuid;
  v_now pg_catalog.timestamptz;
begin
  v_locale := pg_catalog.btrim(coalesce(p_locale, ''));
  v_type := pg_catalog.btrim(coalesce(p_feedback_type, ''));
  v_topic := nullif(pg_catalog.btrim(coalesce(p_topic, '')), '');
  v_body := machimoa_feedback.normalize_feedback_body(p_body);
  v_version := pg_catalog.btrim(coalesce(p_privacy_notice_version, ''));

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
      v_version,
      'normal',
      p_receipt_hmac,
      v_now,
      v_now + '178 days'::pg_catalog.interval
    )
    returning machimoa_feedback.submissions.id into v_id;
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
    pg_catalog.text,
    pg_catalog.bytea,
    pg_catalog.bytea
  )
  to service_role;

create or replace function public.mark_feedback_spam(
  p_submission_id pg_catalog.uuid
)
returns pg_catalog.uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_id pg_catalog.uuid := p_submission_id;
  v_now pg_catalog.timestamptz := pg_catalog.now();
begin
  if v_id is null then
    raise exception 'submission_id is required';
  end if;

  perform 1
  from machimoa_feedback.submissions as s
  where s.id = v_id
  for update;

  if not found then
    raise exception 'submission does not exist';
  end if;

  update machimoa_feedback.submissions as s
  set
    status = 'spam',
    spam_marked_at = coalesce(s.spam_marked_at, v_now),
    expires_at = least(
      s.expires_at,
      v_now + '28 days'::pg_catalog.interval
    )
  where s.id = v_id;

  return v_id;
end
$function$;

alter function public.mark_feedback_spam(pg_catalog.uuid)
  owner to postgres;

revoke all privileges
  on function public.mark_feedback_spam(pg_catalog.uuid)
  from public, anon, authenticated, service_role;

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
  v_schema_acl_bad pg_catalog.text;
  v_table_names pg_catalog.text;
  v_table_bad pg_catalog.text;
  v_table_acl_bad pg_catalog.text;
  v_policy_count pg_catalog.int4;
  v_submit pg_catalog.regprocedure;
  v_submit_old pg_catalog.regprocedure;
  v_delete pg_catalog.regprocedure;
  v_spam pg_catalog.regprocedure;
  v_purge pg_catalog.regprocedure;
  v_normalize pg_catalog.regprocedure;
  v_rate pg_catalog.regprocedure;
  v_service_role pg_catalog.oid;
  v_function_bad pg_catalog.text;
  v_function_acl_bad pg_catalog.text;
begin
  if pg_catalog.pg_get_userbyid(
       (select n.nspowner from pg_catalog.pg_namespace as n
        where n.nspname = 'machimoa_feedback')
     ) is distinct from 'postgres' then
    raise exception 'machimoa_feedback owner changed';
  end if;

  select pg_catalog.string_agg(
           x.privilege_type || ':grantee=' || x.grantee::pg_catalog.text,
           ', ' order by x.privilege_type, x.grantee
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
    raise exception 'machimoa_feedback has unexpected ACL (%)', v_schema_acl_bad;
  end if;

  select pg_catalog.string_agg(c.relname, ',' order by c.relname)
    into v_table_names
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r';

  if v_table_names is distinct from
       'purge_runs,rate_limit_events,submissions' then
    raise exception
      'expected the three B feedback tables, got %',
      coalesce(v_table_names, '<none>');
  end if;

  if pg_catalog.to_regclass('machimoa_feedback.contacts') is not null
     or pg_catalog.to_regclass('machimoa_feedback.contacts_expires_at_idx')
       is not null
     or exists (
       select 1
       from pg_catalog.pg_attribute as a
       where a.attrelid = 'machimoa_feedback.submissions'::pg_catalog.regclass
         and a.attname = 'contact_consent'
         and a.attnum > 0
         and not a.attisdropped
     ) then
    raise exception 'contact storage artifacts remain after B migration';
  end if;

  select pg_catalog.string_agg(c.relname, ', ' order by c.relname)
    into v_table_bad
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and (
      pg_catalog.pg_get_userbyid(c.relowner) is distinct from 'postgres'
      or not c.relrowsecurity
      or c.relforcerowsecurity
    );

  if v_table_bad is not null then
    raise exception 'final feedback table security differs (%)', v_table_bad;
  end if;

  select pg_catalog.string_agg(
           c.relname || ':' || x.privilege_type
             || ':grantee=' || x.grantee::pg_catalog.text,
           ', ' order by c.relname, x.privilege_type, x.grantee
         )
    into v_table_acl_bad
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      c.relacl,
      pg_catalog.acldefault('r'::pg_catalog."char", c.relowner)
    )
  ) as x
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and x.grantee is distinct from c.relowner;

  if v_table_acl_bad is not null then
    raise exception 'final feedback tables have unexpected ACL (%)', v_table_acl_bad;
  end if;

  select pg_catalog.count(*)::pg_catalog.int4
    into v_policy_count
  from pg_catalog.pg_policy as p
  join pg_catalog.pg_class as c on c.oid = p.polrelid
  join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback';

  if v_policy_count is distinct from 0 then
    raise exception 'final feedback tables must not have RLS policies';
  end if;

  if (
    select pg_catalog.count(*)
    from pg_catalog.pg_proc as p
    join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.proname = 'submit_feedback'
  ) is distinct from 1::pg_catalog.int8 then
    raise exception 'expected exactly one final submit_feedback overload';
  end if;

  if (
    select pg_catalog.count(*)
    from pg_catalog.pg_proc as p
    join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
    where (n.nspname = 'public' and p.proname in (
      'submit_feedback',
      'delete_feedback',
      'mark_feedback_spam',
      'purge_feedback'
    ))
    or (n.nspname = 'machimoa_feedback' and p.proname in (
      'normalize_feedback_body',
      'try_consume_rate_limit'
    ))
  ) is distinct from 6::pg_catalog.int8 then
    raise exception 'expected exactly six final feedback functions';
  end if;

  v_submit := pg_catalog.to_regprocedure(
    'public.submit_feedback(text,text,text,text,boolean,boolean,text,bytea,bytea)'
  );
  v_submit_old := pg_catalog.to_regprocedure(
    'public.submit_feedback(text,text,text,text,boolean,boolean,boolean,text,text,bytea,bytea)'
  );
  v_delete := pg_catalog.to_regprocedure('public.delete_feedback(bytea,bytea)');
  v_spam := pg_catalog.to_regprocedure('public.mark_feedback_spam(uuid)');
  v_purge := pg_catalog.to_regprocedure('public.purge_feedback()');
  v_normalize := pg_catalog.to_regprocedure(
    'machimoa_feedback.normalize_feedback_body(text)'
  );
  v_rate := pg_catalog.to_regprocedure(
    'machimoa_feedback.try_consume_rate_limit(text,bytea)'
  );

  if v_submit is null
     or v_submit_old is not null
     or v_delete is null
     or v_spam is null
     or v_purge is null
     or v_normalize is null
     or v_rate is null then
    raise exception 'final feedback function signatures do not match B';
  end if;

  select r.oid into v_service_role
  from pg_catalog.pg_roles as r
  where r.rolname = 'service_role';

  if v_service_role is null then
    raise exception 'role service_role is required';
  end if;

  select pg_catalog.string_agg(
           p.oid::pg_catalog.regprocedure::pg_catalog.text,
           ', ' order by p.oid::pg_catalog.regprocedure::pg_catalog.text
         )
    into v_function_bad
  from pg_catalog.pg_proc as p
  where p.oid in (
    v_submit::pg_catalog.oid,
    v_delete::pg_catalog.oid,
    v_spam::pg_catalog.oid,
    v_purge::pg_catalog.oid,
    v_normalize::pg_catalog.oid,
    v_rate::pg_catalog.oid
  )
    and (
      pg_catalog.pg_get_userbyid(p.proowner) is distinct from 'postgres'
      or p.prosecdef is distinct from (
        p.oid in (
          v_submit::pg_catalog.oid,
          v_delete::pg_catalog.oid,
          v_spam::pg_catalog.oid,
          v_purge::pg_catalog.oid
        )
      )
      or p.proconfig is distinct from array['search_path=""'::pg_catalog.text]
    );

  if v_function_bad is not null then
    raise exception 'final function security differs (%)', v_function_bad;
  end if;

  if not exists (
    select 1 from pg_catalog.pg_proc as p
    where p.oid = v_normalize::pg_catalog.oid
      and p.provolatile = 'i'
      and p.proisstrict
  ) then
    raise exception 'normalize_feedback_body must remain IMMUTABLE STRICT';
  end if;

  select pg_catalog.string_agg(
           p.oid::pg_catalog.regprocedure::pg_catalog.text
             || ':EXECUTE:grantee=' || x.grantee::pg_catalog.text
             || case when x.is_grantable then ':grant_option' else '' end,
           ', ' order by p.oid::pg_catalog.regprocedure::pg_catalog.text, x.grantee
         )
    into v_function_acl_bad
  from pg_catalog.pg_proc as p
  cross join lateral pg_catalog.aclexplode(
    coalesce(
      p.proacl,
      pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
    )
  ) as x
  where p.oid in (
    v_submit::pg_catalog.oid,
    v_delete::pg_catalog.oid,
    v_spam::pg_catalog.oid,
    v_purge::pg_catalog.oid,
    v_normalize::pg_catalog.oid,
    v_rate::pg_catalog.oid
  )
    and x.privilege_type = 'EXECUTE'
    and x.grantee is distinct from p.proowner
    and not (
      p.oid in (v_submit::pg_catalog.oid, v_delete::pg_catalog.oid)
      and x.grantee = v_service_role
      and not x.is_grantable
    );

  if v_function_acl_bad is not null then
    raise exception 'final functions have unexpected ACL (%)', v_function_acl_bad;
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
       where p.oid = v_submit::pg_catalog.oid
         and x.privilege_type = 'EXECUTE'
         and x.grantee = v_service_role
         and not x.is_grantable
     )
     or not exists (
       select 1
       from pg_catalog.pg_proc as p
       cross join lateral pg_catalog.aclexplode(
         coalesce(
           p.proacl,
           pg_catalog.acldefault('f'::pg_catalog."char", p.proowner)
         )
       ) as x
       where p.oid = v_delete::pg_catalog.oid
         and x.privilege_type = 'EXECUTE'
         and x.grantee = v_service_role
         and not x.is_grantable
     ) then
    raise exception 'service_role submit/delete direct EXECUTE contract differs';
  end if;
end
$post$;

commit;
