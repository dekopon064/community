begin;
set local lock_timeout='5s'; set local statement_timeout='30s';
-- No data backfill, history rewrite or automatic classification of existing posts.
do $$ declare r record; f record; begin
 if current_user<>'postgres' then raise exception 'postgres_required'; end if;
 for r in select * from (values
('machimoa_review.content_filter_missing(jsonb)','ab2b7dd9a14a61a8a2d6e96e3a7cd672c677ef0b2afce5fd49e26f418a2df1c0','{postgres=X/postgres}',false),
('machimoa_review.content_filter_validate(jsonb)','955accd4e14024477be3c910fc12171c0dd46eca127aa1945137b0d11d39a97c','{postgres=X/postgres}',false),
('public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)','29e50a416572a408f772b9150d5be96e5935e1e5344f93da1f6f6c4d7bdb29fc','{postgres=X/postgres,service_role=X/postgres}',true),
('machimoa_review.seoul_before_filter_fact_sync(uuid,text,text,bigint,jsonb,uuid)','44a360fced3f1963ecea9e6902c87760e9269eb9c32dd2e9f91921b38e0ccd39','{postgres=X/postgres}',true),
('machimoa_review.classification_filter_missing(jsonb)','129dba73ccf3f05628fc7b2445d5705ed8b59590536831eee130d47770c72b98','{postgres=X/postgres}',false)
 ) x(signature,hash,acl,definer) loop
  select * into f from pg_proc where oid=to_regprocedure(r.signature);
  if f.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(f.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash
   or pg_get_userbyid(f.proowner)<>'postgres' or f.proconfig is distinct from array['search_path=""']::text[]
   or f.prosecdef is distinct from r.definer or f.proacl::text is distinct from r.acl
   then raise exception 'foreigner_filter_predecessor_changed: %',r.signature; end if;
 end loop;
end $$;
create or replace function machimoa_review.classification_filter_missing(v jsonb) returns text[]
language sql immutable set search_path='' as $$
 select coalesce(array_agg(key order by key),'{}'::text[]) from (
  select key from jsonb_each(v-'schema'-'category') where value->>'status'='unknown' and key<>'foreignerProgram'
  union select 'application' where v->>'category'='program' and 'application'=any(machimoa_review.content_filter_missing(v))
 ) pending
$$;
-- Preserve every original v1 value/shape check in a private validator.
do $$ declare d text; begin
 if to_regprocedure('machimoa_review.foreigner_filter_legacy_validate(jsonb)') is not null then raise exception 'foreigner_filter_already_installed'; end if;
 d:=pg_get_functiondef('machimoa_review.content_filter_validate(jsonb)'::regprocedure);
 execute replace(d,'FUNCTION machimoa_review.content_filter_validate(', 'FUNCTION machimoa_review.foreigner_filter_legacy_validate(');
end $$;
revoke all on function machimoa_review.foreigner_filter_legacy_validate(jsonb) from public,anon,authenticated,service_role;
create or replace function machimoa_review.content_filter_validate(v jsonb) returns void
language plpgsql immutable set search_path='' as $$
declare f jsonb; begin
 if v is not null and octet_length(v::text)>120000 then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 perform machimoa_review.foreigner_filter_legacy_validate(v-'foreignerProgram');
 if not v ? 'foreignerProgram' then return; end if;
 f:=v->'foreignerProgram';
 if jsonb_typeof(f) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(f) key) is distinct from array['status','value']
  or f->>'status' is null or f->>'status' not in ('known','unknown','not_applicable')
  or (v->>'category'='program' and f->>'status'='not_applicable')
  or (v->>'category'<>'program' and f->>'status'<>'not_applicable')
  or (f->>'status'='known' and (jsonb_typeof(f->'value') is distinct from 'string' or f->>'value' not in ('foreigner','other')))
  or (f->>'status'<>'known' and f->'value' is distinct from 'null'::jsonb)
  then raise sqlstate 'PT422' using message='invalid_content_filters'; end if;
end $$;
-- Optional discovery metadata does not create a new AI/publish prerequisite.
do $$ declare d text; begin
 d:=pg_get_functiondef('machimoa_review.content_filter_missing(jsonb)'::regprocedure);
 d:=replace(d,'where value->>''status''=''unknown''','where value->>''status''=''unknown'' and key<>''foreignerProgram''');
 execute d;
