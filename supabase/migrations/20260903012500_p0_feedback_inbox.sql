-- P0 private anonymous feedback inbox.
-- Schema machimoa_feedback is not Data API exposed. Tables have no grants
-- to public, anon, authenticated, or service_role. Browser clients must not
-- call these tables or RPCs with the anon key.
--
-- public.submit_feedback / public.delete_feedback: SECURITY DEFINER,
-- search_path="", EXECUTE for service_role only.
-- public.mark_feedback_spam / public.purge_feedback: postgres only.
-- machimoa_feedback.normalize_feedback_body: IMMUTABLE STRICT helper.
--
-- Do not apply this file without a separate approval. This migration must
-- not enable pg_cron, create a Cron job, write curations/qna/review rows,
-- or change enqueue/publish/reject.
--
-- Supabase CLI 2.116.0 linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.
-- session_user is an exact allowlist: postgres or cli_login_postgres.
--
-- Pre-apply (read-only; do not record body, email, hmac, or secrets):
--
--   select current_user, session_user;
--
--   select pg_catalog.to_regnamespace('machimoa_feedback') is null
--     as feedback_schema_absent;
--
--   select n.nspname,
--          p.proname,
--          pg_catalog.pg_get_function_identity_arguments(p.oid) as identity
--     from pg_catalog.pg_proc as p
--     join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
--    where p.proname in (
--      'submit_feedback',
--      'delete_feedback',
--      'mark_feedback_spam',
--      'purge_feedback',
--      'normalize_feedback_body',
--      'try_consume_rate_limit'
--    );
--
-- Post-apply catalog checks are in the $post$ block. Operator DML tests
-- are not in this file.

begin;

do $guard$
declare
  v_existing pg_catalog.text;
begin
  if current_user <> 'postgres'
     or session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'P0 feedback inbox migration must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  if pg_catalog.to_regnamespace('machimoa_feedback') is not null then
    raise exception
      'schema machimoa_feedback already exists; inspect and resolve it manually';
  end if;

  select pg_catalog.string_agg(n.nspname || '.' || p.proname, ', ' order by 1)
    into v_existing
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where (n.nspname, p.proname) in (
    ('public', 'submit_feedback'),
    ('public', 'delete_feedback'),
    ('public', 'mark_feedback_spam'),
    ('public', 'purge_feedback'),
    ('machimoa_feedback', 'normalize_feedback_body'),
    ('machimoa_feedback', 'try_consume_rate_limit')
  );

  if v_existing is not null then
    raise exception
      'feedback functions already exist (%); inspect and resolve them manually',
      v_existing;
  end if;

  if pg_catalog.to_regprocedure('pg_catalog.gen_random_uuid()') is null then
    raise exception 'required function pg_catalog.gen_random_uuid() is unavailable';
  end if;

  if pg_catalog.to_regprocedure(
       'pg_catalog.hashtextextended(text,bigint)'
     ) is null then
    raise exception
      'required function pg_catalog.hashtextextended(text,bigint) is unavailable';
  end if;

  if pg_catalog.to_regprocedure(
       'pg_catalog.pg_advisory_xact_lock(bigint)'
     ) is null then
    raise exception
      'required function pg_catalog.pg_advisory_xact_lock(bigint) is unavailable';
  end if;
end
$guard$;

create schema machimoa_feedback authorization postgres;

revoke all privileges on schema machimoa_feedback
  from public, anon, authenticated, service_role;

alter default privileges for role postgres in schema machimoa_feedback
  revoke all on tables from public, anon, authenticated, service_role;

alter default privileges for role postgres in schema machimoa_feedback
  revoke all on sequences from public, anon, authenticated, service_role;

alter default privileges for role postgres in schema machimoa_feedback
  revoke all on functions from public, anon, authenticated, service_role;

create function machimoa_feedback.normalize_feedback_body(
  p_body pg_catalog.text
)
returns pg_catalog.text
language sql
immutable
strict
set search_path = ''
as $function$
  select pg_catalog.btrim(
    p_body,
    pg_catalog.chr(32)
      || pg_catalog.chr(9)
      || pg_catalog.chr(10)
      || pg_catalog.chr(13)
      || pg_catalog.chr(12288)
  );
$function$;

