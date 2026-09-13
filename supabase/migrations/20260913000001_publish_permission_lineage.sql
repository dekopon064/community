-- Publish permission gate, is_published schema, and source publication lineage.
-- Do not apply without a separate operating-database approval.
-- Soft-unpublish RPC and hard-delete RPC are created as contracts only and
-- are not granted to service_role. Next.js is not changed in this migration.
-- Non-destructive rollback:
--   supabase/rollback/20260913000001_publish_permission_lineage_down.sql

begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception
      'publish lineage migration must run as postgres (current_user=%)',
      current_user;
  end if;
  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'publish lineage migration session_user not allowed (%)',
      session_user;
  end if;
  if pg_catalog.to_regclass('machimoa_review.source_publications') is null then
    raise exception 'source_publications must exist before publish lineage';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'
     ) is null then
    raise exception 'publish_curation_candidate signature is missing';
  end if;
end
$guard$;

alter table public.curations
  add column if not exists is_published pg_catalog.bool not null default true;

create function machimoa_review.assert_publish_allowed(
  p_candidate_source pg_catalog.text
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_canonical pg_catalog.text;
  v_enabled pg_catalog.bool;
  v_permission pg_catalog.text;
begin
  v_canonical := machimoa_review.canonical_source_id(p_candidate_source);
  if v_canonical is null then
    raise exception 'unknown candidate source';
  end if;
  select s.enabled, s.permission_status
    into v_enabled, v_permission
  from machimoa_review.ingest_sources as s
  where s.source_id = v_canonical;
  if not found or not v_enabled then
    raise exception 'source is disabled';
  end if;
  if v_permission in ('testing_only', 'commercial_review_required')
     or v_permission is distinct from 'approved_noncommercial'
        and v_permission is distinct from 'approved_commercial' then
    raise exception 'publish_not_permitted';
  end if;
end
$function$;

create function machimoa_review.write_publication_lineage(
  p_candidate_source pg_catalog.text,
  p_external_key pg_catalog.text,
  p_revision_hash pg_catalog.text,
  p_candidate_id pg_catalog.uuid,
  p_public_curation_id pg_catalog.uuid,
  p_slug pg_catalog.text,
  p_actor pg_catalog.text
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_canonical pg_catalog.text := machimoa_review.canonical_source_id(p_candidate_source);
  v_now pg_catalog.timestamptz := pg_catalog.now();
begin
  insert into machimoa_review.source_publication_events (
    event_kind,
    source_id,
    external_key,
    revision_hash,
    candidate_id,
    public_curation_id,
    slug,
    occurred_at,
    actor
  )
  values (
    'published',
    v_canonical,
    p_external_key,
    p_revision_hash,
    p_candidate_id,
    p_public_curation_id,
    p_slug,
    v_now,
    p_actor
  );

  insert into machimoa_review.source_publications (
    source_id,
    external_key,
    revision_hash,
    candidate_id,
    public_curation_id,
    publication_status,
    published_at,
    unpublished_at,
    takedown_status
  )
  values (
    v_canonical,
    p_external_key,
    p_revision_hash,
    p_candidate_id,
    p_public_curation_id,
    'published',
    v_now,
    null,
    'none'
  )
  on conflict on constraint source_publications_source_item_uk
  do update set
    revision_hash = excluded.revision_hash,
    candidate_id = excluded.candidate_id,
    public_curation_id = excluded.public_curation_id,
    publication_status = 'published',
    published_at = excluded.published_at,
    unpublished_at = null,
    takedown_status = 'none';
end
$function$;

-- Contract only. Not granted to service_role. Event must be written first.
create function machimoa_review.hard_delete_published_curation_contract(
  p_public_curation_id pg_catalog.uuid,
  p_actor pg_catalog.text,
  p_reason pg_catalog.text
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_pub machimoa_review.source_publications%rowtype;
  v_now pg_catalog.timestamptz := pg_catalog.now();
begin
  -- 1. append-only hard_deleted event
  select * into v_pub
  from machimoa_review.source_publications as p
  where p.public_curation_id = p_public_curation_id
  for update;
  if not found then
    raise exception 'publication lineage not found';
  end if;

  insert into machimoa_review.source_publication_events (
    event_kind,
    source_id,
    external_key,
    revision_hash,
    candidate_id,
    public_curation_id,
    occurred_at,
    actor,
    reason
  )
  values (
    'hard_deleted',
    v_pub.source_id,
    v_pub.external_key,
    v_pub.revision_hash,
    v_pub.candidate_id,
    p_public_curation_id,
    v_now,
    p_actor,
    p_reason
  );

  -- 2. safely unlink lineage FK
  update machimoa_review.source_publications
  set
    public_curation_id = null,
    takedown_status = 'hard_deleted',
    publication_status = 'unpublished',
    unpublished_at = v_now
  where id = v_pub.id;

  -- 3. delete public curation
  delete from public.curations
  where id = p_public_curation_id;
end
$function$;

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
  v_source_revision_hash pg_catalog.text;
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
    pg_catalog.btrim(c.source_revision_hash),
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
    v_source_revision_hash,
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

  perform machimoa_review.assert_publish_allowed(v_source);

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
      updated_at,
      is_published
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
      v_now,
      true
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
      updated_at = v_now,
      is_published = true
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
      updated_at = v_now,
      is_published = true
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

  perform machimoa_review.write_publication_lineage(
    v_source,
    v_source_item_id,
    v_source_revision_hash,
    v_candidate_id,
    v_curation_id,
    v_slug,
    v_reviewed_by
  );

  return v_curation_id;
end
$function$;

alter function machimoa_review.assert_publish_allowed(pg_catalog.text)
  owner to postgres;
alter function machimoa_review.write_publication_lineage(
  pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.uuid,
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.hard_delete_published_curation_contract(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.publish_curation_candidate(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.bool
) owner to postgres;

revoke all privileges on function machimoa_review.assert_publish_allowed(
  pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.write_publication_lineage(
  pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.uuid,
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.hard_delete_published_curation_contract(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.publish_curation_candidate(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.bool
) from public, anon, authenticated, service_role;

-- publish remains postgres-callable via owner rights; not granted to service_role.
-- hard_delete contract is intentionally unggranted.

commit;
