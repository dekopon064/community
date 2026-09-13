-- Ingest observation, lease, processing jobs, and lineage tables.
-- Do not apply this file without a separate operating-database approval.
-- Non-destructive rollback:
--   supabase/rollback/20260913000000_ingest_observation_queue_down.sql
-- This migration must not rename existing curation_candidates.source
-- values and must not backfill or delete public.curations rows.
--
-- Supabase CLI linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.

begin;

do $guard$
declare
  v_schema_owner pg_catalog.name;
begin
  if current_user <> 'postgres' then
    raise exception
      'ingest observation migration must run as postgres (current_user=%)',
      current_user;
  end if;

  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'ingest observation migration session_user not allowed (% )',
      session_user;
  end if;

  if pg_catalog.to_regnamespace('machimoa_review') is null then
    raise exception 'schema machimoa_review does not exist';
  end if;

  select pg_catalog.pg_get_userbyid(n.nspowner)
    into v_schema_owner
  from pg_catalog.pg_namespace as n
  where n.nspname = 'machimoa_review';

  if v_schema_owner <> 'postgres' then
    raise exception 'machimoa_review must be owned by postgres';
  end if;

  if pg_catalog.to_regclass('machimoa_review.ingest_sources') is not null then
    raise exception
      'table machimoa_review.ingest_sources already exists; inspect manually';
  end if;
end
$guard$;

create table machimoa_review.ingest_sources (
  source_id pg_catalog.text primary key,
  provider pg_catalog.text not null,
  source_kind pg_catalog.text not null,
  connector_type pg_catalog.text not null,
  enabled pg_catalog.bool not null default true,
  permission_status pg_catalog.text not null default 'testing_only',
  legacy_curation_source pg_catalog.text not null,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  updated_at pg_catalog.timestamptz not null default pg_catalog.now(),
  constraint ingest_sources_id_ck
    check (source_id ~ '^[a-z][a-z0-9_]{1,31}$'),
  constraint ingest_sources_kind_ck
    check (source_kind in ('policy', 'content')),
  constraint ingest_sources_connector_ck
    check (connector_type in ('rest', 'rss', 'cursor')),
  constraint ingest_sources_permission_ck
    check (
      permission_status in (
        'testing_only',
        'approved_noncommercial',
        'commercial_review_required',
        'approved_commercial'
      )
    ),
  constraint ingest_sources_legacy_ck
    check (legacy_curation_source ~ '^[a-z][a-z0-9_]{1,31}$')
);

create table machimoa_review.source_sync_state (
  source_id pg_catalog.text primary key
    references machimoa_review.ingest_sources (source_id)
    on delete restrict,
  bootstrap_complete pg_catalog.bool not null default false,
  committed_checkpoint pg_catalog.jsonb,
  last_success_at pg_catalog.timestamptz,
  last_stop_reason pg_catalog.text,
  lease_owner pg_catalog.uuid,
  lease_expires_at pg_catalog.timestamptz,
  lease_seconds pg_catalog.int4,
  active_run_id pg_catalog.uuid,
  updated_at pg_catalog.timestamptz not null default pg_catalog.now(),
  constraint source_sync_state_lease_ck
    check (
      lease_seconds is null
      or lease_seconds between 30 and 3600
    )
);

create table machimoa_review.ingest_runs (
  id pg_catalog.uuid primary key default pg_catalog.gen_random_uuid(),
  source_id pg_catalog.text not null
    references machimoa_review.ingest_sources (source_id)
    on delete restrict,
  status pg_catalog.text not null default 'running',
  stop_reason pg_catalog.text,
  batches_ok pg_catalog.int4 not null default 0,
  http_request_count pg_catalog.int4 not null default 0,
  http_last_status pg_catalog.int4,
  started_at pg_catalog.timestamptz not null default pg_catalog.now(),
  finished_at pg_catalog.timestamptz,
  lease_seconds pg_catalog.int4 not null default 120,
  constraint ingest_runs_status_ck
    check (status in ('running', 'complete', 'incomplete', 'failed')),
  constraint ingest_runs_lease_ck
    check (lease_seconds between 30 and 3600)
);

