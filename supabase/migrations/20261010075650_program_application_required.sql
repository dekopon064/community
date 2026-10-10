begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- Programs require both application dates. Stored snapshots are not rewritten.
do $$ begin
if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.content_filter_missing(jsonb)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_missing(jsonb)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'65737c08c582ace3752b945f09aa65a01b911092f4cbb6aea62373b8eff5e7d2' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_missing(jsonb)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_missing(jsonb)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_missing(jsonb)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','machimoa_review.content_filter_missing(jsonb)';end if;
if to_regprocedure('machimoa_review.classification_filter_missing(jsonb)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.classification_filter_missing(jsonb)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'ad4f9fe2f8b91a3b07b030875117aec6adeacbd0f78638ebc7be6e9791a22c74' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.classification_filter_missing(jsonb)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.classification_filter_missing(jsonb)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.classification_filter_missing(jsonb)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','machimoa_review.classification_filter_missing(jsonb)';end if;
if to_regprocedure('machimoa_review.classification_ready(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.classification_ready(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'deb1343c5f477af4be4493881522943c1a011835c1ac724d5d91e1bcdd27dc92' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.classification_ready(uuid)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.classification_ready(uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.classification_ready(uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','machimoa_review.classification_ready(uuid)';end if;
if to_regprocedure('public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'c845f90b085c84c1aad937b37102af2bdd9f5d3477b661918ba9733e71823c74' or (select proacl::text from pg_proc where oid=to_regprocedure('public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)')) is distinct from '{postgres=X/postgres,service_role=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)';end if;
if to_regprocedure('machimoa_review.classification_validate(jsonb,jsonb)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.classification_validate(jsonb,jsonb)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'b6084da8619aae482112fa827954e64e4b5f686534005eb5cabaa6cf5ae9e814' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.classification_validate(jsonb,jsonb)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.classification_validate(jsonb,jsonb)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.classification_validate(jsonb,jsonb)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','machimoa_review.classification_validate(jsonb,jsonb)';end if;
if to_regprocedure('public.admin_review_classification_detail(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('public.admin_review_classification_detail(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'25226401fa430cec6519c42775d1c6406de2a5d9fae677119608379db3cadda9' or (select proacl::text from pg_proc where oid=to_regprocedure('public.admin_review_classification_detail(uuid)')) is distinct from '{postgres=X/postgres,service_role=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('public.admin_review_classification_detail(uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('public.admin_review_classification_detail(uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','public.admin_review_classification_detail(uuid)';end if;
if to_regclass('machimoa_review.program_dates_install') is not null or to_regprocedure('machimoa_review.program_dates_dirty()') is not null then raise exception 'program_dates_name_collision';end if;
if to_regprocedure('machimoa_review.classification_table_metadata(text)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.classification_table_metadata(text)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'fc280d69b3db727c0b1007895efcb189cafd8d8bd63c317d89be841354353b3f' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.classification_table_metadata(text)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.classification_table_metadata(text)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.classification_table_metadata(text)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','machimoa_review.classification_table_metadata(text)';end if;
if to_regprocedure('machimoa_review.content_filter_ready(uuid,text)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_ready(uuid,text)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'7cd16e7ff0e72f7bd8f2b085e61202dd6d82eef2bb3c620b2b7c337678426856' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_ready(uuid,text)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_ready(uuid,text)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_ready(uuid,text)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','machimoa_review.content_filter_ready(uuid,text)';end if;
if to_regprocedure('machimoa_review.content_filter_consistent(uuid,text,jsonb)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_consistent(uuid,text,jsonb)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'e3ef7e5965540aad282a3bb95c4a6f3e059d50f839f96b30b1823099317667e7' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_consistent(uuid,text,jsonb)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_consistent(uuid,text,jsonb)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_consistent(uuid,text,jsonb)')) is distinct from array['search_path=""']::text[] then raise exception 'program_dates_definition_changed: %','machimoa_review.content_filter_consistent(uuid,text,jsonb)';end if;
if machimoa_review.classification_table_metadata('machimoa_review.source_item_content_filters') is distinct from '{"acl": "{postgres=arwdDxtm/postgres}", "rls": true, "owner": "postgres", "columns": [["source_item_id", "uuid", true, "", "", null], ["revision_hash", "text", true, "", "", null], ["filter_version", "bigint", true, "", "", "1"], ["data", "jsonb", true, "", "", null], ["observed_data", "jsonb", true, "", "", null], ["origins", "jsonb", true, "", "", null], ["evidence", "jsonb", true, "", "", null], ["source_binding", "jsonb", true, "", "", null], ["updated_at", "timestamp with time zone", true, "", "", "clock_timestamp()"]], "indexes": [["machimoa_review.source_item_content_filters_pkey", "CREATE UNIQUE INDEX source_item_content_filters_pkey ON machimoa_review.source_item_content_filters USING btree (source_item_id, revision_hash)", true]], "forceRls": false, "policies": [], "constraints": [["source_item_content_filters_filter_version_check", "CHECK ((filter_version > 0))", true], ["source_item_content_filters_pkey", "PRIMARY KEY (source_item_id, revision_hash)", true], ["source_item_content_filters_source_item_id_fkey", "FOREIGN KEY (source_item_id) REFERENCES machimoa_review.source_items(id)", true]]}'::jsonb then raise exception 'program_dates_schema_changed';end if;
if machimoa_review.classification_table_metadata('machimoa_review.review_classifications') is distinct from '{"acl": "{postgres=arwdDxtm/postgres}", "rls": true, "owner": "postgres", "columns": [["source_item_id", "uuid", true, "", "", null], ["revision_hash", "text", true, "", "", null], ["classification_version", "bigint", true, "", "", null], ["facts", "jsonb", true, "", "", null], ["filters", "jsonb", false, "", "", null], ["native_snapshot", "text", true, "", "", null], ["note", "text", true, "", "", null], ["actor", "uuid", true, "", "", null], ["confirmed_at", "timestamp with time zone", true, "", "", "clock_timestamp()"]], "indexes": [["machimoa_review.review_classifications_pkey", "CREATE UNIQUE INDEX review_classifications_pkey ON machimoa_review.review_classifications USING btree (source_item_id, revision_hash)", true]], "forceRls": false, "policies": [], "constraints": [["review_classifications_classification_version_check", "CHECK ((classification_version > 0))", true], ["review_classifications_native_snapshot_check", "CHECK ((native_snapshot ~ ''^[a-f0-9]{64}$''::text))", true], ["review_classifications_pkey", "PRIMARY KEY (source_item_id, revision_hash)", true], ["review_classifications_source_item_id_fkey", "FOREIGN KEY (source_item_id) REFERENCES machimoa_review.source_items(id)", true]]}'::jsonb then raise exception 'program_dates_schema_changed';end if;
if machimoa_review.classification_table_metadata('machimoa_review.review_classification_history') is distinct from '{"acl": "{postgres=arwdDxtm/postgres}", "rls": true, "owner": "postgres", "columns": [["source_item_id", "uuid", true, "", "", null], ["revision_hash", "text", true, "", "", null], ["classification_version", "bigint", true, "", "", null], ["previous", "jsonb", false, "", "", null], ["current", "jsonb", true, "", "", null], ["actor", "uuid", true, "", "", null], ["note", "text", true, "", "", null], ["at", "timestamp with time zone", true, "", "", "clock_timestamp()"]], "indexes": [["machimoa_review.review_classification_history_pkey", "CREATE UNIQUE INDEX review_classification_history_pkey ON machimoa_review.review_classification_history USING btree (source_item_id, revision_hash, classification_version)", true]], "forceRls": false, "policies": [], "constraints": [["review_classification_history_pkey", "PRIMARY KEY (source_item_id, revision_hash, classification_version)", true]]}'::jsonb then raise exception 'program_dates_schema_changed';end if;
if machimoa_review.classification_table_metadata('machimoa_review.content_filter_edits') is distinct from '{"acl": "{postgres=arwdDxtm/postgres}", "rls": true, "owner": "postgres", "columns": [["id", "uuid", true, "", "", "gen_random_uuid()"], ["source_item_id", "uuid", true, "", "", null], ["revision_hash", "text", true, "", "", null], ["filter_version", "bigint", true, "", "", null], ["actor", "uuid", false, "", "", null], ["origin", "text", true, "", "", null], ["fields", "text[]", true, "", "", null], ["before_data", "jsonb", false, "", "", null], ["after_data", "jsonb", true, "", "", null], ["created_at", "timestamp with time zone", true, "", "", "clock_timestamp()"]], "indexes": [["machimoa_review.content_filter_edits_pkey", "CREATE UNIQUE INDEX content_filter_edits_pkey ON machimoa_review.content_filter_edits USING btree (id)", true]], "forceRls": false, "policies": [], "constraints": [["content_filter_edits_origin_check", "CHECK ((origin = ANY (ARRAY[''automatic''::text, ''operator''::text, ''source_change''::text])))", true], ["content_filter_edits_pkey", "PRIMARY KEY (id)", true], ["content_filter_edits_source_item_id_revision_hash_fkey", "FOREIGN KEY (source_item_id, revision_hash) REFERENCES machimoa_review.source_item_content_filters(source_item_id, revision_hash)", true]]}'::jsonb then raise exception 'program_dates_schema_changed';end if;
end $$;
lock table machimoa_review.source_item_content_filters,machimoa_review.review_classifications,machimoa_review.review_classification_history,machimoa_review.content_filter_edits in share row exclusive mode;
create table machimoa_review.program_dates_install(singleton boolean primary key check(singleton),dirty boolean not null default false);
alter table machimoa_review.program_dates_install enable row level security;
revoke all on machimoa_review.program_dates_install from public,anon,authenticated,service_role;
insert into machimoa_review.program_dates_install values(true,false);
create function machimoa_review.program_dates_dirty() returns trigger language plpgsql security definer set search_path='' as $$ begin update machimoa_review.program_dates_install set dirty=true where singleton and not dirty;return null;end $$;
revoke all on function machimoa_review.program_dates_dirty() from public,anon,authenticated,service_role;
create trigger program_dates_guard after insert or update or delete or truncate on machimoa_review.source_item_content_filters for each statement execute function machimoa_review.program_dates_dirty();
create trigger program_dates_guard after insert or update or delete or truncate on machimoa_review.review_classifications for each statement execute function machimoa_review.program_dates_dirty();
create trigger program_dates_guard after insert or update or delete or truncate on machimoa_review.review_classification_history for each statement execute function machimoa_review.program_dates_dirty();
create trigger program_dates_guard after insert or update or delete or truncate on machimoa_review.content_filter_edits for each statement execute function machimoa_review.program_dates_dirty();
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_missing(v jsonb)
 RETURNS text[]
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO ''
AS $function$
 select coalesce(array_agg(distinct key order by key),'{}'::text[]) from (
 select key from jsonb_each(v-'schema'-'category') where value->>'status'='unknown'
 union all select 'location' where exists(select 1 from jsonb_array_elements(coalesce(v->'location'->'value'->'venues','[]')) p where p->'district'='null'::jsonb)
 union all select 'application' where v->>'category'='program' and (v->'application'->>'status' is distinct from 'known' or v->'application'->'value'->>'deadlineKind' is distinct from 'fixed' or coalesce(v->'application'->'value'->'start','null')='null'::jsonb or coalesce(v->'application'->'value'->'end','null')='null'::jsonb)) q
$function$
;
CREATE OR REPLACE FUNCTION machimoa_review.classification_filter_missing(v jsonb)
 RETURNS text[]
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO ''
AS $function$select coalesce(array_agg(key order by key),'{}'::text[]) from (select key from jsonb_each(v-'schema'-'category') where value->>'status'='unknown' union select 'application' where v->>'category'='program' and 'application'=any(machimoa_review.content_filter_missing(v))) pending$function$
;
CREATE OR REPLACE FUNCTION machimoa_review.classification_ready(p_id uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
 select coalesce((select c.native_snapshot=machimoa_review.classification_native(s.id) and cardinality(machimoa_review.classification_reasons(s.id,c.facts))=0 and (c.facts->>'category'<>'program' or c.facts->>'deadlineKind'='fixed' and c.filters is not null and not ('application'=any(machimoa_review.classification_filter_missing(c.filters)))) and not machimoa_review.admin_trash_pending(s.id,s.revision_hash) and not exists(select 1 from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed')) and src.enabled and src.permission_status in ('approved_noncommercial','approved_commercial')
 from machimoa_review.review_classifications c join machimoa_review.source_items s on s.id=c.source_item_id and s.revision_hash=c.revision_hash join machimoa_review.ingest_sources src on src.source_id=s.source_id where s.id=p_id),false)
$function$
;
CREATE OR REPLACE FUNCTION public.admin_content_filter_save(p_id uuid, p_revision text, p_version text, p_filter_version bigint, p_patch jsonb, p_actor uuid)
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
 if exists(select 1 from jsonb_object_keys(p_patch) key where key not in ('topic','location','delivery','audience','spaceKind','application','schedule')) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 select array_agg(key order by key) into fields from jsonb_object_keys(p_patch) key;
 if coalesce(cardinality(fields),0)=0 then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 d:=f.data||p_patch;perform machimoa_review.content_filter_validate(d);
 if p_patch ? 'application' and d->>'category'='program' and 'application'=any(machimoa_review.content_filter_missing(d)) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 if not machimoa_review.content_filter_consistent(p_id,p_revision,d) then raise sqlstate 'PT422' using message='content_filter_facts_mismatch';end if;
 if d->>'category' is distinct from machimoa_review.content_filter_category(p_id,p_revision) or f.source_binding is distinct from machimoa_review.content_filter_binding(p_id,p_revision) then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
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
CREATE OR REPLACE FUNCTION machimoa_review.classification_validate(f jsonb, d jsonb)
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare cat text;key text;g jsonb;o jsonb;start_day text;end_day text;
begin
 if f is null or jsonb_typeof(f)<>'object' or (select array_agg(k order by k) from jsonb_object_keys(f) k) is distinct from array['category','deadlineKind','deadlineOn','delivery','eventEnd','eventStart','evidence','foreignEligibility','productType','regions','scope'] then raise sqlstate 'PT422' using message='classification_invalid_facts';end if;
 foreach key in array array['category','deadlineKind','deadlineOn','delivery','eventEnd','eventStart','evidence','foreignEligibility','productType','scope'] loop
 if jsonb_typeof(f->key)<>'string' or f->>key ~ '[<>]' then raise sqlstate 'PT422' using message='classification_invalid_text';end if;end loop;
 cat:=f->>'category';
 if cat not in ('policy','program','event','youth_space','living') or f->>'productType' not in ('event_program','policy_reference','living_guide') or f->>'delivery' not in ('online','offline','hybrid') or f->>'scope' not in ('nationwide','specific','unknown') or f->>'foreignEligibility' not in ('eligible','ineligible','unknown') or char_length(f->>'evidence')>500 then raise sqlstate 'PT422' using message='classification_missing_facts';end if;
 if jsonb_typeof(f->'regions')<>'array' or jsonb_array_length(f->'regions')>17 or exists(select 1 from jsonb_array_elements(f->'regions') v where jsonb_typeof(v)<>'string' or v#>>'{}' not in ('11','26','27','28','29','30','31','36','41','42','43','44','45','46','47','48','50')) or (select count(distinct v) from jsonb_array_elements(f->'regions') v)<>jsonb_array_length(f->'regions') then raise sqlstate 'PT422' using message='classification_invalid_regions';end if;
 if f->>'scope'<>'specific' and jsonb_array_length(f->'regions')<>0 or f->>'scope'='specific' and jsonb_array_length(f->'regions')=0 then raise sqlstate 'PT422' using message='classification_invalid_regions';end if;
 if f->>'productType'<>'living_guide' and (f->>'scope'='unknown' or char_length(btrim(f->>'evidence'))=0) or f->>'productType'='policy_reference' and f->>'foreignEligibility'='unknown' then raise sqlstate 'PT422' using message='classification_missing_evidence';end if;
 g:=machimoa_review.classification_gate(f);perform machimoa_review.validate_gate_facts(f->>'productType',g);
 if cat='program' and f->>'deadlineKind' is distinct from 'fixed' then raise sqlstate 'PT422' using message='classification_invalid_dates';end if;
 if cat in ('policy','program') then
 if f->>'deadlineKind' not in ('fixed','none','closed') or f->>'eventStart'<>'' or f->>'eventEnd'<>'' then raise sqlstate 'PT422' using message='classification_invalid_dates';end if;
 if f->>'deadlineKind'='fixed' then perform machimoa_review.content_filter_day(f->>'deadlineOn');elsif f->>'deadlineOn'<>'' then raise sqlstate 'PT422' using message='classification_invalid_dates';end if;
 elsif cat='event' then
 perform machimoa_review.content_filter_day(f->>'eventStart');perform machimoa_review.content_filter_day(f->>'eventEnd');
 if f->>'eventStart'>f->>'eventEnd' or f->>'deadlineKind'<>'' or f->>'deadlineOn'<>'' then raise sqlstate 'PT422' using message='classification_invalid_dates';end if;
 elsif f->>'deadlineKind'<>'' or f->>'deadlineOn'<>'' or f->>'eventStart'<>'' or f->>'eventEnd'<>'' then raise sqlstate 'PT422' using message='classification_invalid_dates';end if;
 if cat in ('program','event','youth_space') then
 perform machimoa_review.content_filter_validate(d);
 if d->>'category' is distinct from cat or cardinality(machimoa_review.classification_filter_missing(d))<>0 then raise sqlstate 'PT422' using message='classification_missing_filters';end if;
 if cat='program' then
 if d->'delivery'->>'value' is distinct from (case f->>'delivery' when 'offline' then 'onsite' when 'hybrid' then 'mixed' else 'online' end) or
 d->'application'->'value'->>'deadlineKind' is distinct from (case when f->>'deadlineKind'='closed' then 'none' else f->>'deadlineKind' end) or
 f->>'deadlineKind'='fixed' and left(d->'application'->'value'->'end'->>'value',10) is distinct from f->>'deadlineOn' or
 f->>'deadlineKind'='closed' and d->'application'->'value'->>'sourceStatus'<>'closed' then raise sqlstate 'PT422' using message='classification_inconsistent_filters';end if;
 end if;
 if cat='event' then
 if f->>'delivery'='online' then raise sqlstate 'PT422' using message='classification_event_venue_required';end if;
 for o in select value from jsonb_array_elements(d->'schedule'->'value'->'occurrences') loop
 start_day:=left(o->'start'->>'value',10);end_day:=left(o->'end'->>'value',10);
 if start_day<f->>'eventStart' or end_day>f->>'eventEnd' then raise sqlstate 'PT422' using message='classification_schedule_outside_period';end if;end loop;
 end if;
 elsif d is not null then raise sqlstate 'PT422' using message='classification_unexpected_filters';end if;
end $function$
;
CREATE OR REPLACE FUNCTION public.admin_review_classification_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype;c machimoa_review.review_classifications%rowtype;f jsonb;d jsonb;v text;reasons text[];editable boolean;requested_id uuid:=p_id;pub jsonb;
begin
 p_id:=machimoa_review.classification_source(p_id);
 select * into s from machimoa_review.source_items where id=p_id;if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 select * into c from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=s.revision_hash;
 f:=coalesce(c.facts,machimoa_review.classification_initial(p_id));
 if c.source_item_id is not null then d:=c.filters;else d:=machimoa_review.content_filter_info(p_id,s.revision_hash)->'data';if f->>'category' not in ('program','event','youth_space') then d:=null;end if;end if;
 pub:=machimoa_review.classification_publication(p_id);
 v:=encode(sha256(convert_to(jsonb_build_array(machimoa_review.admin_review_snapshot('facts',p_id),to_jsonb(c),pub)::text,'UTF8')),'hex');
 reasons:=case when c.source_item_id is null then '{}'::text[] when c.native_snapshot<>machimoa_review.classification_native(p_id) then array['classification_input_changed'] else '{}'::text[] end;
 if f->>'category'='program' and (f->>'deadlineKind' is distinct from 'fixed' or d is null or 'application'=any(machimoa_review.classification_filter_missing(d))) then reasons:=array_append(reasons,'content_filter:application');end if;
 editable:=not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') and
 not exists(select 1 from machimoa_review.source_item_program_facts pf where pf.source_item_id=p_id and pf.revision_hash=s.revision_hash and pf.manual_excluded) and
 s.disposition not in ('non_target','excluded','outside_scope') and not machimoa_review.admin_trash_pending(p_id,s.revision_hash);
 return jsonb_build_object('id',requested_id,'publication',pub,'revision',s.revision_hash,'version',v,'classificationVersion',coalesce(c.classification_version,0),'active',c.source_item_id is not null,
 'category',f->>'category','facts',f,'filters',d,'note',coalesce(c.note,''),'editable',editable,'ready',machimoa_review.classification_ready(p_id),'reasons',to_jsonb(reasons),'sourceReasons',to_jsonb(array(select distinct code from unnest(machimoa_review.classification_reasons(p_id,f)||array(select unnest(j.reason_codes) from machimoa_review.processing_jobs j where j.source_item_id=p_id and j.revision_hash=s.revision_hash and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed'))) code)));
end $function$
;
notify pgrst,'reload schema';
commit;