alter function machimoa_feedback.normalize_feedback_body(pg_catalog.text)
  owner to postgres;

revoke all privileges
  on function machimoa_feedback.normalize_feedback_body(pg_catalog.text)
  from public, anon, authenticated, service_role;

create table machimoa_feedback.submissions (
  id pg_catalog.uuid
    primary key
    default pg_catalog.gen_random_uuid(),
  locale pg_catalog.text not null,
  feedback_type pg_catalog.text not null,
  topic pg_catalog.text,
  body pg_catalog.text not null,
  privacy_consent pg_catalog.bool not null,
  age_gate_accepted pg_catalog.bool not null,
  contact_consent pg_catalog.bool not null default false,
  privacy_notice_version pg_catalog.text not null,
  status pg_catalog.text not null default 'normal',
  receipt_hmac pg_catalog.bytea not null,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  expires_at pg_catalog.timestamptz not null,
  spam_marked_at pg_catalog.timestamptz,

  constraint submissions_locale_ck
    check (locale in ('ko', 'ja')),
  constraint submissions_feedback_type_ck
    check (
      feedback_type in (
        'hard_to_find_life_info',
        'product_opinion',
        'other_inquiry'
      )
    ),
  constraint submissions_topic_ck
    check (
      topic is null
      or topic in (
        'housing',
        'identity',
        'work',
        'education',
        'welfare',
        'participation',
        'other'
      )
    ),
  constraint submissions_body_ck
    check (
      body = machimoa_feedback.normalize_feedback_body(body)
      and pg_catalog.char_length(body) between 10 and 1000
    ),
  constraint submissions_privacy_consent_ck
    check (privacy_consent),
  constraint submissions_age_gate_ck
    check (age_gate_accepted),
  constraint submissions_privacy_notice_version_ck
    check (
      pg_catalog.char_length(privacy_notice_version) between 19 and 64
      and privacy_notice_version ~ '^feedback-privacy-v[0-9]+$'
    ),
  constraint submissions_status_ck
    check (status in ('normal', 'spam')),
  constraint submissions_receipt_hmac_len_ck
    check (pg_catalog.octet_length(receipt_hmac) = 32),
  constraint submissions_receipt_hmac_uk
    unique (receipt_hmac),
  constraint submissions_spam_marked_at_ck
    check ((status = 'spam') = (spam_marked_at is not null)),
  constraint submissions_expires_at_ck
    check (expires_at > created_at)
);

create table machimoa_feedback.contacts (
  submission_id pg_catalog.uuid
    primary key
    references machimoa_feedback.submissions (id)
    on delete cascade,
  email pg_catalog.text not null,

  constraint contacts_email_ck
    check (
      pg_catalog.char_length(email) between 3 and 254
      and email = pg_catalog.btrim(email)
      and email !~ '[[:space:]]'
      and email ~ '^[^@]+@[^@]+\.[^@]+$'
    )
);

create table machimoa_feedback.rate_limit_events (
  id pg_catalog.uuid
    primary key
    default pg_catalog.gen_random_uuid(),
  action pg_catalog.text not null,
  id_hmac pg_catalog.bytea not null,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),

  constraint rate_limit_events_action_ck
    check (action in ('submit', 'delete')),
  constraint rate_limit_events_id_hmac_len_ck
    check (pg_catalog.octet_length(id_hmac) = 32)
);

create table machimoa_feedback.purge_runs (
  id pg_catalog.uuid
    primary key
    default pg_catalog.gen_random_uuid(),
  started_at pg_catalog.timestamptz not null,
  finished_at pg_catalog.timestamptz not null,
  success pg_catalog.bool not null,
  deleted_submissions pg_catalog.int4 not null default 0,
  deleted_rate_limit_events pg_catalog.int4 not null default 0,
  error_code pg_catalog.text,

  constraint purge_runs_deleted_counts_ck
    check (
      deleted_submissions >= 0
      and deleted_rate_limit_events >= 0
    ),
  constraint purge_runs_finished_at_ck
    check (finished_at >= started_at),
  constraint purge_runs_error_code_ck
    check (
      error_code is null
      or error_code in ('internal_error', 'query_canceled', 'lock_timeout')
    ),
  constraint purge_runs_success_state_ck
    check (
      (
        success
        and error_code is null
      )
      or (
        not success
        and error_code is not null
        and deleted_submissions = 0
        and deleted_rate_limit_events = 0
      )
    )
);

