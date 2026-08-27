-- P1 bilingual curations: add nullable ko/ja language columns and replace
-- enqueue/publish bodies so publish requires all six reviewed language fields.
-- Non-destructive rollback:
--   supabase/rollback/20260827121818_p1_bilingual_curations_down.sql
-- Destructive cleanup:
--   supabase/rollback/20260827121818_p1_bilingual_curations_cleanup.sql
--
-- Do not apply this file to the operating database without an explicit
-- approval that is separate from committing the SQL. This transaction
-- must not delete curation or candidate rows.
--
-- Pre-apply audit (read-only; do not record title, summary, content, or
-- raw_payload). Run as postgres before applying:
--
--   select current_user, session_user;
--
--   select n.nspname, c.relname, pg_catalog.pg_get_userbyid(c.relowner) as owner
--   from pg_catalog.pg_class as c
--   join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
--   where (n.nspname, c.relname) in (
--     ('public', 'curations'),
--     ('machimoa_review', 'curation_candidates')
--   )
--     and c.relkind in ('r', 'p');
--
--   select n.nspname, c.relname, a.attname, a.attacl
--   from pg_catalog.pg_attribute as a
--   join pg_catalog.pg_class as c on c.oid = a.attrelid
--   join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
--   where a.attnum > 0
--     and not a.attisdropped
--     and a.attacl is not null
--     and (n.nspname, c.relname) in (
--       ('public', 'curations'),
--       ('machimoa_review', 'curation_candidates')
--     );
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
--     ('machimoa_review', 'publish_curation_candidate'),
--     ('machimoa_review', 'reject_curation_candidate'),
--     ('machimoa_review', 'set_candidate_updated_at')
--   )
--   order by 1;
--
--   select c.relname,
--          c.relacl,
--          pg_catalog.has_table_privilege('anon', c.oid, 'select') as anon_select,
--          pg_catalog.has_table_privilege('authenticated', c.oid, 'select')
--            as authenticated_select,
--          pg_catalog.has_table_privilege('service_role', c.oid, 'select')
--            as service_role_select,
--          pg_catalog.has_table_privilege('anon', c.oid, 'insert') as anon_insert,
--          pg_catalog.has_table_privilege('authenticated', c.oid, 'insert')
--            as authenticated_insert,
--          pg_catalog.has_table_privilege('service_role', c.oid, 'insert')
--            as service_role_insert
--   from pg_catalog.pg_class as c
--   join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
--   where (n.nspname, c.relname) in (
--     ('public', 'curations'),
--     ('machimoa_review', 'curation_candidates')
--   );
--
--   select t.tgname,
--          t.tgenabled,
--          pg_catalog.pg_get_triggerdef(t.oid, true) as definition
--   from pg_catalog.pg_trigger as t
--   where t.tgrelid =
--           'machimoa_review.curation_candidates'::pg_catalog.regclass
--     and not t.tgisinternal;
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
--          source_revision_hash,
--          ai_status,
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
-- Post-apply audit: repeat the privilege, overload, trigger, and fingerprint
-- queries. Confirm enqueue identity is the 16-argument signature, Japanese
-- columns are null on existing rows, and created_at/updated_at fingerprints
-- match the pre-apply capture.

begin;

do $guard$
declare
  v_curations_owner pg_catalog.name;
  v_candidates_owner pg_catalog.name;
  v_column_acls pg_catalog.text;
  v_existing_new_columns pg_catalog.text;
  v_enqueue_count pg_catalog.int4;
  v_enqueue_identity pg_catalog.text;
  v_enqueue_owner pg_catalog.name;
  v_publish_reg pg_catalog.regprocedure;
  v_reject_reg pg_catalog.regprocedure;
  v_publish_owner pg_catalog.name;
  v_reject_owner pg_catalog.name;
  v_trigger_name pg_catalog.name;
  v_trigger_enabled pg_catalog.char;
  v_trigger_fn_schema pg_catalog.name;
  v_trigger_fn_name pg_catalog.name;
  v_trigger_count pg_catalog.int4;
  v_curations_count pg_catalog.int8;
  v_candidates_count pg_catalog.int8;