create table machimoa_review.source_items (
  id pg_catalog.uuid primary key default pg_catalog.gen_random_uuid(),
  source_id pg_catalog.text not null
    references machimoa_review.ingest_sources (source_id)
    on delete restrict,
  external_key pg_catalog.text not null,
  revision_hash pg_catalog.text not null,
  first_seen_at pg_catalog.timestamptz not null,
  last_seen_at pg_catalog.timestamptz not null,
  source_created_at pg_catalog.timestamptz,
  source_created_raw pg_catalog.text,
  source_created_parse_status pg_catalog.text not null,
  source_updated_at pg_catalog.timestamptz,
  source_updated_raw pg_catalog.text,
  source_updated_parse_status pg_catalog.text not null,
  disposition pg_catalog.text not null,
  min_fields pg_catalog.jsonb not null default '{}'::pg_catalog.jsonb,
  normalized_payload pg_catalog.jsonb,
  has_source_url pg_catalog.bool not null default false,
  body_usable pg_catalog.bool not null default false,
  attachment_present pg_catalog.bool not null default false,
  attachment_length pg_catalog.int4 not null default 0,
  is_data_url pg_catalog.bool not null default false,
  last_run_id pg_catalog.uuid,
  constraint source_items_unique unique (source_id, external_key),
  constraint source_items_parse_created_ck
    check (source_created_parse_status in ('ok', 'missing', 'unparsed')),
  constraint source_items_parse_updated_ck
    check (source_updated_parse_status in ('ok', 'missing', 'unparsed')),
  constraint source_items_disposition_ck
    check (
      disposition in (
        'target',
        'non_target',
        'region_review_required',
        'observe_only',
        'attachment_dependent'
      )
    ),
  constraint source_items_hash_ck
    check (revision_hash ~ '^[0-9a-f]{64}$'),
  constraint source_items_key_len_ck
    check (pg_catalog.char_length(external_key) between 1 and 128),
  constraint source_items_raw_len_ck
    check (
      source_created_raw is null
      or pg_catalog.char_length(source_created_raw) <= 64
    ),
  constraint source_items_raw_updated_len_ck
    check (
      source_updated_raw is null
      or pg_catalog.char_length(source_updated_raw) <= 64
    )
);

create table machimoa_review.processing_jobs (
  id pg_catalog.uuid primary key default pg_catalog.gen_random_uuid(),
  source_item_id pg_catalog.uuid not null
    references machimoa_review.source_items (id)
    on delete restrict,
  revision_hash pg_catalog.text not null,
  processing_stage pg_catalog.text not null,
  status pg_catalog.text not null,
  queued_at pg_catalog.timestamptz not null,
  available_at pg_catalog.timestamptz not null,
  claimed_at pg_catalog.timestamptz,
  completed_at pg_catalog.timestamptz,
  claim_lease_until pg_catalog.timestamptz,
  claimed_by pg_catalog.text,
  retry_count pg_catalog.int4 not null default 0,
  next_retry_at pg_catalog.timestamptz,
  error_code pg_catalog.text,
  reason_codes pg_catalog.text[] not null default '{}'::pg_catalog.text[],
  constraint processing_jobs_unique
    unique (source_item_id, revision_hash, processing_stage),
  constraint processing_jobs_stage_ck
    check (
      processing_stage in (
        'region_review',
        'content_review',
        'relationship_review',
        'ai_enrichment'
      )
    ),
  constraint processing_jobs_status_ck
    check (
      status in ('queued', 'claimed', 'completed', 'failed', 'cancelled')
    ),
  constraint processing_jobs_error_ck
    check (
      error_code is null or pg_catalog.char_length(error_code) <= 64
    )
);

create index processing_jobs_ai_claim_idx
  on machimoa_review.processing_jobs (
    queued_at,
    id
  )
  where processing_stage = 'ai_enrichment'
    and status in ('queued', 'claimed');

create table machimoa_review.source_relationships (
  id pg_catalog.uuid primary key default pg_catalog.gen_random_uuid(),
  from_source_id pg_catalog.text not null,
  from_external_key pg_catalog.text not null,
  to_source_id pg_catalog.text not null,
  to_external_key pg_catalog.text not null,
  relation_kind pg_catalog.text not null,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  constraint source_relationships_kind_ck
    check (relation_kind in ('candidate', 'explicit')),
  constraint source_relationships_unique
    unique (
      from_source_id,
      from_external_key,
      to_source_id,
      to_external_key,
      relation_kind
    )
);

create table machimoa_review.source_publications (
  id pg_catalog.uuid primary key default pg_catalog.gen_random_uuid(),
  source_id pg_catalog.text not null,
  external_key pg_catalog.text not null,
  revision_hash pg_catalog.text not null,
  candidate_id pg_catalog.uuid
    references machimoa_review.curation_candidates (id)
    on delete set null,
  public_curation_id pg_catalog.uuid
    references public.curations (id)
    on delete set null,
  publication_status pg_catalog.text not null,
  published_at pg_catalog.timestamptz not null,
  unpublished_at pg_catalog.timestamptz,
  takedown_status pg_catalog.text not null default 'none',
  constraint source_publications_status_ck
    check (publication_status in ('published', 'unpublished')),
  constraint source_publications_takedown_ck
    check (takedown_status in ('none', 'unpublished', 'hard_deleted')),
  constraint source_publications_source_item_uk
    unique (source_id, external_key)
);