alter table machimoa_feedback.submissions owner to postgres;
alter table machimoa_feedback.contacts owner to postgres;
alter table machimoa_feedback.rate_limit_events owner to postgres;
alter table machimoa_feedback.purge_runs owner to postgres;

alter table machimoa_feedback.submissions enable row level security;
alter table machimoa_feedback.contacts enable row level security;
alter table machimoa_feedback.rate_limit_events enable row level security;
alter table machimoa_feedback.purge_runs enable row level security;

revoke all privileges on table machimoa_feedback.submissions
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_feedback.contacts
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_feedback.rate_limit_events
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_feedback.purge_runs
  from public, anon, authenticated, service_role;

create index submissions_expires_at_idx
  on machimoa_feedback.submissions (expires_at);

create index submissions_status_expires_at_idx
  on machimoa_feedback.submissions (status, expires_at);

create index rate_limit_events_action_hmac_created_idx
  on machimoa_feedback.rate_limit_events (action, id_hmac, created_at);

create index purge_runs_started_at_idx
  on machimoa_feedback.purge_runs (started_at);

create function machimoa_feedback.try_consume_rate_limit(
  p_action pg_catalog.text,
  p_id_hmac pg_catalog.bytea
)
returns pg_catalog.bool
language plpgsql
security invoker
set search_path = ''
as $function$
declare
  v_window_10 pg_catalog.int4;
  v_window_24 pg_catalog.int4;
  v_limit_10 pg_catalog.int4;
  v_limit_24 pg_catalog.int4;
begin
  if p_action = 'submit' then
    v_limit_10 := 3;
    v_limit_24 := 10;
  elsif p_action = 'delete' then
    v_limit_10 := 5;
    v_limit_24 := 20;
  else
    return false;
  end if;

  if pg_catalog.octet_length(p_id_hmac) is distinct from 32 then
    return false;
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      p_action
        || pg_catalog.chr(30)
        || pg_catalog.encode(p_id_hmac, 'hex'),
      0
    )
  );

  select pg_catalog.count(*)::pg_catalog.int4
    into v_window_10
  from machimoa_feedback.rate_limit_events as e
  where e.action = p_action
    and e.id_hmac = p_id_hmac
    and e.created_at > pg_catalog.now() - '10 minutes'::pg_catalog.interval;

  select pg_catalog.count(*)::pg_catalog.int4
    into v_window_24
  from machimoa_feedback.rate_limit_events as e
  where e.action = p_action
    and e.id_hmac = p_id_hmac
    and e.created_at > pg_catalog.now() - '24 hours'::pg_catalog.interval;

  if v_window_10 >= v_limit_10 or v_window_24 >= v_limit_24 then
    return false;
  end if;

  insert into machimoa_feedback.rate_limit_events (
    id,
    action,
    id_hmac
  )
  values (
    pg_catalog.gen_random_uuid(),
    p_action,
    p_id_hmac
  );

  return true;
end
$function$;

alter function machimoa_feedback.try_consume_rate_limit(
  pg_catalog.text,
  pg_catalog.bytea
)
owner to postgres;

revoke all privileges
  on function machimoa_feedback.try_consume_rate_limit(
    pg_catalog.text,
    pg_catalog.bytea
  )
  from public, anon, authenticated, service_role;

create function public.submit_feedback(
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
      pg_catalog.now(),
      pg_catalog.now() + '178 days'::pg_catalog.interval
    )
    returning machimoa_feedback.submissions.id
      into v_id;

    if v_email is not null then
      insert into machimoa_feedback.contacts (submission_id, email)
      values (v_id, v_email);
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