begin
  if current_user <> 'postgres' or session_user <> 'postgres' then
    raise exception
      'P1 bilingual curations migration must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  select pg_catalog.pg_get_userbyid(c.relowner)
    into v_curations_owner
  from pg_catalog.pg_class as c
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where n.nspname = 'public'
    and c.relname = 'curations'
    and c.relkind in ('r', 'p');

  if v_curations_owner is null then
    raise exception 'table public.curations does not exist';
  end if;

  if v_curations_owner <> 'postgres' then
    raise exception
      'public.curations must be owned by postgres, got %',
      v_curations_owner;
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

  select pg_catalog.string_agg(
           n.nspname || '.' || c.relname || '.' || a.attname,
           ', '
           order by n.nspname, c.relname, a.attname
         )
    into v_column_acls
  from pg_catalog.pg_attribute as a
  join pg_catalog.pg_class as c
    on c.oid = a.attrelid
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where a.attnum > 0
    and not a.attisdropped
    and a.attacl is not null
    and (
      (n.nspname = 'public' and c.relname = 'curations')
      or (
        n.nspname = 'machimoa_review'
        and c.relname = 'curation_candidates'
      )
    );

  if v_column_acls is not null then
    raise exception
      'column-level grants exist on (%); inspect and resolve them manually',
      v_column_acls;
  end if;

  select pg_catalog.string_agg(
           n.nspname || '.' || c.relname || '.' || a.attname,
           ', '
           order by n.nspname, c.relname, a.attname
         )
    into v_existing_new_columns
  from pg_catalog.pg_attribute as a
  join pg_catalog.pg_class as c
    on c.oid = a.attrelid
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where a.attnum > 0
    and not a.attisdropped
    and (
      (
        n.nspname = 'public'
        and c.relname = 'curations'
        and a.attname in (
          'title_ko',
          'title_ja',
          'summary_ko',
          'summary_ja',
          'content_ko',
          'content_ja',
          'ai_status_ko',
          'ai_status_ja'
        )
      )
      or (
        n.nspname = 'machimoa_review'
        and c.relname = 'curation_candidates'
        and a.attname in (
          'title_ko',
          'title_ja',
          'summary_ko',
          'summary_ja',
          'content_ko',
          'content_ja',
          'ai_status_ko',
          'ai_status_ja'
        )
      )
    );

  if v_existing_new_columns is not null then
    raise exception
      'bilingual columns already exist (%); refusing to reuse them',
      v_existing_new_columns;
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

  if v_enqueue_identity is distinct from
       'text, text, text, text, text, text, jsonb, text, text, text, text, text'
  then
    raise exception
      'expected 12-argument enqueue_curation_candidate, found (%)',
      v_enqueue_identity;
  end if;

  if v_enqueue_owner <> 'postgres' then
    raise exception
      'public.enqueue_curation_candidate must be owned by postgres, got %',
      v_enqueue_owner;
  end if;

  v_publish_reg := pg_catalog.to_regprocedure(
    'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'
  );
  v_reject_reg := pg_catalog.to_regprocedure(
    'machimoa_review.reject_curation_candidate(uuid,text,text)'
  );

  if v_publish_reg is null then
    raise exception
      'function machimoa_review.publish_curation_candidate(uuid,text,text,boolean) does not exist';
  end if;

  if v_reject_reg is null then
    raise exception
      'function machimoa_review.reject_curation_candidate(uuid,text,text) does not exist';
  end if;

  select pg_catalog.pg_get_userbyid(p.proowner)
    into v_publish_owner
  from pg_catalog.pg_proc as p
  where p.oid = v_publish_reg;

  select pg_catalog.pg_get_userbyid(p.proowner)
    into v_reject_owner
  from pg_catalog.pg_proc as p
  where p.oid = v_reject_reg;

  if v_publish_owner <> 'postgres' then
    raise exception
      'publish_curation_candidate must be owned by postgres, got %',
      v_publish_owner;
  end if;

  if v_reject_owner <> 'postgres' then
    raise exception
      'reject_curation_candidate must be owned by postgres, got %',
      v_reject_owner;
  end if;

  select
    pg_catalog.count(*)::pg_catalog.int4,
    pg_catalog.min(t.tgname),
    pg_catalog.min(t.tgenabled),
    pg_catalog.min(n.nspname),
    pg_catalog.min(p.proname)
    into
      v_trigger_count,
      v_trigger_name,
      v_trigger_enabled,
      v_trigger_fn_schema,
      v_trigger_fn_name
  from pg_catalog.pg_trigger as t
  join pg_catalog.pg_proc as p
    on p.oid = t.tgfoid
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where t.tgrelid =
          'machimoa_review.curation_candidates'::pg_catalog.regclass
    and not t.tgisinternal;

  if v_trigger_count is distinct from 1 then
    raise exception
      'expected exactly one user trigger on curation_candidates, found %',
      coalesce(v_trigger_count, 0);
  end if;

  if v_trigger_name is distinct from 'curation_candidates_set_updated_at'
     or v_trigger_enabled is distinct from 'O'
     or v_trigger_fn_schema is distinct from 'machimoa_review'
     or v_trigger_fn_name is distinct from 'set_candidate_updated_at'
  then
    raise exception
      'unexpected candidate updated_at trigger (name=%, enabled=%, function=%.%)',
      v_trigger_name,
      v_trigger_enabled,
      v_trigger_fn_schema,
      v_trigger_fn_name;
  end if;

  select pg_catalog.count(*)
    into v_curations_count
  from public.curations;

  select pg_catalog.count(*)
    into v_candidates_count
  from machimoa_review.curation_candidates;

  if v_curations_count is distinct from 2 then
    raise exception
      'expected exactly 2 public.curations rows before P1, found %',
      v_curations_count;
  end if;

  if v_candidates_count is distinct from 4 then
    raise exception
      'expected exactly 4 curation_candidates rows before P1, found %',
      v_candidates_count;
  end if;
end
$guard$;

