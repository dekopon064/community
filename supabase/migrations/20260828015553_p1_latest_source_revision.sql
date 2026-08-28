-- P1 latest-source-revision precheck: add a read-only public boolean RPC
-- that reports whether (source, source_item_id, source_revision_hash)
-- matches the newest curation_candidates row for that source item.
--
-- Non-destructive rollback:
--   supabase/rollback/20260828015553_p1_latest_source_revision_down.sql
-- Do not create a destructive cleanup file. This migration adds no table,
-- column, index, or data, so DROP FUNCTION is a lossless rollback.
--
-- Do not apply this file to the operating database without an explicit
-- approval that is separate from committing the SQL. This transaction
-- must not write curation or candidate rows, must not lock candidate
-- rows, and must not change enqueue/publish/reject.
--
-- Meaning of the result:
--   true  = a candidate exists for the normalized (source, source_item_id)
--           and its newest source_revision_hash (revision_seq DESC, no
--           review_status filter) equals the normalized input hash
--   false = no such candidate, or the newest hash is different
--           (A -> B -> A returns false while B is newest)
-- The function returns boolean only. It does not return ids, hashes,
-- status, payload, or title/content.
--
-- Supabase CLI 2.116.0 linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.
-- session_user is an exact allowlist: postgres or cli_login_postgres.
--
-- Signature guards: overload count by proname, then to_regprocedure of the
-- expected (type,...) lookup. Do not compare
-- pg_get_function_identity_arguments to a type-only string; Postgres 17
-- includes parameter names. Identity text is for exception messages only.
--
-- Pre-apply audit (read-only; do not record title, summary, content,
-- raw_payload, source_revision_hash, or secrets). Run as postgres
-- before applying:
--
--   select current_user, session_user;
--
--   select n.nspname,
--          pg_catalog.pg_get_userbyid(n.nspowner) as owner,
--          n.nspacl
--   from pg_catalog.pg_namespace as n
--   where n.nspname = 'machimoa_review';
--
--   select n.nspname,
--          c.relname,
--          c.relkind,
--          pg_catalog.pg_get_userbyid(c.relowner) as owner,
--          c.relacl
--   from pg_catalog.pg_class as c
--   join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
--   where (n.nspname, c.relname) in (
--     ('machimoa_review', 'curation_candidates'),
--     ('machimoa_review', 'curation_candidates_revision_seq_seq'),
--     ('public', 'curations')
--   );
--
--   select a.attname,
--          pg_catalog.format_type(a.atttypid, a.atttypmod) as formatted_type,
--          a.attnotnull,
--          a.attidentity
--   from pg_catalog.pg_attribute as a
--   where a.attrelid =
--           'machimoa_review.curation_candidates'::pg_catalog.regclass
--     and a.attname in (
--       'source',
--       'source_item_id',
--       'source_revision_hash',
--       'revision_seq'
--     )
--     and not a.attisdropped
--   order by a.attname;
--
--   select pg_catalog.pg_get_indexdef(
--            'machimoa_review.curation_candidates_source_revision_idx'
--              ::pg_catalog.regclass
--          ) as indexdef;
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
--     ('public', 'enqueue_curation_candidate'),
--     ('public', 'is_latest_source_revision'),
--     ('machimoa_review', 'publish_curation_candidate'),
--     ('machimoa_review', 'reject_curation_candidate')
--   )
--   order by 1;
--
--   select pg_catalog.has_schema_privilege(
--            'anon', 'machimoa_review', 'USAGE'
--          ) as anon_schema_usage,
--          pg_catalog.has_schema_privilege(
--            'authenticated', 'machimoa_review', 'USAGE'
--          ) as authenticated_schema_usage,
--          pg_catalog.has_schema_privilege(
--            'service_role', 'machimoa_review', 'USAGE'
--          ) as service_role_schema_usage,
--          pg_catalog.has_table_privilege(
--            'anon', 'machimoa_review.curation_candidates', 'SELECT'
--          ) as anon_candidate_select,
--          pg_catalog.has_table_privilege(
--            'authenticated', 'machimoa_review.curation_candidates', 'SELECT'
--          ) as authenticated_candidate_select,
--          pg_catalog.has_table_privilege(
--            'service_role', 'machimoa_review.curation_candidates', 'SELECT'
--          ) as service_role_candidate_select,
--          pg_catalog.has_sequence_privilege(
--            'service_role',
--            'machimoa_review.curation_candidates_revision_seq_seq',
--            'USAGE'
--          ) as service_role_seq_usage,
--          pg_catalog.has_table_privilege(
--            'service_role', 'public.curations', 'INSERT'
--          ) as service_role_curations_insert,
--          pg_catalog.has_table_privilege(
--            'service_role', 'public.curations', 'UPDATE'
--          ) as service_role_curations_update,
--          pg_catalog.has_table_privilege(
--            'service_role', 'public.curations', 'DELETE'
--          ) as service_role_curations_delete;
--
--   select pg_catalog.count(*) as curations_count from public.curations;
--
--   select pg_catalog.count(*) as candidates_count
--   from machimoa_review.curation_candidates;
--
--   select id, slug, created_at, updated_at
--   from public.curations
--   order by created_at, id;
--
--   select id,
--          slug,
--          review_status,
--          revision_seq,
--          source,
--          source_item_id,
--          created_at,
--          updated_at,
--          reviewed_at,
--          published_at,
--          published_curation_id,
--          superseded_at,
--          superseded_by_candidate_id
--   from machimoa_review.curation_candidates
--   order by revision_seq, id;
--
-- Post-apply audit: repeat the catalog, privilege, overload, and
-- fingerprint queries. Confirm public.is_latest_source_revision has
-- exactly one 3-argument overload, owner postgres, SECURITY DEFINER,
-- search_path="", and EXECUTE for service_role only. Confirm enqueue,
-- publish, reject, candidate schema/table/sequence, and public.curations
-- write grants are unchanged. Confirm row counts and the id/slug/status
-- fingerprints above match the pre-apply capture.

