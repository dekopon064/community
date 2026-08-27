-- NON-DESTRUCTIVE ROLLBACK.
-- Restore the P0 review-queue function contracts while keeping the new
-- language columns and their data. Japanese and split AI-status values are
-- not deleted.
--
-- Stop all workflow runs before use. Do not apply without explicit approval.
-- Do not run the matching cleanup unless a separate destructive approval
-- is given. Cleanup permanently drops Japanese and bilingual-status data.
--
-- Recovery after this script:
-- Do not re-run 20260827121818_p1_bilingual_curations.sql. That migration
-- adds columns and will fail if they already exist.
-- Restore a later forward function migration after the failure cause is
-- fixed. Keep collection workflows paused until that recovery is verified.

begin;

do $guard$
declare
  v_enqueue_count pg_catalog.int4;
  v_enqueue_identity pg_catalog.text;
  v_missing_columns pg_catalog.text;
begin
  -- Supabase CLI 2.116.0 linked db push: session_user=cli_login_postgres,
  -- current_user=postgres. DDL authorization still requires current_user=postgres.
  -- session_user is an exact allowlist: postgres or cli_login_postgres.
  if current_user <> 'postgres'
     or session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'P1 bilingual curations rollback must run as postgres (current_user=%, session_user=%)',
      current_user,
      session_user;
  end if;

  select
    pg_catalog.count(*)::pg_catalog.int4,
    pg_catalog.string_agg(
      pg_catalog.pg_get_function_identity_arguments(p.oid),
      ' | '
      order by pg_catalog.pg_get_function_identity_arguments(p.oid)
    )
    into v_enqueue_count, v_enqueue_identity
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'enqueue_curation_candidate';

  if v_enqueue_count is distinct from 1 then
    raise exception
      'expected exactly one enqueue overload before P1 down, found % (%)',
      coalesce(v_enqueue_count, 0),
      coalesce(v_enqueue_identity, 'none');
  end if;

  if v_enqueue_identity is distinct from
       'text, text, text, text, text, text, jsonb, text, text, text, text, text, text, text, text, text'
  then
    raise exception
      'expected 16-argument enqueue_curation_candidate before P1 down, found (%)',
      v_enqueue_identity;
  end if;

  if pg_catalog.to_regprocedure(
       'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'
     ) is null
     or pg_catalog.to_regprocedure(
       'machimoa_review.reject_curation_candidate(uuid,text,text)'
     ) is null
  then
    raise exception
      'publish or reject function is missing; inspect and resolve manually';
  end if;

  select pg_catalog.string_agg(expected.col, ', ' order by expected.col)
    into v_missing_columns
  from (
    values
      ('public.curations.title_ko'),
      ('public.curations.title_ja'),
      ('public.curations.summary_ko'),
      ('public.curations.summary_ja'),
      ('public.curations.content_ko'),
      ('public.curations.content_ja'),
      ('machimoa_review.curation_candidates.title_ko'),
      ('machimoa_review.curation_candidates.title_ja'),
      ('machimoa_review.curation_candidates.summary_ko'),
      ('machimoa_review.curation_candidates.summary_ja'),
      ('machimoa_review.curation_candidates.content_ko'),
      ('machimoa_review.curation_candidates.content_ja'),
      ('machimoa_review.curation_candidates.ai_status_ko'),
      ('machimoa_review.curation_candidates.ai_status_ja')
  ) as expected(col)
  left join pg_catalog.pg_attribute as a
    on a.attrelid = pg_catalog.to_regclass(pg_catalog.split_part(expected.col, '.', 1) || '.' || pg_catalog.split_part(expected.col, '.', 2))
   and a.attname = pg_catalog.split_part(expected.col, '.', 3)
   and a.attnum > 0
   and not a.attisdropped
  where a.attname is null;

  if v_missing_columns is not null then
    raise exception
      'P1 language columns missing before down (%); refusing to continue',
      v_missing_columns;
  end if;
end
$guard$;

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
  v_enqueue_oid pg_catalog.oid;
  v_publish_oid pg_catalog.oid;
  v_reject_oid pg_catalog.oid;
  v_remaining_columns pg_catalog.int4;
begin
  select
    pg_catalog.count(*)::pg_catalog.int4,
    pg_catalog.string_agg(
      pg_catalog.pg_get_function_identity_arguments(p.oid),
      ' | '
      order by pg_catalog.pg_get_function_identity_arguments(p.oid)
    ),
    pg_catalog.min(p.oid)
    into v_enqueue_count, v_enqueue_identity, v_enqueue_oid
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'public'
    and p.proname = 'enqueue_curation_candidate';

  if v_enqueue_count is distinct from 1
     or v_enqueue_identity is distinct from
       'text, text, text, text, text, text, jsonb, text, text, text, text, text'
  then
    raise exception
      'expected restored 12-argument enqueue, found % (%)',
      coalesce(v_enqueue_count, 0),
      coalesce(v_enqueue_identity, 'none');
  end if;

  if pg_catalog.to_regprocedure(
       'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)'
     ) is not null
  then
    raise exception '16-argument enqueue still exists after P1 down';
  end if;

  v_publish_oid := pg_catalog.to_regprocedure(
    'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'
  );
  v_reject_oid := pg_catalog.to_regprocedure(
    'machimoa_review.reject_curation_candidate(uuid,text,text)'
  );

  if not pg_catalog.has_function_privilege(
       'service_role', v_enqueue_oid, 'execute'
     )
     or pg_catalog.has_function_privilege('anon', v_enqueue_oid, 'execute')
     or pg_catalog.has_function_privilege(
       'authenticated', v_enqueue_oid, 'execute'
     )
     or pg_catalog.has_function_privilege('public', v_enqueue_oid, 'execute')
     or pg_catalog.has_function_privilege('anon', v_publish_oid, 'execute')
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
      'restored function privileges are not in the P0-safe state';
  end if;

  select pg_catalog.count(*)::pg_catalog.int4
    into v_remaining_columns
  from pg_catalog.pg_attribute as a
  join pg_catalog.pg_class as c
    on c.oid = a.attrelid
  join pg_catalog.pg_namespace as n
    on n.oid = c.relnamespace
  where a.attnum > 0
    and not a.attisdropped
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
    and (
      (n.nspname = 'public' and c.relname = 'curations')
      or (
        n.nspname = 'machimoa_review'
        and c.relname = 'curation_candidates'
      )
    );

  if v_remaining_columns is distinct from 14 then
    raise exception
      'P1 down must preserve 14 language/status columns, found %',
      v_remaining_columns;
  end if;
end
$post$;

commit;
