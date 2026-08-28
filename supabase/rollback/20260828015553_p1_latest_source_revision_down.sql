-- NON-DESTRUCTIVE ROLLBACK.
-- Removes only public.is_latest_source_revision(text, text, text).
-- Candidate rows, public curations, indexes, columns, enqueue, publish,
-- and reject are left unchanged.
--
-- OPERATIONAL WARNING:
-- Run this file only after the pipeline code that calls
-- public.is_latest_source_revision has been reverted. Keep collection
-- workflows paused. Dropping the function while the pipeline still
-- calls it makes that run fail closed (no Gemini, no enqueue) and is
-- the wrong rollback order.
--
-- Do not apply without explicit approval. Do not create or run a
-- destructive cleanup file; there is nothing to delete beyond this
-- function.
--
-- Recovery after this script:
-- Do not re-run 20260828015553_p1_latest_source_revision.sql until the
-- failure cause is understood. Restore the function with a later
-- timestamped forward migration if needed. Keep collection paused
-- until that recovery is verified.
--
-- Signature guards: overload count by proname, then to_regprocedure of
-- the expected (type,...) lookup. Do not compare
-- pg_get_function_identity_arguments to a type-only string; Postgres 17
-- includes parameter names. Identity text is for exception messages only.
--
-- Pre-apply audit (read-only; do not record title, summary, content,
-- raw_payload, source_revision_hash, or secrets). Run as postgres
-- before applying:
--
--   select current_user, session_user;
--
--   select n.nspname || '.' || p.proname || '('
--            || pg_catalog.pg_get_function_identity_arguments(p.oid) || ')'
--            as identity,
--          pg_catalog.pg_get_userbyid(p.proowner) as owner,
--          p.prosecdef,
--          p.proconfig,
--          p.proacl
--   from pg_catalog.pg_proc as p
--   join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
--   where (n.nspname, p.proname) in (
--     ('public', 'is_latest_source_revision'),
--     ('public', 'enqueue_curation_candidate'),
--     ('machimoa_review', 'publish_curation_candidate'),
--     ('machimoa_review', 'reject_curation_candidate')
--   )
--   order by 1;
--
--   select pg_catalog.has_function_privilege(
--            'anon',
--            'public.is_latest_source_revision(text,text,text)',
--            'EXECUTE'
--          ) as anon_execute,
--          pg_catalog.has_function_privilege(
--            'authenticated',
--            'public.is_latest_source_revision(text,text,text)',
--            'EXECUTE'
--          ) as authenticated_execute,
--          pg_catalog.has_function_privilege(
--            'public',
--            'public.is_latest_source_revision(text,text,text)',
--            'EXECUTE'
--          ) as public_execute,
--          pg_catalog.has_function_privilege(
--            'service_role',
--            'public.is_latest_source_revision(text,text,text)',
--            'EXECUTE'
--          ) as service_role_execute;
--
--   select pg_catalog.count(*) as curations_count from public.curations;
--
--   select pg_catalog.count(*) as candidates_count
--   from machimoa_review.curation_candidates;
--
-- Post-apply audit: confirm zero is_latest_source_revision overloads,
-- unchanged enqueue/publish/reject ACL, unchanged candidate
-- schema/table/sequence privileges, and unchanged id/slug/status
-- fingerprints.

begin;

create temporary table p1_latest_source_revision_down_acl_snapshot (
  k pg_catalog.text primary key,
  v pg_catalog.text
) on commit drop;

do $guard$
declare
  v_precheck_count pg_catalog.int4;
  v_precheck_identity pg_catalog.text;
  v_precheck_oid pg_catalog.oid;
  v_precheck_reg pg_catalog.regprocedure;
  v_precheck_owner pg_catalog.name;
  v_precheck_secdef pg_catalog.bool;
  v_precheck_config pg_catalog.text[];
  v_enqueue_16 pg_catalog.regprocedure;
  v_enqueue_lookup pg_catalog.text :=
    'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)';
  v_publish_lookup pg_catalog.text :=
    'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)';
  v_reject_lookup pg_catalog.text :=
    'machimoa_review.reject_curation_candidate(uuid,text,text)';
  v_precheck_lookup pg_catalog.text :=
    'public.is_latest_source_revision(text,text,text)';