end $$;
CREATE OR REPLACE FUNCTION machimoa_review.seoul_before_filter_fact_sync(p_id uuid, p_revision text, p_version text, p_filter_version bigint, p_patch jsonb, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype;f machimoa_review.source_item_content_filters%rowtype;d jsonb;k text;fields text[];item jsonb;
begin
 if p_actor is null or p_patch is null or jsonb_typeof(p_patch) is distinct from 'object' or octet_length(p_patch::text)>120000 then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 select * into s from machimoa_review.source_items where id=p_id for update;
 if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 if s.source_id='myseoul_program' then perform machimoa_review.myseoul_admin_lock(p_id,p_revision,p_version,p_actor);
 elsif s.source_id='seoul_reservation' then
 perform 1 from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
 item:=public.admin_program_detail(p_id);
 if item->>'status'<>'open' or s.revision_hash is distinct from p_revision or item->>'version' is distinct from p_version then raise sqlstate 'PT409' using message='review_conflict';end if;
 else perform machimoa_review.admin_review_lock('facts',p_id,p_revision,p_version,p_actor);end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed' and (claim_lease_until is null or claim_lease_until>clock_timestamp())) then raise sqlstate 'PT409' using message='content_filter_processing_active';end if;
 select * into f from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision for update;
 if not found or f.filter_version is distinct from p_filter_version then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
 if exists(select 1 from jsonb_object_keys(p_patch) key where key not in ('topic','location','delivery','audience','foreignerProgram','spaceKind','application','schedule')) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 select array_agg(key order by key) into fields from jsonb_object_keys(p_patch) key;
 if coalesce(cardinality(fields),0)=0 then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 d:=f.data||p_patch;perform machimoa_review.content_filter_validate(d);
 if p_patch ? 'application' and d->>'category'='program' and 'application'=any(machimoa_review.content_filter_missing(d)) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 if not machimoa_review.content_filter_consistent(p_id,p_revision,d) then raise sqlstate 'PT422' using message='content_filter_facts_mismatch';end if;
 if d->>'category' is distinct from machimoa_review.content_filter_category(p_id,p_revision) or f.source_binding is distinct from machimoa_review.content_filter_binding(p_id,p_revision) then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
 if p_patch ? 'foreignerProgram' and p_patch-'foreignerProgram'='{}'::jsonb and f.data->'foreignerProgram'=p_patch->'foreignerProgram' and f.origins->>'foreignerProgram'='operator' then return public.admin_content_filter_detail(p_id);end if;
 update machimoa_review.source_item_content_filters set data=d,filter_version=filter_version+1,origins=origins||(select jsonb_object_agg(field_key,'operator') from unnest(fields) field_key),updated_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.content_filter_edits(source_item_id,revision_hash,filter_version,actor,origin,fields,before_data,after_data)
 select p_id,p_revision,filter_version,p_actor,'operator',fields,f.data,d from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision;
 perform machimoa_review.content_filter_review_sync(p_id,p_revision);
 if machimoa_review.content_filter_ready(p_id,p_revision) and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='ai_enrichment' and status in ('failed','completed','claimed')) and not exists(select 1 from machimoa_review.curation_candidates c join machimoa_review.ingest_sources src on src.source_id=s.source_id where c.source=src.legacy_curation_source and c.source_item_id=s.external_key and c.source_revision_hash=s.revision_hash) then
 if s.source_id='myseoul_program' then perform machimoa_review.myseoul_refresh(p_id);
 elsif s.source_id='seoul_reservation' then perform machimoa_review.program_refresh(p_id);
 elsif s.disposition='target' and machimoa_review.category_period_ready(p_id,p_revision) and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) then perform machimoa_review.ensure_ai_enrichment_job(p_id,p_revision,'{}'::text[]);end if;end if;
 perform machimoa_review.content_filter_review_sync(p_id,p_revision);
 return public.admin_content_filter_detail(p_id);
end $function$
;
CREATE OR REPLACE FUNCTION public.admin_content_filter_save(p_id uuid, p_revision text, p_version text, p_filter_version bigint, p_patch jsonb, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype;ignored jsonb;begin
 select * into s from machimoa_review.source_items where id=p_id for update;
 if s.source_id='seoul_reservation' then
  perform 1 from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
  perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
  perform machimoa_review.ai_recheck_edit_guard(p_id,p_revision);
  perform pg_advisory_xact_lock(hashtextextended('seoul_reservation'||':'||s.external_key,0));
  perform 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key for update;
 end if;
 ignored:=machimoa_review.seoul_before_filter_fact_sync(p_id,p_revision,p_version,p_filter_version,p_patch,p_actor);
 if p_patch ? 'foreignerProgram' and p_patch-'foreignerProgram'='{}'::jsonb then return ignored;end if;
 if s.source_id='seoul_reservation' then perform machimoa_review.seoul_filter_facts_sync(p_id,p_revision,p_actor);end if;
 return public.admin_content_filter_detail(p_id);
end $function$
;
revoke all on function machimoa_review.content_filter_validate(jsonb),machimoa_review.content_filter_missing(jsonb),machimoa_review.seoul_before_filter_fact_sync(uuid,text,text,bigint,jsonb,uuid) from public,anon,authenticated,service_role;
revoke all on function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) from public,anon,authenticated;
grant execute on function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) to service_role;
notify pgrst,'reload schema';
commit;
