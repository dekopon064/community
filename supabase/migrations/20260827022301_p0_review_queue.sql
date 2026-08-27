-- P0 review queue: automatic collection may enqueue candidates, but only a
-- human operating as postgres may publish or reject them.
-- Pre-change evidence:
--   supabase/audit/2026-08-27_pre_p0_review_queue_state.md
-- Lossless rollback:
--   supabase/rollback/20260827022301_p0_review_queue_down.sql
-- Destructive cleanup:
--   supabase/rollback/20260827022301_p0_review_queue_cleanup.sql

begin;

do $guard$
declare
  v_curations_owner pg_catalog.name;
  v_column_acls pg_catalog.text;
  v_existing_enqueue pg_catalog.text;
begin
  if current_user <> 'postgres' or session_user <> 'postgres' then
    raise exception
      'P0 review queue migration must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  if pg_catalog.to_regnamespace('machimoa_review') is not null then
    raise exception
      'schema machimoa_review already exists; inspect and resolve it manually';
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

  select pg_catalog.string_agg(a.attname, ', ' order by a.attname)
    into v_column_acls
  from pg_catalog.pg_attribute as a
  where a.attrelid = 'public.curations'::pg_catalog.regclass
    and a.attnum > 0
    and not a.attisdropped
    and a.attacl is not null;

  if v_column_acls is not null then
    raise exception
      'public.curations has column-level grants on (%); table-level revoke cannot clear them; inspect and resolve them manually',
      v_column_acls;
  end if;

  select pg_catalog.string_agg(
           'public.enqueue_curation_candidate('
             || pg_catalog.pg_get_function_identity_arguments(p.oid)
             || ')',
           ', '
           order by pg_catalog.pg_get_function_identity_arguments(p.oid)
         )
    into v_existing_enqueue
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'enqueue_curation_candidate';

  if v_existing_enqueue is not null then
    raise exception
      'function public.enqueue_curation_candidate already exists (%); inspect and resolve it manually',
      v_existing_enqueue;
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
end
$guard$;

create schema machimoa_review authorization postgres;

revoke all privileges on schema machimoa_review
  from public, anon, authenticated, service_role;

alter table public.curations
  add column source pg_catalog.text,
  add column source_item_id pg_catalog.text,
  add column source_url pg_catalog.text,
  add column updated_at pg_catalog.timestamptz
    not null
    default pg_catalog.now();

-- Preserve the historical update time of pre-existing rows.
update public.curations
set updated_at = created_at;

alter table public.curations
  add constraint curations_source_pair_ck
  check ((source is null) = (source_item_id is null));

create unique index curations_source_item_uk
  on public.curations (source, source_item_id)
  where source is not null
    and source_item_id is not null;

-- Establish the target state without relying on the preceding P0 migration.
revoke all privileges on table public.curations
  from public, anon, authenticated, service_role;

grant select on table public.curations
  to anon, authenticated, service_role;