create temporary table p1_curations_fingerprint (
  id pg_catalog.uuid primary key,
  slug pg_catalog.text not null,
  created_at pg_catalog.timestamptz not null,
  updated_at pg_catalog.timestamptz not null
)
on commit drop;

insert into p1_curations_fingerprint (
  id,
  slug,
  created_at,
  updated_at
)
select
  c.id,
  c.slug,
  c.created_at,
  c.updated_at
from public.curations as c;

create temporary table p1_candidates_fingerprint (
  id pg_catalog.uuid primary key,
  slug pg_catalog.text not null,
  review_status pg_catalog.text not null,
  revision_seq pg_catalog.int8 not null,
  created_at pg_catalog.timestamptz not null,
  updated_at pg_catalog.timestamptz not null,
  reviewed_at pg_catalog.timestamptz,
  published_at pg_catalog.timestamptz,
  superseded_at pg_catalog.timestamptz
)
on commit drop;

insert into p1_candidates_fingerprint (
  id,
  slug,
  review_status,
  revision_seq,
  created_at,
  updated_at,
  reviewed_at,
  published_at,
  superseded_at
)
select
  c.id,
  c.slug,
  c.review_status,
  c.revision_seq,
  c.created_at,
  c.updated_at,
  c.reviewed_at,
  c.published_at,
  c.superseded_at
from machimoa_review.curation_candidates as c;

alter table public.curations
  add column title_ko pg_catalog.text,
  add column title_ja pg_catalog.text,
  add column summary_ko pg_catalog.text,
  add column summary_ja pg_catalog.text,
  add column content_ko pg_catalog.text,
  add column content_ja pg_catalog.text;

alter table public.curations
  add constraint curations_title_ko_length_ck
    check (
      title_ko is null
      or (
        pg_catalog.char_length(title_ko) between 1 and 300
        and title_ko = pg_catalog.btrim(title_ko)
      )
    ),
  add constraint curations_title_ja_length_ck
    check (
      title_ja is null
      or (
        pg_catalog.char_length(title_ja) between 1 and 300
        and title_ja = pg_catalog.btrim(title_ja)
      )
    ),
  add constraint curations_summary_ko_length_ck
    check (
      summary_ko is null
      or (
        pg_catalog.char_length(summary_ko) between 1 and 1000
        and summary_ko = pg_catalog.btrim(summary_ko)
      )
    ),
  add constraint curations_summary_ja_length_ck
    check (
      summary_ja is null
      or (
        pg_catalog.char_length(summary_ja) between 1 and 1000
        and summary_ja = pg_catalog.btrim(summary_ja)
      )
    ),
  add constraint curations_content_ko_length_ck
    check (
      content_ko is null
      or (
        pg_catalog.char_length(content_ko) between 1 and 200000
        and content_ko = pg_catalog.btrim(content_ko)
      )
    ),
  add constraint curations_content_ja_length_ck
    check (
      content_ja is null
      or (
        pg_catalog.char_length(content_ja) between 1 and 200000
        and content_ja = pg_catalog.btrim(content_ja)
      )
    );

alter table machimoa_review.curation_candidates
  add column title_ko pg_catalog.text,
  add column title_ja pg_catalog.text,
  add column summary_ko pg_catalog.text,
  add column summary_ja pg_catalog.text,
  add column content_ko pg_catalog.text,
  add column content_ja pg_catalog.text,
  add column ai_status_ko pg_catalog.text,
  add column ai_status_ja pg_catalog.text;

alter table machimoa_review.curation_candidates
  add constraint curation_candidates_title_ko_length_ck
    check (
      title_ko is null
      or (
        pg_catalog.char_length(title_ko) between 1 and 300
        and title_ko = pg_catalog.btrim(title_ko)
      )
    ),
  add constraint curation_candidates_title_ja_length_ck
    check (
      title_ja is null
      or (
        pg_catalog.char_length(title_ja) between 1 and 300
        and title_ja = pg_catalog.btrim(title_ja)
      )
    ),
  add constraint curation_candidates_summary_ko_length_ck
    check (
      summary_ko is null
      or (
        pg_catalog.char_length(summary_ko) between 1 and 1000
        and summary_ko = pg_catalog.btrim(summary_ko)
      )
    ),
  add constraint curation_candidates_summary_ja_length_ck
    check (
      summary_ja is null
      or (
        pg_catalog.char_length(summary_ja) between 1 and 1000
        and summary_ja = pg_catalog.btrim(summary_ja)
      )
    ),
  add constraint curation_candidates_content_ko_length_ck
    check (
      content_ko is null
      or (
        pg_catalog.char_length(content_ko) between 1 and 200000
        and content_ko = pg_catalog.btrim(content_ko)
      )
    ),
  add constraint curation_candidates_content_ja_length_ck
    check (
      content_ja is null
      or (
        pg_catalog.char_length(content_ja) between 1 and 200000
        and content_ja = pg_catalog.btrim(content_ja)
      )
    ),
  add constraint curation_candidates_ai_status_ko_ck
    check (
      ai_status_ko is null
      or ai_status_ko in (
        'success',
        'fallback_raw',
        'empty_response',
        'skipped_no_key',
        'error'
      )
    ),
  add constraint curation_candidates_ai_status_ja_ck
    check (
      ai_status_ja is null
      or ai_status_ja in (
        'success',
        'empty_response',
        'skipped_no_key',
        'error',
        'parse_error'
      )
    );