begin;

create temporary table p1_latest_source_revision_acl_snapshot (
  k pg_catalog.text primary key,
  v pg_catalog.text
) on commit drop;

do $guard$
declare
  v_schema_owner pg_catalog.name;
  v_candidates_owner pg_catalog.name;
  v_bad_columns pg_catalog.text;
  v_index_oid pg_catalog.regclass;
  v_indexdef pg_catalog.text;
  v_enqueue_count pg_catalog.int4;
  v_enqueue_identity pg_catalog.text;
  v_enqueue_16 pg_catalog.regprocedure;
  v_enqueue_owner pg_catalog.name;
  v_enqueue_secdef pg_catalog.bool;
  v_enqueue_config pg_catalog.text[];
  v_existing_precheck pg_catalog.text;
  v_enqueue_lookup pg_catalog.text :=
    'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)';
  v_publish_lookup pg_catalog.text :=
    'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)';
  v_reject_lookup pg_catalog.text :=
    'machimoa_review.reject_curation_candidate(uuid,text,text)';
begin
  -- Supabase CLI 2.116.0 linked db push: session_user=cli_login_postgres,
  -- current_user=postgres. DDL authorization still requires current_user=postgres.
  -- session_user is an exact allowlist: postgres or cli_login_postgres.
  if current_user <> 'postgres'
     or session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'P1 latest source revision migration must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  select pg_catalog.pg_get_userbyid(n.nspowner)
    into v_schema_owner
  from pg_catalog.pg_namespace as n
  where n.nspname = 'machimoa_review';

  if v_schema_owner is null then
    raise exception 'schema machimoa_review does not exist';
  end if;

  if v_schema_owner <> 'postgres' then
    raise exception
      'schema machimoa_review must be owned by postgres, got %',
      v_schema_owner;
  end if;

  select pg_catalog.pg_get_userbyid(c.relowner)
    into v_candidates_owner
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'machimoa_review'
    and c.relname = 'curation_candidates'
    and c.relkind in ('r', 'p');

  if v_candidates_owner is null then
    raise exception
      'table machimoa_review.curation_candidates does not exist';
  end if;

  if v_candidates_owner <> 'postgres' then
    raise exception
      'machimoa_review.curation_candidates must be owned by postgres, got %',
      v_candidates_owner;
  end if;

  select pg_catalog.string_agg(expected.col, ', ' order by expected.col)
    into v_bad_columns
  from (
    values
      ('source'::pg_catalog.name, 'pg_catalog.text'::pg_catalog.regtype, true, ''::pg_catalog.text),
      ('source_item_id', 'pg_catalog.text'::pg_catalog.regtype, true, ''),
      ('source_revision_hash', 'pg_catalog.text'::pg_catalog.regtype, true, ''),
      ('revision_seq', 'pg_catalog.int8'::pg_catalog.regtype, true, 'a')
  ) as expected(col, typ, nn, ident)
  left join pg_catalog.pg_attribute as a
    on a.attrelid =
         'machimoa_review.curation_candidates'::pg_catalog.regclass
   and a.attname = expected.col
   and a.attnum > 0
   and not a.attisdropped
  where a.attname is null
     or a.atttypid is distinct from expected.typ
     or a.attnotnull is distinct from expected.nn
     or a.attidentity is distinct from expected.ident;

  if v_bad_columns is not null then
    raise exception
      'curation_candidates source/revision columns are missing or have an unexpected type (%)',
      v_bad_columns;
  end if;

  v_index_oid := pg_catalog.to_regclass(
    'machimoa_review.curation_candidates_source_revision_idx'
  );
  if v_index_oid is null then
    raise exception
      'index machimoa_review.curation_candidates_source_revision_idx does not exist';
  end if;

  v_indexdef := pg_catalog.pg_get_indexdef(v_index_oid);
  if v_indexdef is distinct from
       'CREATE INDEX curation_candidates_source_revision_idx ON machimoa_review.curation_candidates USING btree (source, source_item_id, revision_seq DESC)'
  then
    raise exception
      'curation_candidates_source_revision_idx definition does not match the P1 lookup index (%)',
      v_indexdef;
  end if;

  select
    pg_catalog.count(*)::pg_catalog.int4,
    pg_catalog.string_agg(
      pg_catalog.pg_get_function_identity_arguments(p.oid),
      ' | '
      order by pg_catalog.pg_get_function_identity_arguments(p.oid)
    ),
    pg_catalog.min(pg_catalog.pg_get_userbyid(p.proowner))
    into v_enqueue_count, v_enqueue_identity, v_enqueue_owner
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'enqueue_curation_candidate';

  if v_enqueue_count is distinct from 1 then
    raise exception
      'expected exactly one public.enqueue_curation_candidate overload, found % (%)',
      coalesce(v_enqueue_count, 0),
      coalesce(v_enqueue_identity, 'none');
  end if;

  v_enqueue_16 := pg_catalog.to_regprocedure(v_enqueue_lookup);
  if v_enqueue_16 is null then
    raise exception
      'expected 16-argument enqueue_curation_candidate, found (%)',
      coalesce(v_enqueue_identity, 'none');
  end if;

  if v_enqueue_owner <> 'postgres' then
    raise exception
      'public.enqueue_curation_candidate must be owned by postgres, got %',
      v_enqueue_owner;
  end if;

  select p.prosecdef, p.proconfig
    into v_enqueue_secdef, v_enqueue_config
  from pg_catalog.pg_proc as p
  where p.oid = v_enqueue_16;

  if v_enqueue_secdef is distinct from true then
    raise exception
      'public.enqueue_curation_candidate must be SECURITY DEFINER';
  end if;

  if v_enqueue_config is distinct from array['search_path=""'::pg_catalog.text] then
    raise exception
      'public.enqueue_curation_candidate search_path must be empty, got %',
      v_enqueue_config;
  end if;

  if pg_catalog.to_regprocedure(v_publish_lookup) is null then
    raise exception
      'function machimoa_review.publish_curation_candidate(uuid,text,text,boolean) does not exist';
  end if;

  if pg_catalog.to_regprocedure(v_reject_lookup) is null then
    raise exception
      'function machimoa_review.reject_curation_candidate(uuid,text,text) does not exist';
  end if;

  select pg_catalog.string_agg(
           'public.is_latest_source_revision('
             || pg_catalog.pg_get_function_identity_arguments(p.oid)
             || ')',
           ', '
           order by pg_catalog.pg_get_function_identity_arguments(p.oid)
         )
    into v_existing_precheck
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'is_latest_source_revision';

  if v_existing_precheck is not null then
    raise exception
      'function public.is_latest_source_revision already exists (%); refusing to reuse or drop it',
      v_existing_precheck;
  end if;

  insert into p1_latest_source_revision_acl_snapshot (k, v)
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

