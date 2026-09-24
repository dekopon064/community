-- Hide unpublished curations from anon/authenticated reads and add
-- set_curation_published. Does not delete curations, candidates, source
-- items, AI jobs, or publication events.
-- Do not apply without a separate operating-database approval.
-- service_role keeps its existing bypass of RLS.
-- Non-destructive rollback:
--   supabase/rollback/20260927000000_curation_publish_visibility_down.sql
-- Fail closed: do not remove the is_published filter while any
-- public.curations.is_published = false row exists.

begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception
      'publish visibility migration must run as postgres (current_user=%)',
      current_user;
  end if;
  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'publish visibility migration session_user not allowed (%)',
      session_user;
  end if;
  if pg_catalog.to_regclass('public.curations') is null then
    raise exception 'public.curations must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.source_publications') is null then
    raise exception 'source_publications must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.source_publication_events') is null then
    raise exception 'source_publication_events must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.curation_candidates') is null then
    raise exception 'curation_candidates must exist';
  end if;
  if not exists (
    select 1
    from pg_catalog.pg_attribute as a
    where a.attrelid = 'public.curations'::pg_catalog.regclass
      and a.attname = 'is_published'
      and not a.attisdropped
  ) then
    raise exception 'public.curations.is_published must exist';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.assert_publish_allowed(pg_catalog.text)'
     ) is null then
    raise exception 'assert_publish_allowed signature is missing';
  end if;
  if not exists (
    select 1
    from pg_roles
    where rolname = 'service_role'
      and rolbypassrls
  ) then
    raise exception 'service_role must bypass RLS';
  end if;
end
$guard$;

drop policy if exists "curations_public_select" on public.curations;

create policy "curations_public_select"
  on public.curations
  for select
  to anon, authenticated
  using (is_published = true);