alter table machimoa_review.curation_candidates
  disable trigger curation_candidates_set_updated_at;

update public.curations
set
  title_ko = title,
  summary_ko = summary,
  content_ko = content;

update machimoa_review.curation_candidates
set
  title_ko = title,
  summary_ko = summary,
  content_ko = content,
  ai_status_ko = ai_status;

alter table machimoa_review.curation_candidates
  enable trigger curation_candidates_set_updated_at;

do $verify$
declare
  v_changed pg_catalog.text;
  v_trigger_enabled pg_catalog.char;
begin
  select t.tgenabled
    into v_trigger_enabled
  from pg_catalog.pg_trigger as t
  where t.tgrelid =
          'machimoa_review.curation_candidates'::pg_catalog.regclass
    and t.tgname = 'curation_candidates_set_updated_at'
    and not t.tgisinternal;

  if v_trigger_enabled is distinct from 'O' then
    raise exception
      'curation_candidates_set_updated_at was not restored to enabled, got %',
      v_trigger_enabled;
  end if;

  select pg_catalog.string_agg(c.id::pg_catalog.text, ', ' order by c.id)
    into v_changed
  from public.curations as c
  join p1_curations_fingerprint as f
    on f.id = c.id
  where c.slug is distinct from f.slug
     or c.created_at is distinct from f.created_at
     or c.updated_at is distinct from f.updated_at
     or c.title_ko is distinct from c.title
     or c.summary_ko is distinct from c.summary
     or c.content_ko is distinct from c.content
     or c.title_ja is not null
     or c.summary_ja is not null
     or c.content_ja is not null;

  if v_changed is not null then
    raise exception
      'public.curations fingerprint or backfill mismatch for ids (%)',
      v_changed;
  end if;

  select pg_catalog.string_agg(c.id::pg_catalog.text, ', ' order by c.id)
    into v_changed
  from machimoa_review.curation_candidates as c
  join p1_candidates_fingerprint as f
    on f.id = c.id
  where c.slug is distinct from f.slug
     or c.review_status is distinct from f.review_status
     or c.revision_seq is distinct from f.revision_seq
     or c.created_at is distinct from f.created_at
     or c.updated_at is distinct from f.updated_at
     or c.reviewed_at is distinct from f.reviewed_at
     or c.published_at is distinct from f.published_at
     or c.superseded_at is distinct from f.superseded_at
     or c.title_ko is distinct from c.title
     or c.summary_ko is distinct from c.summary
     or c.content_ko is distinct from c.content
     or c.ai_status_ko is distinct from c.ai_status
     or c.title_ja is not null
     or c.summary_ja is not null
     or c.content_ja is not null
     or c.ai_status_ja is not null;

  if v_changed is not null then
    raise exception
      'curation_candidates fingerprint or backfill mismatch for ids (%)',
      v_changed;
  end if;

  if (
    select pg_catalog.count(*) from p1_curations_fingerprint
  ) is distinct from (
    select pg_catalog.count(*) from public.curations
  ) then
    raise exception 'public.curations row count changed during P1 backfill';
  end if;

  if (
    select pg_catalog.count(*) from p1_candidates_fingerprint
  ) is distinct from (
    select pg_catalog.count(*) from machimoa_review.curation_candidates
  ) then
    raise exception
      'curation_candidates row count changed during P1 backfill';
  end if;
end
$verify$;

drop function public.enqueue_curation_candidate(
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.jsonb,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text
);