create table machimoa_review.source_publication_events (
  id pg_catalog.uuid primary key default pg_catalog.gen_random_uuid(),
  event_kind pg_catalog.text not null,
  source_id pg_catalog.text not null,
  external_key pg_catalog.text not null,
  revision_hash pg_catalog.text,
  candidate_id pg_catalog.uuid,
  public_curation_id pg_catalog.uuid,
  slug pg_catalog.text,
  occurred_at pg_catalog.timestamptz not null default pg_catalog.now(),
  actor pg_catalog.text,
  reason pg_catalog.text,
  constraint source_publication_events_kind_ck
    check (
      event_kind in (
        'published',
        'unpublished',
        'hard_deleted',
        'permission_revoked'
      )
    )
);

create table machimoa_review.source_permission_events (
  id pg_catalog.uuid primary key default pg_catalog.gen_random_uuid(),
  source_id pg_catalog.text not null
    references machimoa_review.ingest_sources (source_id)
    on delete restrict,
  from_status pg_catalog.text not null,
  to_status pg_catalog.text not null,
  changed_at pg_catalog.timestamptz not null default pg_catalog.now(),
  reason pg_catalog.text,
  evidence_note pg_catalog.text,
  actor pg_catalog.text not null,
  constraint source_permission_events_note_ck
    check (
      evidence_note is null
      or pg_catalog.char_length(evidence_note) <= 500
    )
);

insert into machimoa_review.ingest_sources (
  source_id,
  provider,
  source_kind,
  connector_type,
  enabled,
  permission_status,
  legacy_curation_source
)
values
  (
    'youthcenter_policy',
    'youthcenter',
    'policy',
    'rest',
    true,
    'testing_only',
    'youthcenter'
  ),
  (
    'youthcenter_content',
    'youthcenter',
    'content',
    'rest',
    true,
    'testing_only',
    'youthcenter_content'
  );

insert into machimoa_review.source_sync_state (source_id)
values ('youthcenter_policy'), ('youthcenter_content');

alter table machimoa_review.ingest_sources enable row level security;
alter table machimoa_review.source_sync_state enable row level security;
alter table machimoa_review.ingest_runs enable row level security;
alter table machimoa_review.source_items enable row level security;
alter table machimoa_review.processing_jobs enable row level security;
alter table machimoa_review.source_relationships enable row level security;
alter table machimoa_review.source_publications enable row level security;
alter table machimoa_review.source_publication_events enable row level security;
alter table machimoa_review.source_permission_events enable row level security;

revoke all privileges on table machimoa_review.ingest_sources
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_review.source_sync_state
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_review.ingest_runs
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_review.source_items
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_review.processing_jobs
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_review.source_relationships
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_review.source_publications
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_review.source_publication_events
  from public, anon, authenticated, service_role;
revoke all privileges on table machimoa_review.source_permission_events
  from public, anon, authenticated, service_role;

create function machimoa_review.canonical_source_id(
  p_source pg_catalog.text
)
returns pg_catalog.text
language sql
stable
security definer
set search_path = ''
as $function$
  select case pg_catalog.btrim(pg_catalog.lower(coalesce(p_source, '')))
    when 'youthcenter' then 'youthcenter_policy'
    when 'youthcenter_policy' then 'youthcenter_policy'
    when 'youthcenter_content' then 'youthcenter_content'
    else null
  end;
$function$;

alter function machimoa_review.canonical_source_id(pg_catalog.text)
  owner to postgres;

revoke all privileges
  on function machimoa_review.canonical_source_id(pg_catalog.text)
  from public, anon, authenticated, service_role;

grant execute
  on function machimoa_review.canonical_source_id(pg_catalog.text)
  to service_role;