create function public.is_latest_source_revision(
  p_source pg_catalog.text,
  p_source_item_id pg_catalog.text,
  p_source_revision_hash pg_catalog.text
)
returns pg_catalog.bool
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_source pg_catalog.text :=
    pg_catalog.lower(pg_catalog.btrim(coalesce(p_source, '')));
  v_source_item_id pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_source_item_id, ''));
  v_source_revision_hash pg_catalog.text :=
    pg_catalog.lower(
      pg_catalog.btrim(coalesce(p_source_revision_hash, ''))
    );
  v_latest_hash pg_catalog.text;
begin
  if v_source !~ '^[a-z][a-z0-9_]{1,31}$' then
    raise exception 'source must match ^[a-z][a-z0-9_]{1,31}$';
  end if;

  if pg_catalog.char_length(v_source_item_id) not between 1 and 128 then
    raise exception 'source_item_id length must be between 1 and 128';
  end if;

  if v_source_revision_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'source_revision_hash must be 64 lowercase hex characters';
  end if;

  select c.source_revision_hash
    into v_latest_hash
  from machimoa_review.curation_candidates as c
  where c.source = v_source
    and c.source_item_id = v_source_item_id
  order by c.revision_seq desc
  limit 1;

  if not found then
    return false;
  end if;

  return v_latest_hash = v_source_revision_hash;