create function public.enqueue_curation_candidate(
  p_source pg_catalog.text,
  p_source_item_id pg_catalog.text,
  p_source_revision_hash pg_catalog.text,
  p_slug pg_catalog.text,
  p_title_ko pg_catalog.text,
  p_content_ko pg_catalog.text,
  p_raw_payload pg_catalog.jsonb,
  p_ai_status_ko pg_catalog.text,
  p_category pg_catalog.text default null,
  p_summary_ko pg_catalog.text default null,
  p_source_url pg_catalog.text default null,
  p_ai_model pg_catalog.text default null,
  p_title_ja pg_catalog.text default null,
  p_content_ja pg_catalog.text default null,
  p_summary_ja pg_catalog.text default null,
  p_ai_status_ja pg_catalog.text default null
)
returns table (
  candidate_id pg_catalog.uuid,
  outcome pg_catalog.text,
  superseded_candidate_id pg_catalog.uuid
)
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
  v_slug pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_slug, ''));
  v_title_ko pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_title_ko, ''));
  v_content_ko pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_content_ko, ''));
  v_raw_payload pg_catalog.jsonb := p_raw_payload;
  v_ai_status_ko pg_catalog.text :=
    pg_catalog.lower(pg_catalog.btrim(coalesce(p_ai_status_ko, '')));
  v_category pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_category, '')), '');
  v_summary_ko pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_summary_ko, '')), '');
  v_source_url pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_source_url, '')), '');
  v_ai_model pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_ai_model, '')), '');
  v_title_ja pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_title_ja, '')), '');
  v_content_ja pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_content_ja, '')), '');
  v_summary_ja pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_summary_ja, '')), '');
  v_ai_status_ja pg_catalog.text :=
    nullif(
      pg_catalog.lower(pg_catalog.btrim(coalesce(p_ai_status_ja, ''))),
      ''
    );
  v_latest_id pg_catalog.uuid;
  v_latest_hash pg_catalog.text;
  v_new_id pg_catalog.uuid;
  v_superseded_id pg_catalog.uuid;
  v_now pg_catalog.timestamptz;
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

  if pg_catalog.char_length(v_slug) not between 1 and 128 then
    raise exception 'slug length must be between 1 and 128';
  end if;

  if pg_catalog.char_length(v_title_ko) not between 1 and 300 then
    raise exception 'title_ko length must be between 1 and 300';
  end if;

  if pg_catalog.char_length(v_content_ko) not between 1 and 200000 then
    raise exception 'content_ko length must be between 1 and 200000';
  end if;

  if v_category is not null
     and pg_catalog.char_length(v_category) > 100 then
    raise exception 'category length must not exceed 100';
  end if;

  if v_summary_ko is not null
     and pg_catalog.char_length(v_summary_ko) > 1000 then
    raise exception 'summary_ko length must not exceed 1000';
  end if;

  if v_title_ja is not null
     and pg_catalog.char_length(v_title_ja) not between 1 and 300 then
    raise exception 'title_ja length must be between 1 and 300';
  end if;

  if v_content_ja is not null
     and pg_catalog.char_length(v_content_ja) not between 1 and 200000 then
    raise exception 'content_ja length must be between 1 and 200000';
  end if;

  if v_summary_ja is not null
     and pg_catalog.char_length(v_summary_ja) > 1000 then
    raise exception 'summary_ja length must not exceed 1000';
  end if;

  if v_ai_model is not null
     and pg_catalog.char_length(v_ai_model) > 100 then
    raise exception 'ai_model length must not exceed 100';
  end if;

  if v_ai_status_ko not in (
    'success',
    'fallback_raw',
    'empty_response',
    'skipped_no_key',
    'error'
  ) then
    raise exception 'invalid ai_status_ko: %', v_ai_status_ko;
  end if;

  if v_ai_status_ja is not null
     and v_ai_status_ja not in (
       'success',
       'empty_response',
       'skipped_no_key',
       'error',
       'parse_error'
     ) then
    raise exception 'invalid ai_status_ja: %', v_ai_status_ja;
  end if;

  if v_source_url is not null
     and (
       v_source_url !~ '^https?://'
       or pg_catalog.char_length(v_source_url) > 2048
     ) then
    raise exception 'source_url must be an HTTP(S) URL up to 2048 characters';
  end if;

  if v_raw_payload is null
     or pg_catalog.jsonb_typeof(v_raw_payload) <> 'object' then
    raise exception 'raw_payload must be a JSON object';
  end if;

  if pg_catalog.octet_length(v_raw_payload::pg_catalog.text) > 65536 then
    raise exception 'raw_payload must not exceed 65536 bytes';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      v_source || ':' || v_source_item_id,
      0::pg_catalog.int8
    )
  );

  select c.id, c.source_revision_hash
    into v_latest_id, v_latest_hash
  from machimoa_review.curation_candidates as c
  where c.source = v_source
    and c.source_item_id = v_source_item_id
  order by c.revision_seq desc
  limit 1;

  if found and v_latest_hash = v_source_revision_hash then
    return query
    select
      v_latest_id,
      'duplicate'::pg_catalog.text,
      null::pg_catalog.uuid;
    return;
  end if;

  v_new_id := pg_catalog.gen_random_uuid();
  v_now := pg_catalog.now();

  update machimoa_review.curation_candidates as c
  set
    review_status = 'superseded',
    superseded_at = v_now,
    superseded_by_candidate_id = v_new_id
  where c.source = v_source
    and c.source_item_id = v_source_item_id
    and c.review_status = 'pending'
  returning c.id into v_superseded_id;

  insert into machimoa_review.curation_candidates (
    id,
    source,
    source_item_id,
    source_revision_hash,
    slug,
    category,
    title,
    summary,
    content,
    source_url,
    raw_payload,
    ai_status,
    ai_model,
    title_ko,
    summary_ko,
    content_ko,
    ai_status_ko,
    title_ja,
    summary_ja,
    content_ja,
    ai_status_ja
  )
  values (
    v_new_id,
    v_source,
    v_source_item_id,
    v_source_revision_hash,
    v_slug,
    v_category,
    v_title_ko,
    v_summary_ko,
    v_content_ko,
    v_source_url,
    v_raw_payload,
    v_ai_status_ko,
    v_ai_model,
    v_title_ko,
    v_summary_ko,
    v_content_ko,
    v_ai_status_ko,
    v_title_ja,
    v_summary_ja,
    v_content_ja,
    v_ai_status_ja
  );

  return query
  select
    v_new_id,
    'inserted'::pg_catalog.text,
    v_superseded_id;