create table machimoa_review.curation_candidates (
  id pg_catalog.uuid
    primary key
    default pg_catalog.gen_random_uuid(),
  revision_seq pg_catalog.int8
    generated always as identity,
  source pg_catalog.text not null,
  source_item_id pg_catalog.text not null,
  source_revision_hash pg_catalog.text not null,
  slug pg_catalog.text not null,
  category pg_catalog.text,
  title pg_catalog.text not null,
  summary pg_catalog.text,
  content pg_catalog.text not null,
  source_url pg_catalog.text,
  raw_payload pg_catalog.jsonb not null,
  ai_status pg_catalog.text not null,
  ai_model pg_catalog.text,
  review_status pg_catalog.text not null default 'pending',
  review_notes pg_catalog.text,
  reviewed_at pg_catalog.timestamptz,
  reviewed_by pg_catalog.text,
  published_at pg_catalog.timestamptz,
  published_curation_id pg_catalog.uuid,
  superseded_at pg_catalog.timestamptz,
  superseded_by_candidate_id pg_catalog.uuid,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  updated_at pg_catalog.timestamptz not null default pg_catalog.now(),

  constraint curation_candidates_published_curation_fk
    foreign key (published_curation_id)
    references public.curations (id)
    on delete set null,
  constraint curation_candidates_superseded_by_fk
    foreign key (superseded_by_candidate_id)
    references machimoa_review.curation_candidates (id)
    on delete set null
    deferrable initially deferred,

  constraint curation_candidates_review_status_ck
    check (
      review_status in ('pending', 'published', 'rejected', 'superseded')
    ),
  constraint curation_candidates_ai_status_ck
    check (
      ai_status in (
        'success',
        'fallback_raw',
        'empty_response',
        'skipped_no_key',
        'error'
      )
    ),
  constraint curation_candidates_superseded_at_ck
    check (
      (review_status = 'superseded') = (superseded_at is not null)
    ),
  constraint curation_candidates_superseded_by_ck
    check (
      superseded_by_candidate_id is null
      or review_status = 'superseded'
    ),
  constraint curation_candidates_not_self_superseded_ck
    check (
      superseded_by_candidate_id is null
      or superseded_by_candidate_id <> id
    ),
  constraint curation_candidates_published_at_ck
    check (
      (review_status = 'published') = (published_at is not null)
    ),
  constraint curation_candidates_reviewed_at_ck
    check (
      (review_status in ('published', 'rejected'))
        = (reviewed_at is not null)
    ),
  constraint curation_candidates_reviewed_by_ck
    check (
      (review_status in ('published', 'rejected'))
        = (reviewed_by is not null)
    ),
  constraint curation_candidates_source_format_ck
    check (source ~ '^[a-z][a-z0-9_]{1,31}$'),
  constraint curation_candidates_revision_hash_format_ck
    check (source_revision_hash ~ '^[0-9a-f]{64}$'),
  constraint curation_candidates_source_item_length_ck
    check (
      pg_catalog.char_length(source_item_id) between 1 and 128
      and source_item_id = pg_catalog.btrim(source_item_id)
    ),
  constraint curation_candidates_slug_length_ck
    check (
      pg_catalog.char_length(slug) between 1 and 128
      and slug = pg_catalog.btrim(slug)
    ),
  constraint curation_candidates_title_length_ck
    check (
      pg_catalog.char_length(title) between 1 and 300
      and title = pg_catalog.btrim(title)
    ),
  constraint curation_candidates_content_length_ck
    check (
      pg_catalog.char_length(content) between 1 and 200000
      and content = pg_catalog.btrim(content)
    ),
  constraint curation_candidates_category_length_ck
    check (
      category is null
      or (
        pg_catalog.char_length(category) between 1 and 100
        and category = pg_catalog.btrim(category)
      )
    ),
  constraint curation_candidates_summary_length_ck
    check (
      summary is null
      or (
        pg_catalog.char_length(summary) between 1 and 1000
        and summary = pg_catalog.btrim(summary)
      )
    ),
  constraint curation_candidates_ai_model_length_ck
    check (
      ai_model is null
      or (
        pg_catalog.char_length(ai_model) between 1 and 100
        and ai_model = pg_catalog.btrim(ai_model)
      )
    ),
  constraint curation_candidates_review_notes_length_ck
    check (
      review_notes is null
      or (
        pg_catalog.char_length(review_notes) between 1 and 4000
        and pg_catalog.btrim(review_notes) <> ''
      )
    ),
  constraint curation_candidates_reviewed_by_length_ck
    check (
      reviewed_by is null
      or (
        pg_catalog.char_length(reviewed_by) between 1 and 128
        and reviewed_by = pg_catalog.btrim(reviewed_by)
      )
    ),
  constraint curation_candidates_source_url_format_ck
    check (
      source_url is null
      or (
        source_url ~ '^https?://'
        and pg_catalog.char_length(source_url) <= 2048
        and source_url = pg_catalog.btrim(source_url)
      )
    ),
  constraint curation_candidates_raw_payload_object_ck
    check (pg_catalog.jsonb_typeof(raw_payload) = 'object')
);

alter table machimoa_review.curation_candidates owner to postgres;
alter sequence machimoa_review.curation_candidates_revision_seq_seq
  owner to postgres;

alter table machimoa_review.curation_candidates
  enable row level security;

revoke all privileges on table machimoa_review.curation_candidates
  from public, anon, authenticated, service_role;

revoke all privileges
  on sequence machimoa_review.curation_candidates_revision_seq_seq
  from public, anon, authenticated, service_role;

create unique index curation_candidates_pending_source_item_uk
  on machimoa_review.curation_candidates (source, source_item_id)
  where review_status = 'pending';

create index curation_candidates_source_revision_idx
  on machimoa_review.curation_candidates (
    source,
    source_item_id,
    revision_seq desc
  );