create function machimoa_review.start_ingest_run(
  p_source_id pg_catalog.text,
  p_lease_seconds pg_catalog.int4 default 120
)
returns table (
  run_id pg_catalog.uuid,
  bootstrap_complete pg_catalog.bool,
  committed_checkpoint pg_catalog.jsonb,
  skipped pg_catalog.bool,
  skip_reason pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_source_id pg_catalog.text := pg_catalog.btrim(coalesce(p_source_id, ''));
  v_lease_seconds pg_catalog.int4 := coalesce(p_lease_seconds, 120);
  v_enabled pg_catalog.bool;
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_sync machimoa_review.source_sync_state%rowtype;
  v_run_id pg_catalog.uuid;
begin
  if v_source_id !~ '^[a-z][a-z0-9_]{1,31}$' then
    raise exception 'invalid source_id';
  end if;
  if v_lease_seconds < 30 or v_lease_seconds > 3600 then
    raise exception 'invalid lease_seconds';
  end if;

  select s.enabled into v_enabled
  from machimoa_review.ingest_sources as s
  where s.source_id = v_source_id;
  if not found or not v_enabled then
    return query select
      null::pg_catalog.uuid,
      false,
      null::pg_catalog.jsonb,
      true,
      'source_disabled'::pg_catalog.text;
    return;
  end if;

  select *
    into v_sync
  from machimoa_review.source_sync_state as st
  where st.source_id = v_source_id
  for update;

  if v_sync.lease_owner is not null
     and v_sync.lease_expires_at is not null
     and v_sync.lease_expires_at > v_now then
    return query select
      null::pg_catalog.uuid,
      v_sync.bootstrap_complete,
      v_sync.committed_checkpoint,
      true,
      'lease_held'::pg_catalog.text;
    return;
  end if;

  v_run_id := pg_catalog.gen_random_uuid();
  insert into machimoa_review.ingest_runs (id, source_id, status, lease_seconds)
  values (v_run_id, v_source_id, 'running', v_lease_seconds);

  update machimoa_review.source_sync_state as st
  set
    lease_owner = v_run_id,
    lease_expires_at = v_now + (v_lease_seconds || ' seconds')::pg_catalog.interval,
    lease_seconds = v_lease_seconds,
    active_run_id = v_run_id,
    updated_at = v_now
  where st.source_id = v_source_id;

  return query select
    v_run_id,
    v_sync.bootstrap_complete,
    v_sync.committed_checkpoint,
    false,
    null::pg_catalog.text;
end
$function$;

create function machimoa_review.jsonb_has_forbidden_attachment(
  p_data pg_catalog.jsonb
)
returns pg_catalog.bool
language plpgsql
immutable
security definer
set search_path = ''
as $function$
declare
  v_key pg_catalog.text;
  v_value pg_catalog.jsonb;
  v_compact pg_catalog.text;
begin
  if p_data is null then
    return false;
  end if;
  if pg_catalog.jsonb_typeof(p_data) = 'array' then
    for v_value in
      select e.elem
      from pg_catalog.jsonb_array_elements(p_data) as e(elem)
    loop
      if machimoa_review.jsonb_has_forbidden_attachment(v_value) then
        return true;
      end if;
    end loop;
    return false;
  end if;
  if pg_catalog.jsonb_typeof(p_data) <> 'object' then
    return false;
  end if;
  for v_key, v_value in
    select e.key, e.value
    from pg_catalog.jsonb_each(p_data) as e(key, value)
  loop
    v_compact := replace(replace(pg_catalog.lower(v_key), '-', ''), ' ', '');
    if v_compact in ('atchfile', 'atch_file', 'atchfilename') then
      return true;
    end if;
    if machimoa_review.jsonb_has_forbidden_attachment(v_value) then
      return true;
    end if;
  end loop;
  return false;
end
$function$;

create function machimoa_review.upsert_source_observations(
  p_source_id pg_catalog.text,
  p_run_id pg_catalog.uuid,
  p_items pg_catalog.jsonb,
  p_next_checkpoint pg_catalog.jsonb
)
returns table (
  input_index pg_catalog.int4,
  external_key pg_catalog.text,
  outcome pg_catalog.text,
  duplicate_in_batch pg_catalog.bool
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_source_id pg_catalog.text := pg_catalog.btrim(coalesce(p_source_id, ''));
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_sync machimoa_review.source_sync_state%rowtype;
  v_item pg_catalog.jsonb;
  v_idx pg_catalog.int4;
  v_key pg_catalog.text;
  v_hash pg_catalog.text;
  v_existing_hash pg_catalog.text;
  v_existing_id pg_catalog.uuid;
  v_outcome pg_catalog.text;
  v_dup pg_catalog.bool;
  v_seen pg_catalog.text[] := '{}'::pg_catalog.text[];
  v_item_id pg_catalog.uuid;
  v_job pg_catalog.jsonb;
  v_rel pg_catalog.jsonb;
  v_lease_seconds pg_catalog.int4;
begin
  if v_source_id !~ '^[a-z][a-z0-9_]{1,31}$' or p_run_id is null then
    raise exception 'invalid source_id or run_id';
  end if;
  if p_items is null or pg_catalog.jsonb_typeof(p_items) <> 'array' then
    raise exception 'items must be a json array';
  end if;
  if pg_catalog.jsonb_array_length(p_items) > 40 then
    raise exception 'batch too large';
  end if;
  if pg_catalog.octet_length(p_items::pg_catalog.text) > 1000000 then
    raise exception 'batch payload too large';
  end if;

  select *
    into v_sync
  from machimoa_review.source_sync_state as st
  where st.source_id = v_source_id
  for update;

  if v_sync.active_run_id is distinct from p_run_id
     or v_sync.lease_owner is distinct from p_run_id
     or v_sync.lease_expires_at is null
     or v_sync.lease_expires_at <= v_now then
    raise exception 'lease_lost';
  end if;

  select r.lease_seconds
    into v_lease_seconds
  from machimoa_review.ingest_runs as r
  where r.id = p_run_id;
  if not found or v_lease_seconds is null then
    raise exception 'lease_lost';
  end if;

  for v_idx in 0 .. pg_catalog.jsonb_array_length(p_items) - 1 loop
    v_item := p_items -> v_idx;
    if pg_catalog.jsonb_typeof(v_item) <> 'object' then
      raise exception 'item must be an object';
    end if;
    if machimoa_review.jsonb_has_forbidden_attachment(v_item) then
      raise exception 'forbidden_attachment_key';
    end if;

    v_key := pg_catalog.btrim(coalesce(v_item ->> 'external_key', ''));
    v_hash := pg_catalog.btrim(coalesce(v_item ->> 'revision_hash', ''));
    if pg_catalog.char_length(v_key) not between 1 and 128 then
      raise exception 'invalid external_key';
    end if;
    if v_hash !~ '^[0-9a-f]{64}$' then
      raise exception 'invalid revision_hash';
    end if;

    v_dup := v_key = any (v_seen);
    v_seen := pg_catalog.array_append(v_seen, v_key);

    select si.id, si.revision_hash
      into v_existing_id, v_existing_hash
    from machimoa_review.source_items as si
    where si.source_id = v_source_id
      and si.external_key = v_key;

    if v_existing_id is null then
      v_outcome := 'new';
      insert into machimoa_review.source_items (
        source_id,
        external_key,
        revision_hash,
        first_seen_at,
        last_seen_at,
        source_created_at,
        source_created_raw,
        source_created_parse_status,
        source_updated_at,
        source_updated_raw,
        source_updated_parse_status,
        disposition,
        min_fields,
        normalized_payload,
        has_source_url,
        body_usable,
        attachment_present,
        attachment_length,
        is_data_url,
        last_run_id
      )
      values (
        v_source_id,
        v_key,
        v_hash,
        v_now,
        v_now,
        nullif(v_item ->> 'source_created_at', '')::pg_catalog.timestamptz,
        pg_catalog.left(nullif(v_item ->> 'source_created_raw', ''), 64),
        coalesce(nullif(v_item ->> 'source_created_parse_status', ''), 'missing'),
        nullif(v_item ->> 'source_updated_at', '')::pg_catalog.timestamptz,
        pg_catalog.left(nullif(v_item ->> 'source_updated_raw', ''), 64),
        coalesce(nullif(v_item ->> 'source_updated_parse_status', ''), 'missing'),
        coalesce(nullif(v_item ->> 'disposition', ''), 'observe_only'),
        coalesce(v_item -> 'min_fields', '{}'::pg_catalog.jsonb),
        v_item -> 'normalized_payload',
        coalesce((v_item ->> 'has_source_url')::pg_catalog.bool, false),
        coalesce((v_item ->> 'body_usable')::pg_catalog.bool, false),
        coalesce((v_item ->> 'attachment_present')::pg_catalog.bool, false),
        coalesce((v_item ->> 'attachment_length')::pg_catalog.int4, 0),
        coalesce((v_item ->> 'is_data_url')::pg_catalog.bool, false),
        p_run_id
      )
      returning id into v_item_id;
    elsif v_existing_hash is distinct from v_hash then
      v_outcome := 'changed';
      update machimoa_review.source_items as si
      set
        revision_hash = v_hash,
        last_seen_at = v_now,
        source_created_at = nullif(v_item ->> 'source_created_at', '')::pg_catalog.timestamptz,
        source_created_raw = pg_catalog.left(nullif(v_item ->> 'source_created_raw', ''), 64),
        source_created_parse_status =
          coalesce(nullif(v_item ->> 'source_created_parse_status', ''), 'missing'),
        source_updated_at = nullif(v_item ->> 'source_updated_at', '')::pg_catalog.timestamptz,
        source_updated_raw = pg_catalog.left(nullif(v_item ->> 'source_updated_raw', ''), 64),
        source_updated_parse_status =
          coalesce(nullif(v_item ->> 'source_updated_parse_status', ''), 'missing'),
        disposition = coalesce(nullif(v_item ->> 'disposition', ''), si.disposition),
        min_fields = coalesce(v_item -> 'min_fields', si.min_fields),
        normalized_payload = v_item -> 'normalized_payload',
        has_source_url = coalesce((v_item ->> 'has_source_url')::pg_catalog.bool, false),
        body_usable = coalesce((v_item ->> 'body_usable')::pg_catalog.bool, false),
        attachment_present = coalesce((v_item ->> 'attachment_present')::pg_catalog.bool, false),
        attachment_length = coalesce((v_item ->> 'attachment_length')::pg_catalog.int4, 0),
        is_data_url = coalesce((v_item ->> 'is_data_url')::pg_catalog.bool, false),
        last_run_id = p_run_id
      where si.id = v_existing_id;
      v_item_id := v_existing_id;
    else
      v_outcome := 'unchanged';
      update machimoa_review.source_items as si
      set last_seen_at = v_now, last_run_id = p_run_id
      where si.id = v_existing_id;
      v_item_id := v_existing_id;
    end if;

    if v_outcome in ('new', 'changed') and not v_dup then
      for v_job in
        select value from pg_catalog.jsonb_array_elements(
          coalesce(v_item -> 'jobs', '[]'::pg_catalog.jsonb)
        )
      loop
        insert into machimoa_review.processing_jobs (
          source_item_id,
          revision_hash,
          processing_stage,
          status,
          queued_at,
          available_at,
          reason_codes
        )
        values (
          v_item_id,
          v_hash,
          v_job ->> 'stage',
          'queued',
          v_now,
          v_now,
          coalesce(
            array(select pg_catalog.jsonb_array_elements_text(v_job -> 'reason_codes')),
            '{}'::pg_catalog.text[]
          )
        )
        on conflict (source_item_id, revision_hash, processing_stage)
        do nothing;
      end loop;

      for v_rel in
        select value from pg_catalog.jsonb_array_elements(
          coalesce(v_item -> 'relationships', '[]'::pg_catalog.jsonb)
        )
      loop
        insert into machimoa_review.source_relationships (
          from_source_id,
          from_external_key,
          to_source_id,
          to_external_key,
          relation_kind
        )
        values (
          v_source_id,
          v_key,
          v_rel ->> 'to_source_id',
          v_rel ->> 'to_external_key',
          coalesce(v_rel ->> 'relation_kind', 'candidate')
        )
        on conflict on constraint source_relationships_unique
        do nothing;
      end loop;
    end if;

    input_index := v_idx;
    external_key := v_key;
    outcome := v_outcome;
    duplicate_in_batch := v_dup;
    return next;
  end loop;

  update machimoa_review.source_sync_state as st
  set
    committed_checkpoint = p_next_checkpoint,
    lease_expires_at = v_now + (v_lease_seconds || ' seconds')::pg_catalog.interval,
    updated_at = v_now
  where st.source_id = v_source_id
    and st.active_run_id = p_run_id
    and st.lease_owner = p_run_id;

  update machimoa_review.ingest_runs as r
  set batches_ok = r.batches_ok + 1
  where r.id = p_run_id;
end
$function$;

create function machimoa_review.finish_ingest_run(
  p_run_id pg_catalog.uuid,
  p_status pg_catalog.text,
  p_stop_reason pg_catalog.text,
  p_http_request_count pg_catalog.int4,
  p_bootstrap_complete pg_catalog.bool default false,
  p_batches_ok pg_catalog.int4 default 0
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_run machimoa_review.ingest_runs%rowtype;
  v_sync machimoa_review.source_sync_state%rowtype;
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_owns pg_catalog.bool;
begin
  if p_run_id is null then
    raise exception 'run_id is required';
  end if;
  if p_status not in ('complete', 'incomplete', 'failed') then
    raise exception 'invalid status';
  end if;
  if pg_catalog.char_length(coalesce(p_stop_reason, '')) > 64 then
    raise exception 'invalid stop_reason';
  end if;

  select * into v_run
  from machimoa_review.ingest_runs as r
  where r.id = p_run_id;
  if not found then
    return;
  end if;

  select * into v_sync
  from machimoa_review.source_sync_state as st
  where st.source_id = v_run.source_id
  for update;

  v_owns := v_sync.lease_owner is not distinct from p_run_id
            and v_sync.active_run_id is not distinct from p_run_id;

  if not v_owns then
    update machimoa_review.ingest_runs as r
    set
      status = 'incomplete',
      stop_reason = 'lease_lost',
      finished_at = coalesce(r.finished_at, v_now),
      http_request_count = coalesce(p_http_request_count, r.http_request_count)
    where r.id = p_run_id;
    return;
  end if;

  update machimoa_review.ingest_runs as r
  set
    status = p_status,
    stop_reason = p_stop_reason,
    http_request_count = coalesce(p_http_request_count, 0),
    batches_ok = case
      when p_batches_ok > 0 then p_batches_ok
      else r.batches_ok
    end,
    finished_at = v_now
  where r.id = p_run_id;

  update machimoa_review.source_sync_state as st
  set
    lease_owner = null,
    lease_expires_at = null,
    active_run_id = null,
    last_stop_reason = p_stop_reason,
    last_success_at = case
      when coalesce(p_batches_ok, v_run.batches_ok) > 0 then v_now
      else st.last_success_at
    end,
    bootstrap_complete = case
      when p_bootstrap_complete
           and p_status = 'complete'
           and p_stop_reason in (
             'bootstrap_range_complete',
             'empty_batch',
             'short_batch'
           )
      then true
      else st.bootstrap_complete
    end,
    updated_at = v_now
  where st.source_id = v_run.source_id
    and st.lease_owner is not distinct from p_run_id
    and st.active_run_id is not distinct from p_run_id;
end
$function$;

create function machimoa_review.claim_processing_jobs(
  p_stage pg_catalog.text,
  p_limit pg_catalog.int4,
  p_worker_id pg_catalog.text,
  p_lease_seconds pg_catalog.int4 default 300
)
returns table (
  job_id pg_catalog.uuid,
  source_item_id pg_catalog.uuid,
  source_id pg_catalog.text,
  external_key pg_catalog.text,
  revision_hash pg_catalog.text,
  processing_stage pg_catalog.text,
  curation_source pg_catalog.text,
  normalized_payload pg_catalog.jsonb,
  disposition pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_limit pg_catalog.int4 := coalesce(p_limit, 10);
  v_worker pg_catalog.text := pg_catalog.btrim(coalesce(p_worker_id, ''));
  v_lease pg_catalog.int4 := coalesce(p_lease_seconds, 300);
begin
  if p_stage is distinct from 'ai_enrichment' then
    return;
  end if;
  if v_limit < 1 or v_limit > 10 then
    raise exception 'invalid claim limit';
  end if;
  if pg_catalog.char_length(v_worker) not between 1 and 64 then
    raise exception 'invalid worker_id';
  end if;

  return query
  with picked as (
    select j.id
    from machimoa_review.processing_jobs as j
    where j.processing_stage = 'ai_enrichment'
      and (
        (
          j.status = 'queued'
          and j.available_at <= v_now
          and (j.next_retry_at is null or j.next_retry_at <= v_now)
        )
        or (
          j.status = 'claimed'
          and j.claim_lease_until is not null
          and j.claim_lease_until < v_now
        )
      )
    order by j.queued_at, j.id
    for update skip locked
    limit v_limit
  ),
  updated as (
    update machimoa_review.processing_jobs as j
    set
      status = 'claimed',
      claimed_at = v_now,
      claim_lease_until = v_now + (v_lease || ' seconds')::pg_catalog.interval,
      claimed_by = v_worker
    from picked
    where j.id = picked.id
    returning j.*
  )
  select
    u.id,
    u.source_item_id,
    si.source_id,
    si.external_key,
    u.revision_hash,
    u.processing_stage,
    s.legacy_curation_source,
    si.normalized_payload,
    si.disposition
  from updated as u
  join machimoa_review.source_items as si
    on si.id = u.source_item_id
  join machimoa_review.ingest_sources as s
    on s.source_id = si.source_id;
end
$function$;

create function machimoa_review.complete_processing_job(
  p_job_id pg_catalog.uuid,
  p_worker_id pg_catalog.text
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_stage pg_catalog.text;
  v_claimed_by pg_catalog.text;
begin
  select j.processing_stage, j.claimed_by
    into v_stage, v_claimed_by
  from machimoa_review.processing_jobs as j
  where j.id = p_job_id
  for update;
  if not found then
    raise exception 'job not found';
  end if;
  if v_stage is distinct from 'ai_enrichment' then
    raise exception 'human_job_not_completable_by_ai';
  end if;
  if v_claimed_by is distinct from pg_catalog.btrim(p_worker_id) then
    raise exception 'lease_lost';
  end if;
  update machimoa_review.processing_jobs
  set status = 'completed', completed_at = pg_catalog.now()
  where id = p_job_id;
end
$function$;

create function machimoa_review.fail_processing_job(
  p_job_id pg_catalog.uuid,
  p_worker_id pg_catalog.text,
  p_error_code pg_catalog.text
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_stage pg_catalog.text;
  v_claimed_by pg_catalog.text;
  v_code pg_catalog.text := pg_catalog.left(pg_catalog.btrim(coalesce(p_error_code, 'error')), 64);
  -- Keep in sync with scripts/ingest/constants.py AI_MAX_ATTEMPTS.
  v_ai_max_attempts pg_catalog.int4 := 3;
begin
  select j.processing_stage, j.claimed_by
    into v_stage, v_claimed_by
  from machimoa_review.processing_jobs as j
  where j.id = p_job_id
  for update;
  if v_stage is distinct from 'ai_enrichment' then
    raise exception 'human_job_not_completable_by_ai';
  end if;
  if v_claimed_by is distinct from pg_catalog.btrim(p_worker_id) then
    raise exception 'lease_lost';
  end if;
  update machimoa_review.processing_jobs
  set
    error_code = v_code,
    retry_count = retry_count + 1,
    claimed_by = null,
    claim_lease_until = null,
    status = case
      when retry_count + 1 >= v_ai_max_attempts then 'failed'
      else 'queued'
    end,
    next_retry_at = case
      when retry_count + 1 >= v_ai_max_attempts then null
      else pg_catalog.now() + interval '30 seconds'
    end
  where id = p_job_id;
end
$function$;

create function machimoa_review.set_source_permission(
  p_source_id pg_catalog.text,
  p_to_status pg_catalog.text,
  p_reason pg_catalog.text,
  p_evidence_note pg_catalog.text,
  p_actor pg_catalog.text
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_source_id pg_catalog.text;
  v_to pg_catalog.text := pg_catalog.btrim(coalesce(p_to_status, ''));
  v_from pg_catalog.text;
  v_actor pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_actor, '')), '');
  v_reason pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_reason, '')), '');
  v_note pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_evidence_note, '')), '');