end
$function$;

alter function public.is_latest_source_revision(
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text
)
owner to postgres;

revoke all privileges
  on function public.is_latest_source_revision(
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text
  )
  from public, anon, authenticated, service_role;

grant execute
  on function public.is_latest_source_revision(
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text
  )
  to service_role;

do $post$
declare
  v_precheck_count pg_catalog.int4;
  v_precheck_identity pg_catalog.text;
  v_precheck_oid pg_catalog.oid;
  v_precheck_reg pg_catalog.regprocedure;
  v_precheck_owner pg_catalog.name;
  v_precheck_secdef pg_catalog.bool;
  v_precheck_config pg_catalog.text[];
  v_precheck_src pg_catalog.text;
  v_enqueue_16 pg_catalog.regprocedure;
  v_changed pg_catalog.text;
  v_enqueue_lookup pg_catalog.text :=
    'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)';
  v_publish_lookup pg_catalog.text :=
    'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)';
  v_reject_lookup pg_catalog.text :=
    'machimoa_review.reject_curation_candidate(uuid,text,text)';
  v_precheck_lookup pg_catalog.text :=
    'public.is_latest_source_revision(text,text,text)';
begin
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
      'expected exactly one public.is_latest_source_revision overload, found % (%)',
      coalesce(v_precheck_count, 0),
      coalesce(v_precheck_identity, 'none');
  end if;

  v_precheck_reg := pg_catalog.to_regprocedure(v_precheck_lookup);
  if v_precheck_reg is null then
    raise exception
      'expected 3-argument is_latest_source_revision(text,text,text), found (%)',
      coalesce(v_precheck_identity, 'none');
  end if;

  if v_precheck_reg::pg_catalog.oid is distinct from v_precheck_oid then
    raise exception
      'is_latest_source_revision overload does not match the 3-argument lookup (%)',
      coalesce(v_precheck_identity, 'none');
  end if;

  select
    pg_catalog.pg_get_userbyid(p.proowner),
    p.prosecdef,
    p.proconfig,
    p.prosrc
    into
      v_precheck_owner,
      v_precheck_secdef,
      v_precheck_config,
      v_precheck_src
  from pg_catalog.pg_proc as p
  where p.oid = v_precheck_reg;

  if v_precheck_owner <> 'postgres' then
    raise exception
      'public.is_latest_source_revision must be owned by postgres, got %',
      v_precheck_owner;
  end if;

  if v_precheck_secdef is distinct from true then
    raise exception
      'public.is_latest_source_revision must be SECURITY DEFINER';
  end if;

  if v_precheck_config is distinct from array['search_path=""'::pg_catalog.text] then
    raise exception
      'public.is_latest_source_revision search_path must be empty, got %',
      v_precheck_config;
  end if;

  if pg_catalog.has_function_privilege('anon', v_precheck_reg, 'EXECUTE')
     or pg_catalog.has_function_privilege(
          'authenticated', v_precheck_reg, 'EXECUTE'
        )
     or pg_catalog.has_function_privilege('public', v_precheck_reg, 'EXECUTE')
  then
    raise exception
      'is_latest_source_revision EXECUTE remains granted to PUBLIC or an API role';
  end if;

  if not pg_catalog.has_function_privilege(
       'service_role', v_precheck_reg, 'EXECUTE'
     )
  then
    raise exception
      'service_role must have EXECUTE on is_latest_source_revision';
  end if;

  if v_precheck_src ~* '\m(insert|update|delete|truncate|lock|execute)\M'
     or v_precheck_src ~* 'pg_advisory'
     or v_precheck_src ~* '\mformat\s*\('
  then
    raise exception
      'is_latest_source_revision body must not write, lock, or use dynamic SQL';
  end if;

  v_enqueue_16 := pg_catalog.to_regprocedure(v_enqueue_lookup);

  select pg_catalog.string_agg(s.k, ', ' order by s.k)
    into v_changed
  from p1_latest_source_revision_acl_snapshot as s
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
      'candidate schema/table/sequence privileges, enqueue/publish/reject ACL, or data fingerprints changed (%)',
      v_changed;
  end if;
end
$post$;

commit;