create index curation_candidates_review_queue_idx
  on machimoa_review.curation_candidates (review_status, created_at desc);

create index curation_candidates_slug_idx
  on machimoa_review.curation_candidates (slug);

create index curation_candidates_superseded_by_idx
  on machimoa_review.curation_candidates (superseded_by_candidate_id);

create function machimoa_review.set_candidate_updated_at()
returns pg_catalog.trigger
language plpgsql
security invoker
set search_path = ''
as $function$
begin
  new.updated_at := pg_catalog.now();
  return new;
end
$function$;

alter function machimoa_review.set_candidate_updated_at()
  owner to postgres;

revoke all privileges
  on function machimoa_review.set_candidate_updated_at()
  from public, anon, authenticated, service_role;

create trigger curation_candidates_set_updated_at
  before update on machimoa_review.curation_candidates
  for each row
  execute function machimoa_review.set_candidate_updated_at();

create function public.enqueue_curation_candidate(
  p_source pg_catalog.text,
  p_source_item_id pg_catalog.text,
  p_source_revision_hash pg_catalog.text,
  p_slug pg_catalog.text,
  p_title pg_catalog.text,
  p_content pg_catalog.text,
  p_raw_payload pg_catalog.jsonb,
  p_ai_status pg_catalog.text,
  p_category pg_catalog.text default null,
  p_summary pg_catalog.text default null,
  p_source_url pg_catalog.text default null,
  p_ai_model pg_catalog.text default null
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
  v_title pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_title, ''));
  v_content pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_content, ''));
  v_raw_payload pg_catalog.jsonb := p_raw_payload;
  v_ai_status pg_catalog.text :=
    pg_catalog.lower(pg_catalog.btrim(coalesce(p_ai_status, '')));
  v_category pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_category, '')), '');
  v_summary pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_summary, '')), '');
  v_source_url pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_source_url, '')), '');
  v_ai_model pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_ai_model, '')), '');
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

  if pg_catalog.char_length(v_title) not between 1 and 300 then
    raise exception 'title length must be between 1 and 300';
  end if;

  if pg_catalog.char_length(v_content) not between 1 and 200000 then
    raise exception 'content length must be between 1 and 200000';
  end if;

  if v_category is not null
     and pg_catalog.char_length(v_category) > 100 then
    raise exception 'category length must not exceed 100';
  end if;

  if v_summary is not null
     and pg_catalog.char_length(v_summary) > 1000 then
    raise exception 'summary length must not exceed 1000';
  end if;

  if v_ai_model is not null
     and pg_catalog.char_length(v_ai_model) > 100 then
    raise exception 'ai_model length must not exceed 100';
  end if;

  if v_ai_status not in (
    'success',
    'fallback_raw',
    'empty_response',
    'skipped_no_key',
    'error'
  ) then
    raise exception 'invalid ai_status: %', v_ai_status;
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
    ai_model
  )
  values (
    v_new_id,
    v_source,
    v_source_item_id,
    v_source_revision_hash,
    v_slug,
    v_category,
    v_title,
    v_summary,
    v_content,
    v_source_url,
    v_raw_payload,
    v_ai_status,
    v_ai_model
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
    pg_catalog.text
  )
  to service_role;

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
  v_title pg_catalog.text;
  v_summary pg_catalog.text;
  v_content pg_catalog.text;
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
    pg_catalog.btrim(c.title),
    nullif(pg_catalog.btrim(coalesce(c.summary, '')), ''),
    pg_catalog.btrim(c.content),
    nullif(pg_catalog.btrim(coalesce(c.source_url, '')), '')
  into
    v_review_status,
    v_source,
    v_source_item_id,
    v_slug,
    v_category,
    v_title,
    v_summary,
    v_content,
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

  if pg_catalog.char_length(v_title) not between 1 and 300 then
    raise exception 'candidate title is empty or too long';
  end if;

  if v_summary is null
     or pg_catalog.char_length(v_summary) > 1000 then
    raise exception 'candidate summary is required and must not exceed 1000';
  end if;

  if pg_catalog.char_length(v_content) not between 1 and 200000 then
    raise exception 'candidate content is empty or too long';
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
      source,
      source_item_id,
      source_url,
      updated_at
    )
    values (
      v_slug,
      v_category,
      v_title,
      v_summary,
      v_content,
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
      title = v_title,
      summary = v_summary,
      content = v_content,
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
      title = v_title,
      summary = v_summary,
      content = v_content,
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

commit;