end
$function$;

alter function public.enqueue_curation_candidate(
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.jsonb,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.text
)
owner to postgres;

revoke all privileges
  on function public.enqueue_curation_candidate(
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.jsonb,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text
  )
  from public, anon, authenticated, service_role;

grant execute
  on function public.enqueue_curation_candidate(
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.jsonb,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.text
  )
  to service_role;

drop function machimoa_review.publish_curation_candidate(
  pg_catalog.uuid,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.bool
);

create function machimoa_review.publish_curation_candidate(
  p_candidate_id pg_catalog.uuid,
  p_reviewed_by pg_catalog.text,
  p_review_notes pg_catalog.text default null,
  p_allow_overwrite pg_catalog.bool default false
)
returns pg_catalog.uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_candidate_id pg_catalog.uuid := p_candidate_id;
  v_reviewed_by pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_reviewed_by, '')), '');
  v_review_notes pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_review_notes, '')), '');
  v_allow_overwrite pg_catalog.bool := coalesce(p_allow_overwrite, false);
  v_review_status pg_catalog.text;
  v_source pg_catalog.text;
  v_source_item_id pg_catalog.text;
  v_slug pg_catalog.text;
  v_category pg_catalog.text;
  v_title_ko pg_catalog.text;
  v_title_ja pg_catalog.text;
  v_summary_ko pg_catalog.text;
  v_summary_ja pg_catalog.text;
  v_content_ko pg_catalog.text;
  v_content_ja pg_catalog.text;
  v_source_url pg_catalog.text;
  v_source_match_id pg_catalog.uuid;
  v_slug_match_id pg_catalog.uuid;
  v_slug_match_source pg_catalog.text;
  v_curation_id pg_catalog.uuid;
  v_target record;
  v_now pg_catalog.timestamptz := pg_catalog.now();