create function machimoa_review.set_curation_published(
  p_public_curation_id pg_catalog.uuid,
  p_published pg_catalog.bool,
  p_actor pg_catalog.text,
  p_reason pg_catalog.text
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_actor, '')), '');
  v_reason pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_reason, '')), '');
  v_curation public.curations%rowtype;
  v_pub machimoa_review.source_publications%rowtype;
  v_legacy_candidate machimoa_review.curation_candidates%rowtype;
  v_legacy_source pg_catalog.text;
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_event_kind pg_catalog.text;
begin
  if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then
    raise exception 'publish visibility requires read committed isolation';
  end if;
  -- Serialize with rollback. A call waiting behind rollback must not
  -- resume and hide a row after the public policy has been restored.
  perform pg_catalog.pg_advisory_xact_lock(20260927, 1);
  if pg_catalog.to_regprocedure(
       'machimoa_review.set_curation_published(pg_catalog.uuid,pg_catalog.bool,pg_catalog.text,pg_catalog.text)'
     ) is null then
    raise exception 'publish visibility function is no longer installed';
  end if;

  if p_public_curation_id is null then
    raise exception 'public_curation_id is required';
  end if;
  if p_published is null then
    raise exception 'published is required';
  end if;
  if v_actor is null or pg_catalog.char_length(v_actor) > 128 then
    raise exception 'actor must contain 1 to 128 non-whitespace characters';
  end if;
  if v_reason is null or pg_catalog.char_length(v_reason) > 4000 then
    raise exception 'reason must contain 1 to 4000 non-whitespace characters';
  end if;

  select * into v_curation
  from public.curations as c
  where c.id = p_public_curation_id
  for update;
  if not found then
    raise exception 'curation % does not exist', p_public_curation_id;
  end if;

  select * into v_pub
  from machimoa_review.source_publications as p
  where p.public_curation_id = p_public_curation_id
  for update;
  if not found then
    -- Publications created before lineage tracking have a published
    -- candidate but no source_publications row. Reconstruct only that
    -- verifiable snapshot when taking the curation offline.
    if p_published or not v_curation.is_published then
      raise exception 'publication lineage not found';
    end if;

    -- The old publisher retained earlier published candidates when a
    -- newer revision overwrote the same public curation. Select only the
    -- unique candidate that matches the public row's last publish time
    -- and every field copied by that publisher. Missing or ambiguous
    -- lineage must be repaired explicitly, never guessed by sort order.
    select c.* into strict v_legacy_candidate
    from machimoa_review.curation_candidates as c
    where c.published_curation_id = p_public_curation_id
      and c.review_status = 'published'
      and c.published_at = v_curation.updated_at
      and pg_catalog.lower(pg_catalog.btrim(c.source)) is not distinct from v_curation.source
      and pg_catalog.btrim(c.source_item_id) is not distinct from v_curation.source_item_id
      and pg_catalog.btrim(c.slug) is not distinct from v_curation.slug
      and nullif(pg_catalog.btrim(coalesce(c.category, '')), '') is not distinct from v_curation.category
      and nullif(pg_catalog.btrim(coalesce(c.title_ko, '')), '') is not distinct from v_curation.title_ko
      and nullif(pg_catalog.btrim(coalesce(c.title_ja, '')), '') is not distinct from v_curation.title_ja
      and nullif(pg_catalog.btrim(coalesce(c.summary_ko, '')), '') is not distinct from v_curation.summary_ko
      and nullif(pg_catalog.btrim(coalesce(c.summary_ja, '')), '') is not distinct from v_curation.summary_ja
      and nullif(pg_catalog.btrim(coalesce(c.content_ko, '')), '') is not distinct from v_curation.content_ko
      and nullif(pg_catalog.btrim(coalesce(c.content_ja, '')), '') is not distinct from v_curation.content_ja
      and nullif(pg_catalog.btrim(coalesce(c.source_url, '')), '') is not distinct from v_curation.source_url
      and c.application_deadline_kind is not distinct from v_curation.application_deadline_kind
      and c.application_deadline_on is not distinct from v_curation.application_deadline_on
      and v_curation.title is not distinct from v_curation.title_ko
      and v_curation.summary is not distinct from v_curation.summary_ko
      and v_curation.content is not distinct from v_curation.content_ko
    for update;

    v_legacy_source := machimoa_review.canonical_source_id(
      v_legacy_candidate.source
    );
    if v_legacy_source is null
       or v_legacy_candidate.source is distinct from v_curation.source
       or v_legacy_candidate.source_item_id is distinct from v_curation.source_item_id
       or v_legacy_candidate.slug is distinct from v_curation.slug
       or v_legacy_candidate.title_ko is distinct from v_curation.title_ko
       or v_legacy_candidate.title_ja is distinct from v_curation.title_ja
       or v_legacy_candidate.summary_ko is distinct from v_curation.summary_ko
       or v_legacy_candidate.summary_ja is distinct from v_curation.summary_ja
       or v_legacy_candidate.content_ko is distinct from v_curation.content_ko
       or v_legacy_candidate.content_ja is distinct from v_curation.content_ja then
      raise exception 'legacy publication candidate does not match curation';
    end if;

    insert into machimoa_review.source_publications (
      source_id, external_key, revision_hash, candidate_id,
      public_curation_id, publication_status, published_at,
      unpublished_at, takedown_status
    ) values (
      v_legacy_source,
      v_legacy_candidate.source_item_id,
      v_legacy_candidate.source_revision_hash,
      v_legacy_candidate.id,
      v_curation.id,
      'published',
      v_legacy_candidate.published_at,
      null,
      'none'
    ) returning * into v_pub;
  end if;

  if v_pub.source_id is distinct from machimoa_review.canonical_source_id(v_curation.source)
     or v_pub.external_key is distinct from v_curation.source_item_id
     or v_pub.public_curation_id is distinct from v_curation.id then
    raise exception 'publication lineage does not match curation';
  end if;

  if p_published then
    if v_curation.is_published
       or v_pub.publication_status is distinct from 'unpublished'
       or v_pub.takedown_status is distinct from 'unpublished' then
      raise exception 'curation % is not unpublished', p_public_curation_id;
    end if;
    perform machimoa_review.assert_publish_allowed(v_pub.source_id);
    v_event_kind := 'published';
    update public.curations as c
    set is_published = true
    where c.id = v_curation.id;
    update machimoa_review.source_publications as p
    set
      publication_status = 'published',
      takedown_status = 'none',
      unpublished_at = null
    where p.id = v_pub.id;
  else
    if not v_curation.is_published
       or v_pub.publication_status is distinct from 'published'
       or v_pub.takedown_status is distinct from 'none' then
      raise exception 'curation % is not published', p_public_curation_id;
    end if;
    v_event_kind := 'unpublished';
    update public.curations as c
    set is_published = false
    where c.id = v_curation.id;
    update machimoa_review.source_publications as p
    set
      publication_status = 'unpublished',
      takedown_status = 'unpublished',
      unpublished_at = v_now
    where p.id = v_pub.id;
  end if;

  insert into machimoa_review.source_publication_events (
    event_kind,
    source_id,
    external_key,
    revision_hash,
    candidate_id,
    public_curation_id,
    slug,
    occurred_at,
    actor,
    reason
  )
  values (
    v_event_kind,
    v_pub.source_id,
    v_pub.external_key,
    v_pub.revision_hash,
    v_pub.candidate_id,
    v_pub.public_curation_id,
    v_curation.slug,
    v_now,
    v_actor,
    v_reason
  );
end
$function$;

alter function machimoa_review.set_curation_published(
  pg_catalog.uuid, pg_catalog.bool, pg_catalog.text, pg_catalog.text
) owner to postgres;

revoke all privileges on function machimoa_review.set_curation_published(
  pg_catalog.uuid, pg_catalog.bool, pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;

commit;
