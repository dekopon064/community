-- Rollback publish lineage helpers and restore the previous publish function.
-- Apply this file before 20260913000000_ingest_observation_queue_down.sql.
-- Safe order: restore previous publish_curation_candidate, then drop helpers
-- that the replaced function depended on, then drop is_published.
-- Does not delete curation_candidates or public.curations rows.
-- This file is not auto-applied.

begin;

-- Same signature as the P1 bilingual definition. CREATE OR REPLACE is required
-- because 000001 already replaced the function in place.
create or replace function machimoa_review.publish_curation_candidate(
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

drop function if exists machimoa_review.hard_delete_published_curation_contract(
  uuid, text, text
);
drop function if exists machimoa_review.write_publication_lineage(
  text, text, text, uuid, uuid, text, text
);
drop function if exists machimoa_review.assert_publish_allowed(text);

alter table public.curations
  drop column if exists is_published;

commit;