begin
  if v_candidate_id is null then
    raise exception 'candidate_id is required';
  end if;

  if v_reviewed_by is null
     or pg_catalog.char_length(v_reviewed_by) > 128 then
    raise exception
      'reviewed_by must contain 1 to 128 non-whitespace characters';
  end if;

  if v_review_notes is not null
     and pg_catalog.char_length(v_review_notes) > 4000 then
    raise exception 'review_notes length must not exceed 4000';
  end if;

  select
    c.review_status,
    pg_catalog.lower(pg_catalog.btrim(c.source)),
    pg_catalog.btrim(c.source_item_id),
    pg_catalog.btrim(c.slug),
    nullif(pg_catalog.btrim(coalesce(c.category, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.title_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.title_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.summary_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.summary_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.content_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.content_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.source_url, '')), '')
  into
    v_review_status,
    v_source,
    v_source_item_id,
    v_slug,
    v_category,
    v_title_ko,
    v_title_ja,
    v_summary_ko,
    v_summary_ja,
    v_content_ko,
    v_content_ja,
    v_source_url
  from machimoa_review.curation_candidates as c
  where c.id = v_candidate_id
  for update;

  if not found then
    raise exception 'curation candidate % does not exist', v_candidate_id;
  end if;

  if v_review_status <> 'pending' then
    raise exception
      'curation candidate % is %, expected pending',
      v_candidate_id,
      v_review_status;
  end if;

  if v_source !~ '^[a-z][a-z0-9_]{1,31}$' then
    raise exception 'candidate source has an invalid format';
  end if;

  if pg_catalog.char_length(v_source_item_id) not between 1 and 128 then
    raise exception 'candidate source_item_id is empty or too long';
  end if;

  if pg_catalog.char_length(v_slug) not between 1 and 128 then
    raise exception 'candidate slug is empty or too long';
  end if;

  if v_category is null
     or pg_catalog.char_length(v_category) > 100 then
    raise exception 'candidate category is required and must not exceed 100';
  end if;

  if v_title_ko is null
     or pg_catalog.char_length(v_title_ko) not between 1 and 300 then
    raise exception 'candidate title_ko is empty or too long';
  end if;

  if v_title_ja is null
     or pg_catalog.char_length(v_title_ja) not between 1 and 300 then
    raise exception 'candidate title_ja is empty or too long';
  end if;

  if v_summary_ko is null
     or pg_catalog.char_length(v_summary_ko) not between 1 and 1000 then
    raise exception
      'candidate summary_ko is required and must not exceed 1000';
  end if;

  if v_summary_ja is null
     or pg_catalog.char_length(v_summary_ja) not between 1 and 1000 then
    raise exception
      'candidate summary_ja is required and must not exceed 1000';
  end if;

  if v_content_ko is null
     or pg_catalog.char_length(v_content_ko) not between 1 and 200000 then
    raise exception 'candidate content_ko is empty or too long';
  end if;

  if v_content_ja is null
     or pg_catalog.char_length(v_content_ja) not between 1 and 200000 then
    raise exception 'candidate content_ja is empty or too long';
  end if;

  if v_source_url is null
     or v_source_url !~ '^https?://'
     or pg_catalog.char_length(v_source_url) > 2048 then
    raise exception
      'candidate source_url is required and must be an HTTP(S) URL';
  end if;

  -- Lock every existing target row in deterministic UUID order.
  for v_target in
    select
      c.id,
      c.source,
      c.source_item_id,
      c.slug
    from public.curations as c
    where (
      c.source = v_source
      and c.source_item_id = v_source_item_id
    )
    or c.slug = v_slug
    order by c.id
    for update
  loop
    if v_target.source = v_source
       and v_target.source_item_id = v_source_item_id then
      v_source_match_id := v_target.id;
    end if;

    if v_target.slug = v_slug then
      v_slug_match_id := v_target.id;
      v_slug_match_source := v_target.source;
    end if;
  end loop;

  if v_source_match_id is null and v_slug_match_id is null then
    insert into public.curations (
      slug,
      category,
      title,
      summary,
      content,
      title_ko,
      title_ja,
      summary_ko,
      summary_ja,
      content_ko,
      content_ja,
      source,
      source_item_id,
      source_url,
      updated_at
    )
    values (
      v_slug,
      v_category,
      v_title_ko,
      v_summary_ko,
      v_content_ko,
      v_title_ko,
      v_title_ja,
      v_summary_ko,
      v_summary_ja,
      v_content_ko,
      v_content_ja,
      v_source,
      v_source_item_id,
      v_source_url,
      v_now
    )
    returning id into v_curation_id;
  elsif v_source_match_id is not null
        and (
          v_slug_match_id is null
          or v_slug_match_id = v_source_match_id
        ) then
    update public.curations as c
    set
      slug = v_slug,
      category = v_category,
      title = v_title_ko,
      summary = v_summary_ko,
      content = v_content_ko,
      title_ko = v_title_ko,
      title_ja = v_title_ja,
      summary_ko = v_summary_ko,
      summary_ja = v_summary_ja,
      content_ko = v_content_ko,
      content_ja = v_content_ja,
      source = v_source,
      source_item_id = v_source_item_id,
      source_url = v_source_url,
      updated_at = v_now
    where c.id = v_source_match_id
    returning c.id into v_curation_id;
  elsif v_source_match_id is null and v_slug_match_id is not null then
    if v_slug_match_source is not null then
      raise exception
        'slug % belongs to a different sourced curation',
        v_slug;
    end if;

    if not v_allow_overwrite then
      raise exception
        'slug % belongs to a legacy curation; explicit overwrite approval is required',
        v_slug;
    end if;

    update public.curations as c
    set
      slug = v_slug,
      category = v_category,
      title = v_title_ko,
      summary = v_summary_ko,
      content = v_content_ko,
      title_ko = v_title_ko,
      title_ja = v_title_ja,
      summary_ko = v_summary_ko,
      summary_ja = v_summary_ja,
      content_ko = v_content_ko,
      content_ja = v_content_ja,
      source = v_source,
      source_item_id = v_source_item_id,
      source_url = v_source_url,
      updated_at = v_now
    where c.id = v_slug_match_id
    returning c.id into v_curation_id;
  else
    raise exception
      'candidate source and slug resolve to different public curations';
  end if;

  update machimoa_review.curation_candidates as c
  set
    review_status = 'published',
    review_notes = v_review_notes,
    reviewed_at = v_now,
    reviewed_by = v_reviewed_by,
    published_at = v_now,
    published_curation_id = v_curation_id
  where c.id = v_candidate_id;

  return v_curation_id;
end
$function$;

alter function machimoa_review.publish_curation_candidate(
  pg_catalog.uuid,
  pg_catalog.text,
  pg_catalog.text,
  pg_catalog.bool
)
owner to postgres;

revoke all privileges
  on function machimoa_review.publish_curation_candidate(
    pg_catalog.uuid,
    pg_catalog.text,
    pg_catalog.text,
    pg_catalog.bool
  )
  from public, anon, authenticated, service_role;

drop function machimoa_review.reject_curation_candidate(
  pg_catalog.uuid,
  pg_catalog.text,
  pg_catalog.text
);

create function machimoa_review.reject_curation_candidate(
  p_candidate_id pg_catalog.uuid,
  p_reviewed_by pg_catalog.text,
  p_review_notes pg_catalog.text
)
returns pg_catalog.uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_candidate_id pg_catalog.uuid := p_candidate_id;
  v_reviewed_by pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_reviewed_by, '')), '');
  v_review_notes pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_review_notes, '')), '');
  v_review_status pg_catalog.text;
  v_now pg_catalog.timestamptz := pg_catalog.now();