begin
  v_source_id := machimoa_review.canonical_source_id(p_source_id);
  if v_source_id is null then
    raise exception 'unknown source identity';
  end if;
  if v_actor is null or pg_catalog.char_length(v_actor) > 128 then
    raise exception 'invalid actor';
  end if;
  if v_reason is null or pg_catalog.char_length(v_reason) > 500 then
    raise exception 'invalid reason';
  end if;
  if v_note is not null and pg_catalog.char_length(v_note) > 500 then
    raise exception 'invalid evidence_note';
  end if;
  if v_to not in (
    'testing_only',
    'approved_noncommercial',
    'commercial_review_required',
    'approved_commercial'
  ) then
    raise exception 'invalid permission_status';
  end if;

  select s.permission_status
    into v_from
  from machimoa_review.ingest_sources as s
  where s.source_id = v_source_id
  for update;
  if not found then
    raise exception 'source_not_found';
  end if;

  -- Keep in sync with scripts/ingest/source_identity.py ALLOWED_PERMISSION_TRANSITIONS.
  if not (
    (v_from = 'testing_only' and v_to = 'approved_noncommercial')
    or (
      v_from = 'approved_noncommercial'
      and v_to = 'commercial_review_required'
    )
    or (
      v_from = 'commercial_review_required'
      and v_to = 'approved_commercial'
    )
  ) then
    raise exception 'permission_transition_not_allowed';
  end if;

  update machimoa_review.ingest_sources as s
  set
    permission_status = v_to,
    updated_at = pg_catalog.now()
  where s.source_id = v_source_id;

  insert into machimoa_review.source_permission_events (
    source_id,
    from_status,
    to_status,
    reason,
    evidence_note,
    actor
  )
  values (
    v_source_id,
    v_from,
    v_to,
    v_reason,
    v_note,
    v_actor
  );