begin
  -- Supabase CLI 2.116.0 linked db push: session_user=cli_login_postgres,
  -- current_user=postgres. DDL authorization still requires current_user=postgres.
  -- session_user is an exact allowlist: postgres or cli_login_postgres.
  if current_user <> 'postgres'
     or session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'P1 latest source revision rollback must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  select
    pg_catalog.count(*)::pg_catalog.int4,
    pg_catalog.string_agg(
      pg_catalog.pg_get_function_identity_arguments(p.oid),
      ' | '
      order by pg_catalog.pg_get_function_identity_arguments(p.oid)
    ),
    pg_catalog.min(p.oid)
    into v_precheck_count, v_precheck_identity, v_precheck_oid
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'is_latest_source_revision';

  if v_precheck_count is distinct from 1 then
    raise exception
      'expected exactly one public.is_latest_source_revision overload before down, found % (%); refusing to drop',
      coalesce(v_precheck_count, 0),
      coalesce(v_precheck_identity, 'none');
  end if;

  v_precheck_reg := pg_catalog.to_regprocedure(v_precheck_lookup);
  if v_precheck_reg is null then
    raise exception
      'expected 3-argument is_latest_source_revision(text,text,text) before down, found (%); refusing to drop',
      coalesce(v_precheck_identity, 'none');
  end if;

  if v_precheck_reg::pg_catalog.oid is distinct from v_precheck_oid then
    raise exception
      'is_latest_source_revision overload does not match the 3-argument lookup (%); refusing to drop',
      coalesce(v_precheck_identity, 'none');
  end if;

  select
    pg_catalog.pg_get_userbyid(p.proowner),
    p.prosecdef,
    p.proconfig
    into v_precheck_owner, v_precheck_secdef, v_precheck_config
  from pg_catalog.pg_proc as p
  where p.oid = v_precheck_reg;

  if v_precheck_owner <> 'postgres'
     or v_precheck_secdef is distinct from true
     or v_precheck_config is distinct from array['search_path=""'::pg_catalog.text]
     or pg_catalog.has_function_privilege('anon', v_precheck_reg, 'EXECUTE')
     or pg_catalog.has_function_privilege('authenticated', v_precheck_reg, 'EXECUTE')
     or pg_catalog.has_function_privilege('public', v_precheck_reg, 'EXECUTE')
     or not pg_catalog.has_function_privilege(
          'service_role', v_precheck_reg, 'EXECUTE'
        )
  then
    raise exception
      'public.is_latest_source_revision owner, SECURITY DEFINER, search_path, or ACL is not the forward expected state; refusing to drop';
  end if;

  v_enqueue_16 := pg_catalog.to_regprocedure(v_enqueue_lookup);
  if v_enqueue_16 is null
     or pg_catalog.to_regprocedure(v_publish_lookup) is null
     or pg_catalog.to_regprocedure(v_reject_lookup) is null
  then
    raise exception
      'enqueue, publish, or reject is missing; refusing to drop is_latest_source_revision';
  end if;

  insert into p1_latest_source_revision_down_acl_snapshot (k, v)
  values
    (
      'schema_nspacl',
      (
        select n.nspacl::pg_catalog.text
        from pg_catalog.pg_namespace as n
        where n.nspname = 'machimoa_review'
      )
    ),
    (
      'candidates_relacl',
      (
        select c.relacl::pg_catalog.text
        from pg_catalog.pg_class as c
        join pg_catalog.pg_namespace as n
          on n.oid = c.relnamespace
        where n.nspname = 'machimoa_review'
          and c.relname = 'curation_candidates'
          and c.relkind in ('r', 'p')
      )
    ),
    (
      'seq_relacl',
      (
        select c.relacl::pg_catalog.text
        from pg_catalog.pg_class as c
        join pg_catalog.pg_namespace as n
          on n.oid = c.relnamespace
        where n.nspname = 'machimoa_review'
          and c.relname = 'curation_candidates_revision_seq_seq'
          and c.relkind = 'S'
      )
    ),
    (
      'curations_relacl',
      (
        select c.relacl::pg_catalog.text
        from pg_catalog.pg_class as c
        join pg_catalog.pg_namespace as n
          on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relname = 'curations'
          and c.relkind in ('r', 'p')
      )
    ),
    (
      'enqueue_proacl',
      (
        select p.proacl::pg_catalog.text
        from pg_catalog.pg_proc as p
        where p.oid = v_enqueue_16
      )
    ),
    (
      'publish_proacl',
      (
        select p.proacl::pg_catalog.text
        from pg_catalog.pg_proc as p
        where p.oid = pg_catalog.to_regprocedure(v_publish_lookup)
      )
    ),
    (
      'reject_proacl',
      (
        select p.proacl::pg_catalog.text
        from pg_catalog.pg_proc as p
        where p.oid = pg_catalog.to_regprocedure(v_reject_lookup)
      )
    ),
    (
      'privilege_fingerprint',
      pg_catalog.concat_ws(
        ',',
        pg_catalog.has_schema_privilege('anon', 'machimoa_review', 'USAGE')::pg_catalog.text,
        pg_catalog.has_schema_privilege('authenticated', 'machimoa_review', 'USAGE')::pg_catalog.text,
        pg_catalog.has_schema_privilege('service_role', 'machimoa_review', 'USAGE')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'machimoa_review.curation_candidates', 'SELECT')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'machimoa_review.curation_candidates', 'SELECT')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'machimoa_review.curation_candidates', 'SELECT')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'machimoa_review.curation_candidates', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'machimoa_review.curation_candidates', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'machimoa_review.curation_candidates', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'machimoa_review.curation_candidates', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'machimoa_review.curation_candidates', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'machimoa_review.curation_candidates', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'machimoa_review.curation_candidates', 'DELETE')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'machimoa_review.curation_candidates', 'DELETE')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'machimoa_review.curation_candidates', 'DELETE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('anon', 'machimoa_review.curation_candidates_revision_seq_seq', 'USAGE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('authenticated', 'machimoa_review.curation_candidates_revision_seq_seq', 'USAGE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('service_role', 'machimoa_review.curation_candidates_revision_seq_seq', 'USAGE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('anon', 'machimoa_review.curation_candidates_revision_seq_seq', 'SELECT')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('authenticated', 'machimoa_review.curation_candidates_revision_seq_seq', 'SELECT')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('service_role', 'machimoa_review.curation_candidates_revision_seq_seq', 'SELECT')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('anon', 'machimoa_review.curation_candidates_revision_seq_seq', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('authenticated', 'machimoa_review.curation_candidates_revision_seq_seq', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('service_role', 'machimoa_review.curation_candidates_revision_seq_seq', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'public.curations', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'public.curations', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'public.curations', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'public.curations', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'public.curations', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'public.curations', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'public.curations', 'DELETE')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'public.curations', 'DELETE')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'public.curations', 'DELETE')::pg_catalog.text,
        pg_catalog.has_function_privilege('anon', v_enqueue_16, 'EXECUTE')::pg_catalog.text,
        pg_catalog.has_function_privilege('authenticated', v_enqueue_16, 'EXECUTE')::pg_catalog.text,
        pg_catalog.has_function_privilege('public', v_enqueue_16, 'EXECUTE')::pg_catalog.text,
        pg_catalog.has_function_privilege('service_role', v_enqueue_16, 'EXECUTE')::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'anon',
          pg_catalog.to_regprocedure(v_publish_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'authenticated',
          pg_catalog.to_regprocedure(v_publish_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'public',
          pg_catalog.to_regprocedure(v_publish_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'service_role',
          pg_catalog.to_regprocedure(v_publish_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'anon',
          pg_catalog.to_regprocedure(v_reject_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'authenticated',
          pg_catalog.to_regprocedure(v_reject_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'public',
          pg_catalog.to_regprocedure(v_reject_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'service_role',
          pg_catalog.to_regprocedure(v_reject_lookup),
          'EXECUTE'
        )::pg_catalog.text
      )
    ),
    (
      'curations_count',
      (
        select pg_catalog.count(*)::pg_catalog.text
        from public.curations
      )
    ),
    (
      'candidates_count',
      (
        select pg_catalog.count(*)::pg_catalog.text
        from machimoa_review.curation_candidates
      )
    ),
    (
      'curations_fingerprint',
      (
        select pg_catalog.md5(
          coalesce(
            pg_catalog.string_agg(
              c.id::pg_catalog.text
                || '|'
                || c.slug
                || '|'
                || c.created_at::pg_catalog.text
                || '|'
                || c.updated_at::pg_catalog.text,
              ','
              order by c.created_at, c.id
            ),
            ''
          )
        )
        from public.curations as c
      )
    ),
    (
      'candidates_fingerprint',
      (
        select pg_catalog.md5(
          coalesce(
            pg_catalog.string_agg(
              c.id::pg_catalog.text
                || '|'
                || c.slug
                || '|'
                || c.review_status
                || '|'
                || c.revision_seq::pg_catalog.text
                || '|'
                || c.source
                || '|'
                || c.source_item_id
                || '|'
                || c.created_at::pg_catalog.text
                || '|'
                || c.updated_at::pg_catalog.text,
              ','
              order by c.revision_seq, c.id
            ),
            ''
          )
        )
        from machimoa_review.curation_candidates as c
      )
    );
end
$guard$;

drop function public.is_latest_source_revision(
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text
);

do $post$
declare
  v_remaining pg_catalog.text;
  v_enqueue_16 pg_catalog.regprocedure;
  v_changed pg_catalog.text;
  v_enqueue_lookup pg_catalog.text :=
    'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)';
  v_publish_lookup pg_catalog.text :=
    'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)';
  v_reject_lookup pg_catalog.text :=
    'machimoa_review.reject_curation_candidate(uuid,text,text)';
begin
  select pg_catalog.string_agg(
           'public.is_latest_source_revision('
             || pg_catalog.pg_get_function_identity_arguments(p.oid)
             || ')',
           ', '
           order by pg_catalog.pg_get_function_identity_arguments(p.oid)
         )
    into v_remaining
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'is_latest_source_revision';

  if v_remaining is not null then
    raise exception
      'public.is_latest_source_revision still exists after down (%)',
      v_remaining;
  end if;

  v_enqueue_16 := pg_catalog.to_regprocedure(v_enqueue_lookup);

  select pg_catalog.string_agg(s.k, ', ' order by s.k)
    into v_changed
  from p1_latest_source_revision_down_acl_snapshot as s
  where s.v is distinct from
    case s.k
      when 'schema_nspacl' then (
        select n.nspacl::pg_catalog.text
        from pg_catalog.pg_namespace as n
        where n.nspname = 'machimoa_review'
      )
      when 'candidates_relacl' then (
        select c.relacl::pg_catalog.text
        from pg_catalog.pg_class as c
        join pg_catalog.pg_namespace as n
          on n.oid = c.relnamespace
        where n.nspname = 'machimoa_review'
          and c.relname = 'curation_candidates'
          and c.relkind in ('r', 'p')
      )
      when 'seq_relacl' then (
        select c.relacl::pg_catalog.text
        from pg_catalog.pg_class as c
        join pg_catalog.pg_namespace as n
          on n.oid = c.relnamespace
        where n.nspname = 'machimoa_review'
          and c.relname = 'curation_candidates_revision_seq_seq'
          and c.relkind = 'S'
      )
      when 'curations_relacl' then (
        select c.relacl::pg_catalog.text
        from pg_catalog.pg_class as c
        join pg_catalog.pg_namespace as n
          on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relname = 'curations'
          and c.relkind in ('r', 'p')
      )
      when 'enqueue_proacl' then (
        select p.proacl::pg_catalog.text
        from pg_catalog.pg_proc as p
        where p.oid = v_enqueue_16
      )
      when 'publish_proacl' then (
        select p.proacl::pg_catalog.text
        from pg_catalog.pg_proc as p
        where p.oid = pg_catalog.to_regprocedure(v_publish_lookup)
      )
      when 'reject_proacl' then (
        select p.proacl::pg_catalog.text
        from pg_catalog.pg_proc as p
        where p.oid = pg_catalog.to_regprocedure(v_reject_lookup)
      )
      when 'privilege_fingerprint' then pg_catalog.concat_ws(
        ',',
        pg_catalog.has_schema_privilege('anon', 'machimoa_review', 'USAGE')::pg_catalog.text,
        pg_catalog.has_schema_privilege('authenticated', 'machimoa_review', 'USAGE')::pg_catalog.text,
        pg_catalog.has_schema_privilege('service_role', 'machimoa_review', 'USAGE')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'machimoa_review.curation_candidates', 'SELECT')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'machimoa_review.curation_candidates', 'SELECT')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'machimoa_review.curation_candidates', 'SELECT')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'machimoa_review.curation_candidates', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'machimoa_review.curation_candidates', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'machimoa_review.curation_candidates', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'machimoa_review.curation_candidates', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'machimoa_review.curation_candidates', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'machimoa_review.curation_candidates', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'machimoa_review.curation_candidates', 'DELETE')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'machimoa_review.curation_candidates', 'DELETE')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'machimoa_review.curation_candidates', 'DELETE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('anon', 'machimoa_review.curation_candidates_revision_seq_seq', 'USAGE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('authenticated', 'machimoa_review.curation_candidates_revision_seq_seq', 'USAGE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('service_role', 'machimoa_review.curation_candidates_revision_seq_seq', 'USAGE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('anon', 'machimoa_review.curation_candidates_revision_seq_seq', 'SELECT')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('authenticated', 'machimoa_review.curation_candidates_revision_seq_seq', 'SELECT')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('service_role', 'machimoa_review.curation_candidates_revision_seq_seq', 'SELECT')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('anon', 'machimoa_review.curation_candidates_revision_seq_seq', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('authenticated', 'machimoa_review.curation_candidates_revision_seq_seq', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_sequence_privilege('service_role', 'machimoa_review.curation_candidates_revision_seq_seq', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'public.curations', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'public.curations', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'public.curations', 'INSERT')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'public.curations', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'public.curations', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'public.curations', 'UPDATE')::pg_catalog.text,
        pg_catalog.has_table_privilege('anon', 'public.curations', 'DELETE')::pg_catalog.text,
        pg_catalog.has_table_privilege('authenticated', 'public.curations', 'DELETE')::pg_catalog.text,
        pg_catalog.has_table_privilege('service_role', 'public.curations', 'DELETE')::pg_catalog.text,
        pg_catalog.has_function_privilege('anon', v_enqueue_16, 'EXECUTE')::pg_catalog.text,
        pg_catalog.has_function_privilege('authenticated', v_enqueue_16, 'EXECUTE')::pg_catalog.text,
        pg_catalog.has_function_privilege('public', v_enqueue_16, 'EXECUTE')::pg_catalog.text,
        pg_catalog.has_function_privilege('service_role', v_enqueue_16, 'EXECUTE')::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'anon',
          pg_catalog.to_regprocedure(v_publish_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'authenticated',
          pg_catalog.to_regprocedure(v_publish_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'public',
          pg_catalog.to_regprocedure(v_publish_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'service_role',
          pg_catalog.to_regprocedure(v_publish_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'anon',
          pg_catalog.to_regprocedure(v_reject_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'authenticated',
          pg_catalog.to_regprocedure(v_reject_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'public',
          pg_catalog.to_regprocedure(v_reject_lookup),
          'EXECUTE'
        )::pg_catalog.text,
        pg_catalog.has_function_privilege(
          'service_role',
          pg_catalog.to_regprocedure(v_reject_lookup),
          'EXECUTE'
        )::pg_catalog.text
      )
      when 'curations_count' then (
        select pg_catalog.count(*)::pg_catalog.text
        from public.curations
      )
      when 'candidates_count' then (
        select pg_catalog.count(*)::pg_catalog.text
        from machimoa_review.curation_candidates
      )
      when 'curations_fingerprint' then (
        select pg_catalog.md5(
          coalesce(
            pg_catalog.string_agg(
              c.id::pg_catalog.text
                || '|'
                || c.slug
                || '|'
                || c.created_at::pg_catalog.text
                || '|'
                || c.updated_at::pg_catalog.text,
              ','
              order by c.created_at, c.id
            ),
            ''
          )
        )
        from public.curations as c
      )
      when 'candidates_fingerprint' then (
        select pg_catalog.md5(
          coalesce(
            pg_catalog.string_agg(
              c.id::pg_catalog.text
                || '|'
                || c.slug
                || '|'
                || c.review_status
                || '|'
                || c.revision_seq::pg_catalog.text
                || '|'
                || c.source
                || '|'
                || c.source_item_id
                || '|'
                || c.created_at::pg_catalog.text
                || '|'
                || c.updated_at::pg_catalog.text,
              ','
              order by c.revision_seq, c.id
            ),
            ''
          )
        )
        from machimoa_review.curation_candidates as c
      )
      else s.v
    end;

  if v_changed is not null then
    raise exception
      'candidate schema/table/sequence privileges, enqueue/publish/reject ACL, or data fingerprints changed during down (%)',
      v_changed;
  end if;
end
$post$;

commit;