begin
  if v_candidate_id is null then
    raise exception 'candidate_id is required';
  end if;

  if v_reviewed_by is null
     or pg_catalog.char_length(v_reviewed_by) > 128 then
    raise exception
      'reviewed_by must contain 1 to 128 non-whitespace characters';
  end if;

  if v_review_notes is null
     or pg_catalog.char_length(v_review_notes) > 4000 then
    raise exception
      'review_notes must contain 1 to 4000 non-whitespace characters';
  end if;

  select c.review_status
    into v_review_status
  from machimoa_review.curation_candidates as c
  where c.id = v_candidate_id
  for update;

  if not found then
    raise exception 'curation candidate % does not exist', v_candidate_id;
  end if;

  if v_review_status <> 'pending' then
    raise exception
      'curation candidate % is %, expected pending',
      v_candidate_id,
      v_review_status;
  end if;

  update machimoa_review.curation_candidates as c
  set
    review_status = 'rejected',
    review_notes = v_review_notes,
    reviewed_at = v_now,
    reviewed_by = v_reviewed_by
  where c.id = v_candidate_id;

  return v_candidate_id;
end
$function$;

alter function machimoa_review.reject_curation_candidate(
  pg_catalog.uuid,
  pg_catalog.text,
  pg_catalog.text
)
owner to postgres;

revoke all privileges
  on function machimoa_review.reject_curation_candidate(
    pg_catalog.uuid,
    pg_catalog.text,
    pg_catalog.text
  )
  from public, anon, authenticated, service_role;

do $post$
declare
  v_enqueue_count pg_catalog.int4;
  v_enqueue_identity pg_catalog.text;
  v_enqueue_owner pg_catalog.name;
  v_enqueue_oid pg_catalog.oid;
  v_publish_oid pg_catalog.oid;
  v_reject_oid pg_catalog.oid;
  v_old_enqueue pg_catalog.regprocedure;
begin
  select
    pg_catalog.count(*)::pg_catalog.int4,
    pg_catalog.string_agg(
      pg_catalog.pg_get_function_identity_arguments(p.oid),
      ' | '
      order by pg_catalog.pg_get_function_identity_arguments(p.oid)
    ),
    pg_catalog.min(pg_catalog.pg_get_userbyid(p.proowner)),
    pg_catalog.min(p.oid)
    into
      v_enqueue_count,
      v_enqueue_identity,
      v_enqueue_owner,
      v_enqueue_oid
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'enqueue_curation_candidate';

  if v_enqueue_count is distinct from 1 then
    raise exception
      'expected exactly one enqueue overload after P1, found % (%)',
      coalesce(v_enqueue_count, 0),
      coalesce(v_enqueue_identity, 'none');
  end if;

  if v_enqueue_identity is distinct from
       'text, text, text, text, text, text, jsonb, text, text, text, text, text, text, text, text, text'
  then
    raise exception
      'expected 16-argument enqueue_curation_candidate, found (%)',
      v_enqueue_identity;
  end if;

  if v_enqueue_owner <> 'postgres' then
    raise exception
      'new enqueue_curation_candidate must be owned by postgres, got %',
      v_enqueue_owner;
  end if;

  v_old_enqueue := pg_catalog.to_regprocedure(
    'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text)'
  );
  if v_old_enqueue is not null then
    raise exception
      'old 12-argument enqueue_curation_candidate still exists after P1';
  end if;

  v_publish_oid := pg_catalog.to_regprocedure(
    'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'
  );
  v_reject_oid := pg_catalog.to_regprocedure(
    'machimoa_review.reject_curation_candidate(uuid,text,text)'
  );

  if v_publish_oid is null or v_reject_oid is null then
    raise exception 'publish or reject function missing after P1 replace';
  end if;

  if pg_catalog.has_function_privilege(
       'anon', v_enqueue_oid, 'execute'
     )
     or pg_catalog.has_function_privilege(
       'authenticated', v_enqueue_oid, 'execute'
     )
     or pg_catalog.has_function_privilege(
       'public', v_enqueue_oid, 'execute'
     )
  then
    raise exception
      'enqueue EXECUTE remains granted to PUBLIC or an API role';
  end if;

  if not pg_catalog.has_function_privilege(
       'service_role', v_enqueue_oid, 'execute'
     )
  then
    raise exception 'service_role must have EXECUTE on the new enqueue';
  end if;

  if pg_catalog.has_function_privilege('anon', v_publish_oid, 'execute')
     or pg_catalog.has_function_privilege(
       'authenticated', v_publish_oid, 'execute'
     )
     or pg_catalog.has_function_privilege(
       'service_role', v_publish_oid, 'execute'
     )
     or pg_catalog.has_function_privilege('public', v_publish_oid, 'execute')
     or pg_catalog.has_function_privilege('anon', v_reject_oid, 'execute')
     or pg_catalog.has_function_privilege(
       'authenticated', v_reject_oid, 'execute'
     )
     or pg_catalog.has_function_privilege(
       'service_role', v_reject_oid, 'execute'
     )
     or pg_catalog.has_function_privilege('public', v_reject_oid, 'execute')
  then
    raise exception
      'publish or reject EXECUTE remains granted to PUBLIC, an API role, or service_role';
  end if;
end
$post$;

commit;