end
$function$;

alter function machimoa_review.start_ingest_run(pg_catalog.text, pg_catalog.int4)
  owner to postgres;
alter function machimoa_review.upsert_source_observations(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.finish_ingest_run(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4,
  pg_catalog.bool, pg_catalog.int4
) owner to postgres;
alter function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) owner to postgres;
alter function machimoa_review.complete_processing_job(
  pg_catalog.uuid, pg_catalog.text
) owner to postgres;
alter function machimoa_review.fail_processing_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.jsonb_has_forbidden_attachment(pg_catalog.jsonb)
  owner to postgres;
alter function machimoa_review.set_source_permission(
  pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text
) owner to postgres;

revoke all privileges on function machimoa_review.start_ingest_run(
  pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.upsert_source_observations(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.finish_ingest_run(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4,
  pg_catalog.bool, pg_catalog.int4
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.complete_processing_job(
  pg_catalog.uuid, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.fail_processing_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.jsonb_has_forbidden_attachment(
  pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.set_source_permission(
  pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;

grant execute on function machimoa_review.start_ingest_run(
  pg_catalog.text, pg_catalog.int4
) to service_role;
grant execute on function machimoa_review.upsert_source_observations(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) to service_role;
grant execute on function machimoa_review.finish_ingest_run(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4,
  pg_catalog.bool, pg_catalog.int4
) to service_role;
grant execute on function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) to service_role;
grant execute on function machimoa_review.complete_processing_job(
  pg_catalog.uuid, pg_catalog.text
) to service_role;
grant execute on function machimoa_review.fail_processing_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) to service_role;

commit;