create function public.delete_feedback(
  p_receipt_hmac pg_catalog.bytea,
  p_rate_hmac pg_catalog.bytea
)
returns table (
  outcome pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if pg_catalog.octet_length(p_rate_hmac) is distinct from 32 then
    outcome := 'processed';
    return next;
    return;
  end if;

  if not machimoa_feedback.try_consume_rate_limit('delete', p_rate_hmac) then
    outcome := 'rate_limited';
    return next;
    return;
  end if;

  if pg_catalog.octet_length(p_receipt_hmac) is not distinct from 32 then
    delete from machimoa_feedback.submissions as s
    where s.receipt_hmac = p_receipt_hmac;
  end if;

  outcome := 'processed';
  return next;
  return;
end
$function$;

alter function public.delete_feedback(
  pg_catalog.bytea,
  pg_catalog.bytea
)
owner to postgres;

revoke all privileges
  on function public.delete_feedback(
    pg_catalog.bytea,
    pg_catalog.bytea
  )
  from public, anon, authenticated, service_role;

grant execute
  on function public.delete_feedback(
    pg_catalog.bytea,
    pg_catalog.bytea
  )
  to service_role;

create function public.mark_feedback_spam(
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

  delete from machimoa_feedback.contacts as c
  where c.submission_id = v_id;

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

create function public.purge_feedback()
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
  v_schema_owner pg_catalog.name;
  v_table_count pg_catalog.int4;
  v_missing_owner pg_catalog.text;
  v_rls_off pg_catalog.text;
  v_force_on pg_catalog.text;
  v_policy_count pg_catalog.int4;
  v_index_missing pg_catalog.text;
  v_table_acl_bad pg_catalog.text;
  v_schema_acl_bad pg_catalog.text;
  v_fn_acl_bad pg_catalog.text;
  v_service_role pg_catalog.oid;
  v_submit pg_catalog.regprocedure;
  v_delete pg_catalog.regprocedure;
  v_spam pg_catalog.regprocedure;
  v_purge pg_catalog.regprocedure;
  v_normalize pg_catalog.regprocedure;
  v_rate pg_catalog.regprocedure;
  v_owner pg_catalog.name;
  v_secdef pg_catalog.bool;
  v_config pg_catalog.text[];
  v_volatile pg_catalog.char;
  v_strict pg_catalog.bool;
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

  select pg_catalog.count(*)::pg_catalog.int4
    into v_table_count
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r';

  if v_table_count is distinct from 4 then
    raise exception
      'machimoa_feedback must have exactly 4 tables, found %',
      v_table_count;
  end if;

  select pg_catalog.string_agg(c.relname, ', ' order by c.relname)
    into v_missing_owner
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and pg_catalog.pg_get_userbyid(c.relowner) is distinct from 'postgres';

  if v_missing_owner is not null then
    raise exception
      'feedback tables must be owned by postgres (%)',
      v_missing_owner;
  end if;

  select pg_catalog.string_agg(c.relname, ', ' order by c.relname)
    into v_rls_off
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and c.relrowsecurity is distinct from true;

  if v_rls_off is not null then
    raise exception 'RLS must be enabled on (%)', v_rls_off;
  end if;

  select pg_catalog.string_agg(c.relname, ', ' order by c.relname)
    into v_force_on
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback'
    and c.relkind = 'r'
    and c.relforcerowsecurity is distinct from false;

  if v_force_on is not null then
    raise exception 'FORCE RLS must remain off on (%)', v_force_on;
  end if;

  select pg_catalog.string_agg(t.relname, ', ' order by t.relname)
    into v_table_acl_bad
  from (
    values
      ('submissions'::pg_catalog.name),
      ('contacts'),
      ('rate_limit_events'),
      ('purge_runs')
  ) as t(relname)
  where pg_catalog.to_regclass('machimoa_feedback.' || t.relname) is null;

  if v_table_acl_bad is not null then
    raise exception 'expected feedback tables are missing (%)', v_table_acl_bad;
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
    into v_policy_count
  from pg_catalog.pg_policy as p
  join pg_catalog.pg_class as c
    on c.oid = p.polrelid
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_feedback';

  if v_policy_count is distinct from 0 then
    raise exception
      'machimoa_feedback must have zero RLS policies, found %',
      v_policy_count;
  end if;

  select pg_catalog.string_agg(idx, ', ' order by idx)
    into v_index_missing
  from (
    values
      ('machimoa_feedback.submissions_receipt_hmac_uk'),
      ('machimoa_feedback.submissions_expires_at_idx'),
      ('machimoa_feedback.submissions_status_expires_at_idx'),
      ('machimoa_feedback.rate_limit_events_action_hmac_created_idx'),
      ('machimoa_feedback.purge_runs_started_at_idx')
  ) as expected(idx)
  where pg_catalog.to_regclass(expected.idx) is null;

  if v_index_missing is not null then
    raise exception 'missing feedback indexes (%)', v_index_missing;
  end if;

  v_submit := pg_catalog.to_regprocedure(
    'public.submit_feedback(text,text,text,text,boolean,boolean,boolean,text,text,bytea,bytea)'
  );
  v_delete := pg_catalog.to_regprocedure(
    'public.delete_feedback(bytea,bytea)'
  );
  v_spam := pg_catalog.to_regprocedure(
    'public.mark_feedback_spam(uuid)'
  );
  v_purge := pg_catalog.to_regprocedure(
    'public.purge_feedback()'
  );
  v_normalize := pg_catalog.to_regprocedure(
    'machimoa_feedback.normalize_feedback_body(text)'
  );
  v_rate := pg_catalog.to_regprocedure(
    'machimoa_feedback.try_consume_rate_limit(text,bytea)'
  );

  if v_submit is null
     or v_delete is null
     or v_spam is null
     or v_purge is null
     or v_normalize is null
     or v_rate is null then
    raise exception 'one or more feedback functions failed to register';
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
  where p.oid = v_delete;

  if v_owner is distinct from 'postgres'
     or v_secdef is distinct from true
     or v_config is distinct from array['search_path=""'::pg_catalog.text]
  then
    raise exception
      'delete_feedback must be postgres SECURITY DEFINER search_path=""';
  end if;

  select pg_catalog.pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
    into v_owner, v_secdef, v_config
  from pg_catalog.pg_proc as p
  where p.oid = v_spam;

  if v_owner is distinct from 'postgres'
     or v_secdef is distinct from true
     or v_config is distinct from array['search_path=""'::pg_catalog.text]
  then
    raise exception
      'mark_feedback_spam must be postgres SECURITY DEFINER search_path=""';
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

  select pg_catalog.pg_get_userbyid(p.proowner),
         p.prosecdef,
         p.proconfig,
         p.provolatile,
         p.proisstrict
    into v_owner, v_secdef, v_config, v_volatile, v_strict
  from pg_catalog.pg_proc as p
  where p.oid = v_normalize;

  if v_owner is distinct from 'postgres'
     or v_secdef is distinct from false
     or v_config is distinct from array['search_path=""'::pg_catalog.text]
     or v_volatile is distinct from 'i'
     or v_strict is distinct from true
  then
    raise exception
      'normalize_feedback_body must be postgres SECURITY INVOKER IMMUTABLE STRICT search_path=""';
  end if;

  select pg_catalog.pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
    into v_owner, v_secdef, v_config
  from pg_catalog.pg_proc as p
  where p.oid = v_rate;

  if v_owner is distinct from 'postgres'
     or v_secdef is distinct from false
     or v_config is distinct from array['search_path=""'::pg_catalog.text]
  then
    raise exception
      'try_consume_rate_limit must be postgres SECURITY INVOKER search_path=""';
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
  where p.oid in (v_submit, v_delete)
    and x.privilege_type = 'EXECUTE'
    and x.grantee is distinct from p.proowner
    and x.grantee is distinct from v_service_role;

  if v_fn_acl_bad is not null then
    raise exception
      'submit/delete have unexpected direct EXECUTE ACL (%)',
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
    where p.oid in (v_submit, v_delete)
      and x.privilege_type = 'EXECUTE'
      and x.grantee = v_service_role
      and x.is_grantable
  ) then
    raise exception
      'service_role must not have GRANT OPTION on submit or delete';
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
       where p.oid = v_delete
         and x.privilege_type = 'EXECUTE'
         and x.grantee = v_service_role
     )
  then
    raise exception
      'service_role must have a direct EXECUTE grant on submit and delete';
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
  where p.oid in (v_spam, v_purge, v_normalize, v_rate)
    and x.privilege_type = 'EXECUTE'
    and x.grantee is distinct from p.proowner;

  if v_fn_acl_bad is not null then
    raise exception
      'postgres-only feedback functions have unexpected direct EXECUTE ACL (%)',
      v_fn_acl_bad;
  end if;
end
$post$;

commit;
