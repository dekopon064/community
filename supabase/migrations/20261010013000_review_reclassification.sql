-- Explicit administrator classification. No source discovery, provider execution,
-- automatic publication, existing-row conversion or scheduler changes.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $$ declare r record;begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.admin_review_snapshot(text,uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.admin_review_snapshot(text,uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'860df47334068c224b6c4cefda7f680e8f4e3dc9c3d3dfcbd05c1791ac21a6c5' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.admin_review_snapshot(text,uuid)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.admin_review_snapshot(text,uuid)';end if;
if to_regprocedure('machimoa_review.content_filter_category(uuid,text)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_category(uuid,text)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'1de8078fbe415b1a90c54c332ad51a70d5d27bcc73ec1ce52cd1c6047611acd2' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_category(uuid,text)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.content_filter_category(uuid,text)';end if;
if to_regprocedure('machimoa_review.content_filter_info(uuid,text)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_info(uuid,text)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'51e537ce4d512f3b76b265eaeb5b61cbb8d5f9c0f62033fd349f7adf6e15bf79' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_info(uuid,text)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.content_filter_info(uuid,text)';end if;
if to_regprocedure('machimoa_review.content_filter_ready(uuid,text)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_ready(uuid,text)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'c79fe481fa6f248805e78bdb810a26d886930c668f440756c834983f79ad6ede' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_ready(uuid,text)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.content_filter_ready(uuid,text)';end if;
if to_regprocedure('machimoa_review.program_candidate_guard(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.program_candidate_guard(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'5060c019ae25b26f73ca05ee087b7c5cfd11cb5005f10fae1ca0537868514c90' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.program_candidate_guard(uuid)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.program_candidate_guard(uuid)';end if;
if to_regprocedure('machimoa_review.program_candidate_info(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.program_candidate_info(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'b8f363a2fcf3da18f6d28a0a806d6a13e13365425db6bd4389f1ff2baaf6774f' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.program_candidate_info(uuid)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.program_candidate_info(uuid)';end if;
if to_regprocedure('machimoa_review.content_filter_candidate_info(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_candidate_info(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'3257a19deadf793535b50dcc4f24732779d3ca1048b7557f1d7cfdb91e930088' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_candidate_info(uuid)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.content_filter_candidate_info(uuid)';end if;
if to_regprocedure('machimoa_review.content_filter_candidate_approve(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_candidate_approve(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'03d10a6b938630324f942863ae3f59c06c5dada47aacd38d07ccd291b8fe3e3c' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_candidate_approve(uuid)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.content_filter_candidate_approve(uuid)';end if;
if to_regprocedure('machimoa_review.content_filter_publish(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.content_filter_publish(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'eaace413b40bd8ce98b11c1d1f6abc1abce3e159238308eb153cd87608c0bade' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.content_filter_publish(uuid)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.content_filter_publish(uuid)';end if;
if to_regprocedure('machimoa_review.publish_curation_candidate(uuid,text,text,boolean)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.publish_curation_candidate(uuid,text,text,boolean)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'cb450b8998eee4ff24a4cdb4c910adf09f86ac5998340d61fe6e15a7eb36c27e' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.publish_curation_candidate(uuid,text,text,boolean)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.publish_curation_candidate(uuid,text,text,boolean)';end if;
if to_regprocedure('public.admin_myseoul_program_detail(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('public.admin_myseoul_program_detail(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'b618f15da2770f6459f0b48cfc8d5261031b89d6c16ce48268c9e61be5995360' or (select proacl::text from pg_proc where oid=to_regprocedure('public.admin_myseoul_program_detail(uuid)')) is distinct from '{postgres=X/postgres,service_role=X/postgres}' then raise exception 'classification_predecessor_changed: %','public.admin_myseoul_program_detail(uuid)';end if;
if to_regprocedure('public.admin_program_detail(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('public.admin_program_detail(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'a8bd37e0246f1af7f1c3516ea708c211d0eb5a875620787022dfcc1ab75ad46f' or (select proacl::text from pg_proc where oid=to_regprocedure('public.admin_program_detail(uuid)')) is distinct from '{postgres=X/postgres,service_role=X/postgres}' then raise exception 'classification_predecessor_changed: %','public.admin_program_detail(uuid)';end if;
if to_regprocedure('machimoa_review.claim_processing_jobs(text,integer,text,integer)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.claim_processing_jobs(text,integer,text,integer)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'c731b72b2c0455de8b45ca77e8bf6be3f92c967c1a03a7a44a9e378c313ab377' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.claim_processing_jobs(text,integer,text,integer)')) is distinct from '{postgres=X/postgres}' then raise exception 'classification_predecessor_changed: %','machimoa_review.claim_processing_jobs(text,integer,text,integer)';end if;
for r in select p.oid from pg_proc p where p.oid in (select to_regprocedure(name) from unnest(array['machimoa_review.admin_review_snapshot(text,uuid)','machimoa_review.content_filter_category(uuid,text)','machimoa_review.content_filter_info(uuid,text)','machimoa_review.content_filter_ready(uuid,text)','machimoa_review.program_candidate_guard(uuid)','machimoa_review.program_candidate_info(uuid)','machimoa_review.content_filter_candidate_info(uuid)','machimoa_review.content_filter_candidate_approve(uuid)','machimoa_review.content_filter_publish(uuid)','machimoa_review.publish_curation_candidate(uuid,text,text,boolean)','public.admin_myseoul_program_detail(uuid)','public.admin_program_detail(uuid)','machimoa_review.claim_processing_jobs(text,integer,text,integer)']) name) loop if (select pg_get_userbyid(proowner) from pg_proc where oid=r.oid)<>'postgres' then raise exception 'classification_predecessor_owner_changed';end if;end loop;
if to_regclass('machimoa_review.review_classifications') is not null then raise exception 'classification_already_installed';end if;end $$;
create table machimoa_review.classification_function_backup(name text primary key,definition text not null,acl text,base_name text);


create table machimoa_review.review_classifications(
 source_item_id uuid not null references machimoa_review.source_items(id),revision_hash text not null,
 classification_version bigint not null check(classification_version>0),facts jsonb not null,filters jsonb,
 native_snapshot text not null check(native_snapshot ~ '^[a-f0-9]{64}$'),note text not null,
 actor uuid not null,confirmed_at timestamptz not null default clock_timestamp(),
 primary key(source_item_id,revision_hash));
create table machimoa_review.review_classification_history(
 source_item_id uuid not null,revision_hash text not null,classification_version bigint not null,
 previous jsonb,current jsonb not null,actor uuid not null,note text not null,at timestamptz not null default clock_timestamp(),
 primary key(source_item_id,revision_hash,classification_version));
create table machimoa_review.review_classification_claims(
 job_id uuid not null,claimed_at timestamptz not null,source_item_id uuid not null,revision_hash text not null,
 classification_version bigint not null,native_snapshot text not null,facts jsonb not null,filters jsonb,
 worker_id text not null,lease_until timestamptz not null,native_facts jsonb not null,primary key(job_id,claimed_at));
create table machimoa_review.review_classification_candidates(
 candidate_id uuid primary key references machimoa_review.curation_candidates(id),source_item_id uuid not null,
 revision_hash text not null,classification_version bigint not null,native_snapshot text not null,
 facts jsonb not null,filters jsonb,job_id uuid not null,claimed_at timestamptz not null);

create table machimoa_review.review_classification_publications(
 source_item_id uuid not null,revision_hash text not null,classification_version bigint not null,
 curation_id uuid not null references public.curations(id),before_version text not null,after_version text not null,
 previous_category text,current_category text not null,actor uuid not null,note text not null,
 applied_at timestamptz not null default clock_timestamp(),primary key(source_item_id,revision_hash,classification_version));

create function machimoa_review.classification_source(p_id uuid) returns uuid
language sql stable set search_path='' as $$
 select coalesce((select id from machimoa_review.source_items where id=p_id),machimoa_review.admin_review_source('candidates',p_id))
$$;
create function machimoa_review.classification_publication(p_id uuid) returns jsonb
language plpgsql stable set search_path='' as $$
declare p public.curations%rowtype;s machimoa_review.source_items%rowtype;c machimoa_review.review_classifications%rowtype;v text;
begin
 select * into s from machimoa_review.source_items where id=p_id;
 if (select count(distinct ca.published_curation_id) from machimoa_review.curation_candidates ca where machimoa_review.canonical_source_id(ca.source)=s.source_id and ca.source_item_id=s.external_key and ca.review_status='published')>1 then raise sqlstate 'PT409' using message='classification_multiple_publications';end if;
 select cu.* into p from public.curations cu where cu.is_published and cu.id in (select ca.published_curation_id from machimoa_review.curation_candidates ca where machimoa_review.canonical_source_id(ca.source)=s.source_id and ca.source_item_id=s.external_key and ca.review_status='published');
 if p.id is null then return null;end if;
 select * into c from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=s.revision_hash;
 v:=encode(sha256(convert_to(to_jsonb(p)::text,'UTF8')),'hex');
 return jsonb_build_object('version',v,'category',coalesce(p.user_category,p.category),'content',jsonb_build_object('titleKo',coalesce(p.title_ko,p.title),'summaryKo',coalesce(p.summary_ko,p.summary),'contentKo',coalesce(p.content_ko,p.content),'titleJa',p.title_ja,'summaryJa',p.summary_ja,'contentJa',p.content_ja),'applied',exists(select 1 from machimoa_review.review_classification_publications a where a.source_item_id=p_id and a.revision_hash=s.revision_hash and a.classification_version=c.classification_version and a.curation_id=p.id and a.after_version=v));
end $$;

create function machimoa_review.classification_native(p_id uuid) returns text
language sql stable set search_path='' as $$
 select encode(sha256(convert_to(jsonb_build_array(jsonb_build_object('id',s.id,'source',s.source_id,'key',s.external_key,'revision',s.revision_hash,'payload',s.normalized_payload,'min',s.min_fields,'bodyUsable',s.body_usable,'hasUrl',s.has_source_url,'attachment',s.attachment_present),to_jsonb(f),to_jsonb(pt),to_jsonb(uc),to_jsonb(ad),to_jsonb(ep),to_jsonb(cf))::text,'UTF8')),'hex')
 from machimoa_review.source_items s
 left join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
 left join machimoa_review.source_item_product_types pt on pt.source_item_id=s.id and pt.revision_hash=s.revision_hash
 left join machimoa_review.source_item_user_categories uc on uc.source_item_id=s.id and uc.revision_hash=s.revision_hash
 left join machimoa_review.source_item_application_deadlines ad on ad.source_item_id=s.id and ad.revision_hash=s.revision_hash
 left join machimoa_review.source_item_event_periods ep on ep.source_item_id=s.id and ep.revision_hash=s.revision_hash
 left join machimoa_review.source_item_content_filters cf on cf.source_item_id=s.id and cf.revision_hash=s.revision_hash
 where s.id=p_id
$$;

create function machimoa_review.classification_initial(p_id uuid) returns jsonb
language plpgsql stable set search_path='' as $$
declare s machimoa_review.source_items%rowtype;f jsonb;g jsonb;cat text;pt text;v jsonb;scope text;regions jsonb;evidence text;dk text;de text;es text;ee text;
begin
 select * into s from machimoa_review.source_items where id=p_id;
 if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 select facts into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash;
 select product_type,gate_facts into pt,g from machimoa_review.source_item_product_types where source_item_id=p_id and revision_hash=s.revision_hash;
 cat:=machimoa_review.content_filter_category(p_id,s.revision_hash);
 if cat not in ('policy','program','event','youth_space','living') or cat is null then cat:='';end if;
 if pt not in ('event_program','policy_reference','living_guide') or pt is null then pt:=case when f is not null then 'event_program' else '' end;end if;
 scope:=coalesce(g->>'eligibility_scope','unknown');regions:=coalesce(g->'eligibility_region_codes','[]');evidence:=coalesce(g->>'eligibility_region_evidence','');
 if f is not null then
 scope:=case f->>'residence_scope' when 'nationwide' then 'nationwide' when 'capital' then 'specific' when 'includes_capital' then 'specific' else 'unknown' end;
 regions:=case when scope='specific' then '["11","28","41"]'::jsonb else '[]'::jsonb end;
 evidence:=left(coalesce((select string_agg(value#>>'{}',E'\n') from jsonb_array_elements(coalesce(f->'residence_evidence','[]'))),''),500);
 end if;
 v:=machimoa_review.content_filter_fact_values(p_id,s.revision_hash);
 if cat in ('policy','program') then
 select application_deadline_kind,application_deadline_on::text into dk,de from machimoa_review.source_item_application_deadlines where source_item_id=p_id and revision_hash=s.revision_hash;
 if v ? 'application' then dk:=v->'application'->>'deadlineKind';de:=v->'application'->'end'->>'value';end if;
 end if;
 if cat='event' then select event_start_on::text,event_end_on::text into es,ee from machimoa_review.source_item_event_periods where source_item_id=p_id and revision_hash=s.revision_hash;end if;
 return jsonb_build_object('productType',pt,'category',cat,'scope',scope,'regions',regions,'evidence',evidence,
 'foreignEligibility',coalesce(g->>'foreign_resident_eligibility','unknown'),'delivery',case coalesce(f->>'delivery_mode',g->>'delivery_mode') when 'mixed' then 'hybrid' when 'hybrid' then 'hybrid' when 'online' then 'online' when 'offline' then 'offline' else 'unknown' end,
 'deadlineKind',coalesce(dk,''),'deadlineOn',case when dk='fixed' then left(coalesce(de,''),10) else '' end,'eventStart',coalesce(es,''),'eventEnd',coalesce(ee,''));
end $$;

create function machimoa_review.classification_gate(f jsonb) returns jsonb
language sql immutable set search_path='' as $$
 select jsonb_build_object('schema_version','gate-facts-v1','delivery_mode',f->>'delivery') ||
 case when f->>'productType'='living_guide' then '{}'::jsonb else jsonb_build_object('eligibility_scope',f->>'scope',
 'eligibility_region_codes',f->'regions','eligibility_region_evidence',f->>'evidence') ||
 case when f->>'productType'='policy_reference' then jsonb_build_object('foreign_resident_eligibility',f->>'foreignEligibility') else '{}'::jsonb end end
$$;

create function machimoa_review.classification_filter_missing(v jsonb) returns text[] language sql immutable set search_path='' as $$select coalesce(array_agg(key order by key),'{}'::text[]) from jsonb_each(v-'schema'-'category') where value->>'status'='unknown'$$;

create function machimoa_review.classification_validate(f jsonb,d jsonb) returns void
language plpgsql set search_path='' as $$
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
end $$;

-- Source-specific eligibility/quality remain authoritative. Only the axes
-- explicitly replaced by confirmed common facts are removed from this result.
create function machimoa_review.classification_reasons(p_id uuid,f jsonb) returns text[]
language plpgsql stable set search_path='' as $$
declare s machimoa_review.source_items%rowtype;pf machimoa_review.source_item_program_facts%rowtype;r jsonb;codes text[];g jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id;
 select * into pf from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash;
 if pf.source_item_id is not null then
 r:=case when s.source_id='myseoul_program' then machimoa_review.myseoul_evaluate(pf.facts,statement_timestamp()) else machimoa_review.program_evaluate(pf.facts,statement_timestamp()) end;
 if pf.manual_excluded or r->>'decision'='out_of_scope' then return array['classification_source_excluded'];end if;
 select array(select code from jsonb_array_elements_text(coalesce(r->'reasons','[]')) code where not (machimoa_review.publication_temporal_ready(r) and code in ('application_not_started','application_closed','operation_ended','not_currently_accepting','program_ended')) and code not in
 ('category_unresolved','delivery_mode_unknown','activity_region_unknown','application_period_unknown','operation_period_unknown','application_state_unknown','online_residence_unknown') and code not like 'content_filter:%') into codes;
 else codes:='{}';end if;
 if f->>'productType' not in ('event_program','policy_reference','living_guide') then return array_append(codes,'classification_missing_facts');end if;
 select to_jsonb(gate) into g from machimoa_review.evaluate_source_item_gates(s.body_usable,s.has_source_url,s.attachment_present,f->>'productType','{}',machimoa_review.classification_gate(f)) gate;
 codes:=codes||array(select code from jsonb_array_elements(coalesce(g->'jobs','[]')) job cross join lateral jsonb_array_elements_text(job->'reason_codes') code);
 if g->>'disposition'<>'target' and cardinality(codes)=0 then codes:=array_append(codes,'classification_scope_unresolved');end if;
 return array(select distinct c from unnest(codes) c);
end $$;

create function machimoa_review.classification_ready(p_id uuid) returns boolean
language sql stable set search_path='' as $$
 select coalesce((select c.native_snapshot=machimoa_review.classification_native(s.id) and cardinality(machimoa_review.classification_reasons(s.id,c.facts))=0 and not machimoa_review.admin_trash_pending(s.id,s.revision_hash) and not exists(select 1 from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed')) and src.enabled and src.permission_status in ('approved_noncommercial','approved_commercial')
 from machimoa_review.review_classifications c join machimoa_review.source_items s on s.id=c.source_item_id and s.revision_hash=c.revision_hash join machimoa_review.ingest_sources src on src.source_id=s.source_id where s.id=p_id),false)
$$;

create function public.admin_review_classification_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
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
 editable:=not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') and
 not exists(select 1 from machimoa_review.source_item_program_facts pf where pf.source_item_id=p_id and pf.revision_hash=s.revision_hash and pf.manual_excluded) and
 s.disposition not in ('non_target','excluded','outside_scope') and not machimoa_review.admin_trash_pending(p_id,s.revision_hash);
 return jsonb_build_object('id',requested_id,'publication',pub,'revision',s.revision_hash,'version',v,'classificationVersion',coalesce(c.classification_version,0),'active',c.source_item_id is not null,
 'category',f->>'category','facts',f,'filters',d,'note',coalesce(c.note,''),'editable',editable,'ready',machimoa_review.classification_ready(p_id),'reasons',to_jsonb(reasons),'sourceReasons',to_jsonb(array(select distinct code from unnest(machimoa_review.classification_reasons(p_id,f)||array(select unnest(j.reason_codes) from machimoa_review.processing_jobs j where j.source_item_id=p_id and j.revision_hash=s.revision_hash and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed'))) code)));
end $$;

create function public.admin_review_reclassify(p_id uuid,p_revision text,p_version text,p_classification_version bigint,p_facts jsonb,p_filters jsonb,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;before_row jsonb;item jsonb;v bigint;codes text[];requested_id uuid:=p_id;
begin
 p_id:=machimoa_review.classification_source(p_id);
 if p_actor is null or p_note is null or char_length(btrim(p_note)) not between 10 and 4000 then raise sqlstate 'PT422' using message='classification_invalid_command';end if;
 select * into s from machimoa_review.source_items where id=p_id for update;if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by id for update;
 item:=public.admin_review_classification_detail(p_id);
 if s.revision_hash is distinct from p_revision or item->>'version' is distinct from p_version or (item->>'classificationVersion')::bigint is distinct from p_classification_version or not (item->>'editable')::boolean then raise sqlstate 'PT409' using message='classification_conflict';end if;
 perform machimoa_review.classification_validate(p_facts,p_filters);
 select to_jsonb(c) into before_row from machimoa_review.review_classifications c where source_item_id=p_id and revision_hash=p_revision;
 v:=p_classification_version+1;
 insert into machimoa_review.review_classifications(source_item_id,revision_hash,classification_version,facts,filters,native_snapshot,note,actor)
 values(p_id,p_revision,v,p_facts,p_filters,machimoa_review.classification_native(p_id),btrim(p_note),p_actor)
 on conflict(source_item_id,revision_hash) do update set classification_version=v,facts=p_facts,filters=p_filters,native_snapshot=excluded.native_snapshot,note=excluded.note,actor=p_actor,confirmed_at=clock_timestamp();
 insert into machimoa_review.review_classification_history(source_item_id,revision_hash,classification_version,previous,current,actor,note)
 select p_id,p_revision,v,before_row,to_jsonb(c),p_actor,btrim(p_note) from machimoa_review.review_classifications c where source_item_id=p_id and revision_hash=p_revision;
 codes:=machimoa_review.classification_reasons(p_id,p_facts);
 update machimoa_review.curation_candidates ca set review_status='superseded',superseded_at=clock_timestamp() where machimoa_review.canonical_source_id(ca.source)=s.source_id and ca.source_item_id=s.external_key and ca.review_status='pending';
 update machimoa_review.processing_jobs set status='cancelled',error_code='classification_input_changed' where source_item_id=p_id and processing_stage='ai_enrichment' and status in ('queued','failed','completed');
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at)
 values(p_id,p_revision,'content_review',case when cardinality(codes)=0 then 'completed' else 'queued' end,codes,clock_timestamp(),clock_timestamp())
 on conflict(source_item_id,revision_hash,processing_stage) do update set status=excluded.status,reason_codes=codes,completed_at=case when cardinality(codes)=0 then clock_timestamp() else null end;
 -- Re-evaluate only the stages this explicit common fact contract can resolve.
 -- Unrelated relationship/content reasons remain pending and block readiness.
 update machimoa_review.processing_jobs set status='completed',completed_at=clock_timestamp(),reason_codes='{}'
 where source_item_id=p_id and revision_hash=p_revision and processing_stage in ('product_type_review','region_review','relevance_review') and status in ('queued','failed') and cardinality(codes)=0;
 -- An explicit target claim RPC creates the subsequent job; saving runs no AI.
 return public.admin_review_classification_detail(requested_id);
end $$;

-- A saved reclassification never changes the existing public row. Only this
-- explicit, fenced administrator action updates its projection and reviewed text.
create function public.admin_review_apply_public_classification(p_id uuid,p_revision text,p_version text,p_classification_version bigint,p_publication_version text,p_content jsonb,p_body_reviewed boolean,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare requested_id uuid:=p_id;s machimoa_review.source_items%rowtype;c machimoa_review.review_classifications%rowtype;p public.curations%rowtype;item jsonb;before_pub jsonb;after_pub jsonb;k text;
begin
 if p_actor is null or p_body_reviewed is distinct from true or p_note is null or char_length(btrim(p_note)) not between 10 and 4000 then raise sqlstate 'PT422' using message='classification_invalid_command';end if;
 p_id:=machimoa_review.classification_source(p_id);
 select * into s from machimoa_review.source_items where id=p_id for update;if s.id is null then raise sqlstate 'PT404' using message='review_not_found';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by id for update;
 select * into c from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=s.revision_hash for update;
 select cu.* into p from public.curations cu where cu.is_published and cu.id in (select ca.published_curation_id from machimoa_review.curation_candidates ca where machimoa_review.canonical_source_id(ca.source)=s.source_id and ca.source_item_id=s.external_key and ca.review_status='published') for update;
 item:=public.admin_review_classification_detail(p_id);before_pub:=item->'publication';
 if c.source_item_id is null or p.id is null or s.revision_hash is distinct from p_revision or item->>'version' is distinct from p_version or c.classification_version is distinct from p_classification_version or before_pub->>'version' is distinct from p_publication_version or not (item->>'editable')::boolean or not (item->>'ready')::boolean or exists(select 1 from machimoa_review.review_classification_publications a where a.source_item_id=p_id and a.revision_hash=p_revision and a.classification_version=p_classification_version) then raise sqlstate 'PT409' using message='classification_publication_conflict';end if;
 if p_content is null or jsonb_typeof(p_content)<>'object' or (select array_agg(key order by key) from jsonb_object_keys(p_content) q(key)) is distinct from array['contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 for k in select jsonb_object_keys(p_content) loop if jsonb_typeof(p_content->k)<>'string' or char_length(btrim(p_content->>k)) not between 1 and (case when k like 'title%' then 300 when k like 'summary%' then 1000 else 200000 end) then raise sqlstate 'PT422' using message='review_invalid_input';end if;end loop;
 -- Update in place: no new content ID/slug, account record, saved row or comment.
 update public.curations set category=c.facts->>'category',user_category=c.facts->>'category',content_filters=c.filters,
 application_deadline_kind=nullif(c.facts->>'deadlineKind',''),application_deadline_on=nullif(c.facts->>'deadlineOn','')::date,event_start_on=nullif(c.facts->>'eventStart','')::date,event_end_on=nullif(c.facts->>'eventEnd','')::date,
 title=p_content->>'titleKo',summary=p_content->>'summaryKo',content=p_content->>'contentKo',title_ko=p_content->>'titleKo',summary_ko=p_content->>'summaryKo',content_ko=p_content->>'contentKo',title_ja=p_content->>'titleJa',summary_ja=p_content->>'summaryJa',content_ja=p_content->>'contentJa',updated_at=clock_timestamp() where id=p.id;
 after_pub:=machimoa_review.classification_publication(p_id);
 insert into machimoa_review.review_classification_publications values(p_id,p_revision,p_classification_version,p.id,before_pub->>'version',after_pub->>'version',before_pub->>'category',c.facts->>'category',p_actor,btrim(p_note),clock_timestamp());
 return public.admin_review_classification_detail(requested_id);
end $$;

create function machimoa_review.classification_claim_guard() returns trigger
language plpgsql set search_path='' as $$
begin
 if new.status='claimed' and new.processing_stage='ai_enrichment' and exists(select 1 from machimoa_review.review_classifications where source_item_id=new.source_item_id and revision_hash=new.revision_hash) and current_setting('machimoa.classification_claim',true) is distinct from new.id::text then
 raise sqlstate 'PT409' using message='classification_targeted_claim_required';end if;
 return new;
end $$;
create trigger classification_claim_guard before insert or update on machimoa_review.processing_jobs for each row execute function machimoa_review.classification_claim_guard();

create function public.claim_reclassified_content_ai(p_id uuid,p_revision text,p_classification_version bigint,p_worker_id text,p_lease_seconds integer default 300) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;c machimoa_review.review_classifications%rowtype;j machimoa_review.processing_jobs%rowtype;
begin
 if p_worker_id is null or char_length(p_worker_id) not between 1 and 100 or p_lease_seconds is null or p_lease_seconds not between 30 and 600 then raise sqlstate 'PT422' using message='classification_invalid_claim';end if;
 select * into s from machimoa_review.source_items where id=p_id for update;
 select * into c from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision for share;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by id for update;
 if s.id is null or c.source_item_id is null or s.revision_hash is distinct from p_revision or c.classification_version is distinct from p_classification_version or not machimoa_review.classification_ready(p_id) or not (public.admin_review_classification_detail(p_id)->>'editable')::boolean or exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) then raise sqlstate 'PT409' using message='classification_not_ready';end if;
 select * into j from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='ai_enrichment' for update;
 if j.id is not null and (j.status='claimed' or j.status='completed') then raise sqlstate 'PT409' using message='classification_already_processed';end if;
 if j.id is null then
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at) values(p_id,p_revision,'ai_enrichment','queued','{}',clock_timestamp(),clock_timestamp()) returning * into j;
 end if;
 perform set_config('machimoa.classification_claim',j.id::text,true);
 update machimoa_review.processing_jobs set status='claimed',claimed_at=clock_timestamp(),claim_lease_until=clock_timestamp()+make_interval(secs=>p_lease_seconds),claimed_by=p_worker_id,completed_at=null,error_code=null where id=j.id returning * into j;
 insert into machimoa_review.review_classification_claims values(j.id,j.claimed_at,p_id,p_revision,c.classification_version,c.native_snapshot,c.facts,c.filters,p_worker_id,j.claim_lease_until,jsonb_build_object('programFacts',(select facts from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision),'gateFacts',(select gate_facts from machimoa_review.source_item_product_types where source_item_id=p_id and revision_hash=p_revision)));
 return jsonb_build_object('schema','review-classification-ai-v1','jobId',j.id,'sourceItemId',p_id,'revision',p_revision,'classificationVersion',c.classification_version,'workerId',p_worker_id,'claimedAt',j.claimed_at,'leaseUntil',j.claim_lease_until,'source',s.source_id,'externalKey',s.external_key,'sourceUrl',coalesce(s.min_fields->>'source_url',s.normalized_payload->>'source_url'),'title',coalesce(s.min_fields->>'title',s.normalized_payload->>'plcyNm',s.normalized_payload->>'pstTtl'),'body',left(coalesce(s.normalized_payload->>'plain_text',''),200000),'facts',c.facts,'filters',c.filters,'nativeConfirmedFacts',(select native_facts from machimoa_review.review_classification_claims where job_id=j.id and claimed_at=j.claimed_at));
end $$;

create function public.reclassified_content_ai_status(p_job_id uuid,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_classification_version bigint,p_close_expired boolean default false) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;j machimoa_review.processing_jobs%rowtype;m machimoa_review.review_classification_claims%rowtype;cid uuid;state text;
begin
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs job on job.source_item_id=si.id where job.id=p_job_id for update of si;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 select * into m from machimoa_review.review_classification_claims where job_id=p_job_id and claimed_at=p_claimed_at;
 if s.id is null or m.job_id is null or m.lease_until is distinct from p_lease_until or m.worker_id is distinct from p_worker_id or m.classification_version is distinct from p_classification_version or p_close_expired is null then raise sqlstate 'PT409' using message='classification_fence_lost';end if;
 select candidate_id into cid from machimoa_review.review_classification_candidates where job_id=p_job_id and claimed_at=p_claimed_at;
 if cid is not null then state:='completed';
 elsif j.claimed_at is distinct from p_claimed_at or j.claim_lease_until is distinct from p_lease_until or j.claimed_by is distinct from p_worker_id then state:='superseded';
 elsif j.status<>'claimed' then state:='closed';
 elsif j.claim_lease_until>clock_timestamp() then state:='active';
 elsif not p_close_expired then state:='expired';
 else update machimoa_review.processing_jobs set status='failed',error_code='classification_expired_attempt_closed',completed_at=clock_timestamp() where id=p_job_id;state:='expired_closed';end if;
 return jsonb_build_object('status',state,'candidateId',cid);
end $$;

create function machimoa_review.classification_candidate_guard(p_id uuid) returns void
language plpgsql set search_path='' as $$
declare m machimoa_review.review_classification_candidates%rowtype;s machimoa_review.source_items%rowtype;c machimoa_review.review_classifications%rowtype;
begin
 select si.* into s from machimoa_review.source_items si join machimoa_review.curation_candidates ca on machimoa_review.canonical_source_id(ca.source)=si.source_id and ca.source_item_id=si.external_key where ca.id=p_id for update of si;
 select * into c from machimoa_review.review_classifications where source_item_id=s.id and revision_hash=s.revision_hash;
 select * into m from machimoa_review.review_classification_candidates where candidate_id=p_id;
 if c.source_item_id is null and m.candidate_id is null then return;end if;
 if m.candidate_id is null or c.source_item_id is null or m.revision_hash is distinct from s.revision_hash or m.classification_version is distinct from c.classification_version or m.native_snapshot is distinct from c.native_snapshot or not machimoa_review.classification_ready(s.id) then raise sqlstate 'PT409' using message='classification_candidate_input_changed';end if;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed') then raise sqlstate 'PT409' using message='classification_processing_active';end if;
end $$;

create function machimoa_review.classification_candidate_update() returns trigger
language plpgsql set search_path='' as $$
begin
 if new.review_status in ('published','pending') and current_setting('machimoa.classification_finish',true) is distinct from new.source_item_id then perform machimoa_review.classification_candidate_guard(new.id);end if;
 return new;
end $$;
create trigger classification_candidate_update before update on machimoa_review.curation_candidates for each row execute function machimoa_review.classification_candidate_update();

create function public.finish_reclassified_content_ai(p_job_id uuid,p_revision text,p_classification_version bigint,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_output jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;j machimoa_review.processing_jobs%rowtype;m machimoa_review.review_classification_claims%rowtype;c machimoa_review.review_classifications%rowtype;r record;src text;slug text;k text;payload jsonb;
begin
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs job on job.source_item_id=si.id where job.id=p_job_id for update of si;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 select * into m from machimoa_review.review_classification_claims where job_id=p_job_id and claimed_at=p_claimed_at;
 select * into c from machimoa_review.review_classifications where source_item_id=s.id and revision_hash=p_revision for share;
 if exists(select 1 from machimoa_review.review_classification_candidates cm join machimoa_review.curation_candidates ca on ca.id=cm.candidate_id where cm.job_id=p_job_id and cm.claimed_at=p_claimed_at and cm.classification_version=p_classification_version and cm.revision_hash=p_revision and m.worker_id=p_worker_id and m.lease_until=p_lease_until and ca.title_ko=p_output->>'titleKo' and ca.content_ko=p_output->>'contentKo' and ca.summary_ko=p_output->>'summaryKo' and ca.title_ja=p_output->>'titleJa' and ca.content_ja=p_output->>'contentJa' and ca.summary_ja=p_output->>'summaryJa' and ca.ai_model=p_output->>'aiModel') then
 return jsonb_build_object('candidateId',(select candidate_id from machimoa_review.review_classification_candidates where job_id=p_job_id and claimed_at=p_claimed_at),'outcome','duplicate');end if;
 if s.id is null or j.processing_stage<>'ai_enrichment' or j.status<>'claimed' or s.revision_hash is distinct from p_revision or j.revision_hash is distinct from p_revision or j.claimed_at is distinct from p_claimed_at or j.claim_lease_until is distinct from p_lease_until or j.claimed_by is distinct from p_worker_id or j.claim_lease_until<=clock_timestamp() or m.job_id is null or m.worker_id is distinct from p_worker_id or m.lease_until is distinct from p_lease_until or m.classification_version is distinct from p_classification_version or c.classification_version is distinct from p_classification_version or c.native_snapshot is distinct from m.native_snapshot or not machimoa_review.classification_ready(s.id) then raise sqlstate 'PT409' using message='classification_fence_lost';end if;
 if p_output is null or jsonb_typeof(p_output)<>'object' or (select array_agg(key order by key) from jsonb_object_keys(p_output) q(key)) is distinct from array['aiModel','contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 for k in select jsonb_object_keys(p_output) loop if jsonb_typeof(p_output->k)<>'string' or char_length(btrim(p_output->>k)) not between 1 and (case when k like 'title%' then 300 when k like 'summary%' then 1000 when k='aiModel' then 100 else 200000 end) then raise sqlstate 'PT422' using message='review_invalid_input';end if;end loop;
 select legacy_curation_source into src from machimoa_review.ingest_sources where source_id=s.source_id;
 -- Keep the canonical source identity and the existing source's stable slug.
 slug:=case when s.source_id in ('myseoul_program','seoul_reservation') then (case when s.source_id='myseoul_program' then 'myseoul-' else 'seoul-' end)||substr(encode(sha256(convert_to(s.external_key,'UTF8')),'hex'),1,32) else (case when s.source_id='youthcenter_policy' then 'policy-' else 'content-' end)||replace(s.external_key,':','-') end;
 select coalesce(jsonb_object_agg(key,value),'{}') into payload from jsonb_each(s.normalized_payload) where lower(key) not in ('atchfile','atch_file','facts','content_filter_context','filterfacts');
 perform set_config('machimoa.classification_finish',s.external_key,true);
 -- Source revision is immutable. Each explicitly processed classification version
 -- gets a new candidate revision_seq; never fake a source revision to bypass dedupe.
 perform pg_advisory_xact_lock(hashtextextended(src||':'||s.external_key,0));
 if exists(select 1 from machimoa_review.review_classification_candidates where source_item_id=s.id and revision_hash=p_revision and classification_version=c.classification_version) then raise sqlstate 'PT409' using message='classification_candidate_exists';end if;
 if exists(select 1 from machimoa_review.curation_candidates where source=src and source_item_id=s.external_key and review_status='pending') then raise sqlstate 'PT409' using message='classification_pending_candidate';end if;
 if octet_length(payload::text)>65536 then raise sqlstate 'PT422' using message='classification_payload_too_large';end if;
 insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,category,user_category,title,summary,content,source_url,raw_payload,ai_status,ai_model,title_ko,summary_ko,content_ko,ai_status_ko,title_ja,summary_ja,content_ja,ai_status_ja,application_deadline_kind,application_deadline_on,event_start_on,event_end_on)
 values(src,s.external_key,p_revision,slug,c.facts->>'category',c.facts->>'category',p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo',coalesce(s.min_fields->>'source_url',s.normalized_payload->>'source_url'),payload,'success',p_output->>'aiModel',p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',p_output->>'titleJa',p_output->>'summaryJa',p_output->>'contentJa','success',nullif(c.facts->>'deadlineKind',''),nullif(c.facts->>'deadlineOn','')::date,nullif(c.facts->>'eventStart','')::date,nullif(c.facts->>'eventEnd','')::date) returning id as candidate_id into r;
 insert into machimoa_review.review_classification_candidates values(r.candidate_id,s.id,p_revision,c.classification_version,c.native_snapshot,c.facts,c.filters,j.id,j.claimed_at);
 perform machimoa_review.complete_processing_job(j.id,p_worker_id);
 return jsonb_build_object('candidateId',r.candidate_id,'outcome','inserted');
end $$;

insert into machimoa_review.classification_function_backup values('machimoa_review.admin_review_snapshot(text,uuid)','CREATE OR REPLACE FUNCTION machimoa_review.admin_review_snapshot(p_kind text, p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''''
AS $function$
begin
 return machimoa_review.cf_base_admin_review_snapshot(p_kind,p_id)||jsonb_build_object(''contentFilter'',case when p_kind=''facts'' then
 (select to_jsonb(f) from machimoa_review.source_item_content_filters f join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash where s.id=p_id)
 else (select jsonb_build_array(to_jsonb(m),to_jsonb(f)) from machimoa_review.candidate_content_filters m left join machimoa_review.source_item_content_filters f on f.source_item_id=m.source_item_id and f.revision_hash=m.revision_hash where m.candidate_id=p_id) end);
end
$function$
','{postgres=X/postgres}','machimoa_review.cl_base_admin_review_snapshot(text,uuid)');
alter function machimoa_review.admin_review_snapshot(text,uuid) rename to cl_base_admin_review_snapshot;
revoke all on function machimoa_review.cl_base_admin_review_snapshot(text,uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.admin_review_snapshot(p_kind text, p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin return machimoa_review.cl_base_admin_review_snapshot(p_kind,p_id)||jsonb_build_object('classification',(select to_jsonb(c) from machimoa_review.review_classifications c join machimoa_review.source_items s on s.id=c.source_item_id and s.revision_hash=c.revision_hash where s.id=machimoa_review.admin_review_source(p_kind,p_id)));end
$function$;
revoke all on function machimoa_review.admin_review_snapshot(text,uuid) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.content_filter_category(uuid,text)','CREATE OR REPLACE FUNCTION machimoa_review.content_filter_category(p_id uuid, p_revision text)
 RETURNS text
 LANGUAGE sql
 STABLE
 SET search_path TO ''''
AS $function$
 select coalesce(f.facts->>''public_category'',case when s.source_id=''seoul_reservation'' then ''program'' end,c.user_category)
 from machimoa_review.source_items s left join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
 left join machimoa_review.source_item_user_categories c on c.source_item_id=s.id and c.revision_hash=s.revision_hash
 where s.id=p_id and s.revision_hash=p_revision
$function$
','{postgres=X/postgres}','machimoa_review.cl_base_content_filter_category(uuid,text)');
alter function machimoa_review.content_filter_category(uuid,text) rename to cl_base_content_filter_category;
revoke all on function machimoa_review.cl_base_content_filter_category(uuid,text) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_category(p_id uuid, p_revision text)
 RETURNS text
 LANGUAGE plpgsql
 STABLE
 SET search_path TO ''
AS $function$
declare c jsonb;begin select facts into c from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision;if found then return c->>'category';end if;return machimoa_review.cl_base_content_filter_category(p_id,p_revision);end
$function$;
revoke all on function machimoa_review.content_filter_category(uuid,text) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.content_filter_info(uuid,text)','CREATE OR REPLACE FUNCTION machimoa_review.content_filter_info(p_id uuid, p_revision text)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''''
AS $function$
 select jsonb_build_object(''schema'',''content-filters-v1'',''revision'',f.revision_hash,''filterVersion'',f.filter_version,''data'',f.data,
 ''missing'',to_jsonb(machimoa_review.content_filter_missing(f.data)),''origins'',f.origins)
 from machimoa_review.source_item_content_filters f where source_item_id=p_id and revision_hash=p_revision
$function$
','{postgres=X/postgres}','machimoa_review.cl_base_content_filter_info(uuid,text)');
alter function machimoa_review.content_filter_info(uuid,text) rename to cl_base_content_filter_info;
revoke all on function machimoa_review.cl_base_content_filter_info(uuid,text) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_info(p_id uuid, p_revision text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
 SET search_path TO ''
AS $function$
declare c machimoa_review.review_classifications%rowtype;begin select * into c from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision;if not found then return machimoa_review.cl_base_content_filter_info(p_id,p_revision);end if;if c.filters is null then return null;end if;return jsonb_build_object('schema','content-filters-v1','revision',p_revision,'filterVersion',c.classification_version,'data',c.filters,'missing',to_jsonb(machimoa_review.classification_filter_missing(c.filters)),'origins',jsonb_build_object('topic','operator','delivery','operator','location','operator','application','operator','schedule','operator','audience','operator','spaceKind','operator'));end
$function$;
revoke all on function machimoa_review.content_filter_info(uuid,text) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.content_filter_ready(uuid,text)','CREATE OR REPLACE FUNCTION machimoa_review.content_filter_ready(p_id uuid, p_revision text)
 RETURNS boolean
 LANGUAGE sql
 STABLE
 SET search_path TO ''''
AS $function$
 select case when not exists(select 1 from machimoa_review.source_item_content_filters where source_item_id=p_id) then coalesce(not exists(select 1 from machimoa_review.content_filter_enrollments e where e.source_item_id=p_id) or machimoa_review.content_filter_category(p_id,p_revision) in (''policy'',''living''),false) else coalesce((select cardinality(machimoa_review.content_filter_missing(f.data))=0 and s.revision_hash=p_revision and f.source_binding=machimoa_review.content_filter_binding(p_id,p_revision) and machimoa_review.content_filter_consistent(p_id,p_revision,f.data)
 and f.data->>''category''=machimoa_review.content_filter_category(p_id,p_revision) from machimoa_review.source_item_content_filters f join machimoa_review.source_items s on s.id=f.source_item_id where source_item_id=p_id and f.revision_hash=p_revision),false) end
$function$
','{postgres=X/postgres}','machimoa_review.cl_base_content_filter_ready(uuid,text)');
alter function machimoa_review.content_filter_ready(uuid,text) rename to cl_base_content_filter_ready;
revoke all on function machimoa_review.cl_base_content_filter_ready(uuid,text) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_ready(p_id uuid, p_revision text)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
 SET search_path TO ''
AS $function$
begin if exists(select 1 from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision) then return machimoa_review.classification_ready(p_id);end if;return machimoa_review.cl_base_content_filter_ready(p_id,p_revision);end
$function$;
revoke all on function machimoa_review.content_filter_ready(uuid,text) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.program_candidate_guard(uuid)','CREATE OR REPLACE FUNCTION machimoa_review.program_candidate_guard(p_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''''
AS $function$
declare m machimoa_review.program_candidate_inputs%rowtype;s machimoa_review.source_items%rowtype;f machimoa_review.source_item_program_facts%rowtype;
begin
 select * into m from machimoa_review.program_candidate_inputs where candidate_id=p_id;
 select * into s from machimoa_review.source_items where id=m.source_item_id for update;
 if s.source_id is distinct from ''myseoul_program'' then perform machimoa_review.program_candidate_guard_before_myseoul_changes(p_id);return;end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=s.revision_hash for update;
 if (m.revision_hash is distinct from s.revision_hash or m.facts_version is distinct from f.facts_version) and not machimoa_review.myseoul_review_matches(p_id) then
 raise exception using errcode=''PT409'',message=''program_candidate_input_changed'';end if;
 begin perform machimoa_review.myseoul_publication_check(s.id,s.revision_hash,f.facts_version);
 exception when sqlstate ''PT409'' then raise exception using errcode=''PT409'',message=''program_candidate_unavailable'';end;
end $function$
','{postgres=X/postgres}','machimoa_review.cl_base_program_candidate_guard(uuid)');
alter function machimoa_review.program_candidate_guard(uuid) rename to cl_base_program_candidate_guard;
revoke all on function machimoa_review.cl_base_program_candidate_guard(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.program_candidate_guard(p_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin perform machimoa_review.classification_candidate_guard(p_id);if exists(select 1 from machimoa_review.review_classification_candidates where candidate_id=p_id) then return;end if;perform machimoa_review.cl_base_program_candidate_guard(p_id);end
$function$;
revoke all on function machimoa_review.program_candidate_guard(uuid) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.program_candidate_info(uuid)','CREATE OR REPLACE FUNCTION machimoa_review.program_candidate_info(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''''
AS $function$
declare m machimoa_review.program_candidate_inputs%rowtype;s machimoa_review.source_items%rowtype;f machimoa_review.source_item_program_facts%rowtype;src machimoa_review.ingest_sources%rowtype;
 changed boolean;checked boolean;fields jsonb;r jsonb;
begin
 select * into m from machimoa_review.program_candidate_inputs where candidate_id=p_id;
 select * into s from machimoa_review.source_items where id=m.source_item_id;
 if s.source_id is distinct from ''myseoul_program'' then return machimoa_review.program_candidate_info_before_myseoul_changes(p_id);end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=s.revision_hash;
 select * into src from machimoa_review.ingest_sources where source_id=s.source_id;
 changed:=m.revision_hash is distinct from s.revision_hash or m.facts_version is distinct from f.facts_version;
 checked:=machimoa_review.myseoul_review_matches(p_id);
 select coalesce(jsonb_agg(label order by label),''[]'') into fields from (values
 (''title'',''제목''),(''description'',''설명''),(''target'',''대상''),(''conditions'',''참여 조건''),(''language'',''진행 언어''),(''venue'',''장소''),(''delivery_mode'',''진행 방식''),(''fees'',''비용''),(''periods'',''신청·진행 일정''),(''session_evidence'',''회차·시간''),(''meeting_evidence'',''집결 안내''),(''application_methods'',''신청 방법''),(''application_links'',''신청 링크''),(''source_status'',''모집 상태''),(''public_category'',''공개 분류''),(''residence'',''거주 조건''),(''age'',''연령''),(''companion'',''동반 조건'')) v(key,label)
 where case when key=''title'' then (select pf.source_snapshot->''min_fields''->>''title'' from machimoa_review.source_item_program_facts pf where pf.source_item_id=m.source_item_id and pf.revision_hash=m.revision_hash) is distinct from s.min_fields->>''title''
 else m.input_facts->key is distinct from f.facts->key end;
 r:=machimoa_review.myseoul_evaluate(f.facts,statement_timestamp());
 return jsonb_build_object(''inputFactsVersion'',m.facts_version,''currentFactsVersion'',f.facts_version,''inputChanged'',changed,
 ''changeReviewed'',checked,''changedFields'',fields,''comparisonAvailable'',m.input_facts is not null,
 ''canPublish'',(not changed or checked) and f.schema_version=''myseoul-program-facts-v1-local'' and f.evaluated_profile=''myseoul-program-v1-local''
 and not f.manual_excluded and not machimoa_review.admin_trash_pending(s.id,s.revision_hash) and src.enabled and src.permission_status in (''approved_noncommercial'',''approved_commercial'') and machimoa_review.publication_temporal_ready(r)
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and processing_stage<>''ai_enrichment'' and revision_hash=s.revision_hash and status in (''queued'',''claimed'')),
 ''applicationPeriod'',coalesce((select string_agg(value->>''raw'','' / '') from jsonb_array_elements(f.facts->''periods''->''application'')),''공식 안내 확인''),
 ''operatingPeriod'',coalesce((select string_agg(value->>''raw'','' / '') from jsonb_array_elements(f.facts->''periods''->''operation'')),''공식 안내 확인''));
end $function$
','{postgres=X/postgres}','machimoa_review.cl_base_program_candidate_info(uuid)');
alter function machimoa_review.program_candidate_info(uuid) rename to cl_base_program_candidate_info;
revoke all on function machimoa_review.cl_base_program_candidate_info(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.program_candidate_info(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare m machimoa_review.review_classification_candidates%rowtype;c machimoa_review.review_classifications%rowtype;s machimoa_review.source_items%rowtype;changed boolean;begin select * into m from machimoa_review.review_classification_candidates where candidate_id=p_id;if not found then return machimoa_review.cl_base_program_candidate_info(p_id);end if;select * into s from machimoa_review.source_items where id=m.source_item_id;select * into c from machimoa_review.review_classifications where source_item_id=s.id and revision_hash=s.revision_hash;changed:=m.classification_version is distinct from c.classification_version or m.revision_hash is distinct from s.revision_hash or m.native_snapshot is distinct from machimoa_review.classification_native(s.id);return jsonb_build_object('inputFactsVersion',m.classification_version,'currentFactsVersion',coalesce(c.classification_version,m.classification_version),'inputChanged',changed,'changeReviewed',false,'changedFields',case when changed then '["분류·사실·필터"]'::jsonb else '[]'::jsonb end,'comparisonAvailable',true,'canPublish',not changed and machimoa_review.classification_ready(s.id),'applicationPeriod',case when m.facts->>'deadlineKind'='fixed' then m.facts->>'deadlineOn' else '공식 안내 확인' end,'operatingPeriod',case when m.facts->>'category'='event' then (m.facts->>'eventStart')||' ~ '||(m.facts->>'eventEnd') else '공식 안내 확인' end);end
$function$;
revoke all on function machimoa_review.program_candidate_info(uuid) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.content_filter_candidate_info(uuid)','CREATE OR REPLACE FUNCTION machimoa_review.content_filter_candidate_info(p_id uuid)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''''
AS $function$
 select jsonb_build_object(''schema'',''content-filters-v1'',''inputVersion'',m.filter_version,''approvedVersion'',m.approved_version,''currentVersion'',coalesce(f.filter_version,1),
 ''inputRevision'',m.revision_hash,''approvedRevision'',m.approved_revision,''currentRevision'',s.revision_hash,
 ''input'',m.input_data,''approved'',m.approved_data,''current'',coalesce(f.data,m.approved_data),''changed'',f.filter_version is distinct from m.approved_version or s.revision_hash is distinct from m.approved_revision,
 ''canPublish'',coalesce(f.filter_version=m.approved_version and s.revision_hash=m.approved_revision and machimoa_review.content_filter_ready(m.source_item_id,s.revision_hash),false))
 from machimoa_review.candidate_content_filters m join machimoa_review.source_items s on s.id=m.source_item_id left join machimoa_review.source_item_content_filters f on f.source_item_id=m.source_item_id and f.revision_hash=s.revision_hash where m.candidate_id=p_id
$function$
','{postgres=X/postgres}','machimoa_review.cl_base_content_filter_candidate_info(uuid)');
alter function machimoa_review.content_filter_candidate_info(uuid) rename to cl_base_content_filter_candidate_info;
revoke all on function machimoa_review.cl_base_content_filter_candidate_info(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_candidate_info(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
 SET search_path TO ''
AS $function$
declare m machimoa_review.review_classification_candidates%rowtype;c machimoa_review.review_classifications%rowtype;s machimoa_review.source_items%rowtype;changed boolean;begin select * into m from machimoa_review.review_classification_candidates where candidate_id=p_id;if not found then return machimoa_review.cl_base_content_filter_candidate_info(p_id);end if;if m.filters is null then return null;end if;select * into s from machimoa_review.source_items where id=m.source_item_id;select * into c from machimoa_review.review_classifications where source_item_id=s.id and revision_hash=s.revision_hash;changed:=m.classification_version is distinct from c.classification_version or m.revision_hash is distinct from s.revision_hash or m.native_snapshot is distinct from machimoa_review.classification_native(s.id);return jsonb_build_object('schema','content-filters-v1','inputVersion',m.classification_version,'approvedVersion',m.classification_version,'currentVersion',coalesce(c.classification_version,m.classification_version),'inputRevision',m.revision_hash,'approvedRevision',m.revision_hash,'currentRevision',s.revision_hash,'input',m.filters,'approved',m.filters,'current',coalesce(c.filters,m.filters),'changed',changed,'canPublish',not changed and machimoa_review.classification_ready(s.id));end
$function$;
revoke all on function machimoa_review.content_filter_candidate_info(uuid) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.content_filter_candidate_approve(uuid)','CREATE OR REPLACE FUNCTION machimoa_review.content_filter_candidate_approve(p_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''''
AS $function$
declare m machimoa_review.candidate_content_filters%rowtype;f machimoa_review.source_item_content_filters%rowtype;c machimoa_review.curation_candidates%rowtype;
begin
 select * into m from machimoa_review.candidate_content_filters where candidate_id=p_id for update;
 if not found then return;end if;
 select ff.* into f from machimoa_review.source_item_content_filters ff join machimoa_review.source_items s on s.id=ff.source_item_id and s.revision_hash=ff.revision_hash where ff.source_item_id=m.source_item_id for share of ff;
 select * into c from machimoa_review.curation_candidates where id=p_id;
 if f.source_item_id is null or not machimoa_review.content_filter_ready(m.source_item_id,f.revision_hash) or c.user_category is distinct from f.data->>''category'' then raise sqlstate ''PT409'' using message=''content_filter_input_changed'';end if;
 update machimoa_review.candidate_content_filters set approved_version=f.filter_version,approved_revision=f.revision_hash,approved_data=f.data where candidate_id=p_id;
end $function$
','{postgres=X/postgres}','machimoa_review.cl_base_content_filter_candidate_approve(uuid)');
alter function machimoa_review.content_filter_candidate_approve(uuid) rename to cl_base_content_filter_candidate_approve;
revoke all on function machimoa_review.cl_base_content_filter_candidate_approve(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_candidate_approve(p_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin perform machimoa_review.classification_candidate_guard(p_id);if exists(select 1 from machimoa_review.review_classification_candidates where candidate_id=p_id) then return;end if;perform machimoa_review.cl_base_content_filter_candidate_approve(p_id);end
$function$;
revoke all on function machimoa_review.content_filter_candidate_approve(uuid) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.content_filter_publish(uuid)','CREATE OR REPLACE FUNCTION machimoa_review.content_filter_publish(p_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''''
AS $function$
declare m machimoa_review.candidate_content_filters%rowtype;f machimoa_review.source_item_content_filters%rowtype;c machimoa_review.curation_candidates%rowtype;
begin
 select * into m from machimoa_review.candidate_content_filters where candidate_id=p_id for share;
 if not found then return;end if;
 select ff.* into f from machimoa_review.source_item_content_filters ff join machimoa_review.source_items s on s.id=ff.source_item_id and s.revision_hash=ff.revision_hash where ff.source_item_id=m.source_item_id for share of ff;
 select * into c from machimoa_review.curation_candidates where id=p_id;
 if f.filter_version is distinct from m.approved_version or f.revision_hash is distinct from m.approved_revision or f.data is distinct from m.approved_data or not machimoa_review.content_filter_ready(m.source_item_id,m.approved_revision) or c.user_category is distinct from m.approved_data->>''category'' then raise sqlstate ''PT409'' using message=''content_filter_input_changed'';end if;
 if c.published_curation_id is not null then update public.curations set content_filters=m.approved_data where id=c.published_curation_id;end if;
end $function$
','{postgres=X/postgres}','machimoa_review.cl_base_content_filter_publish(uuid)');
alter function machimoa_review.content_filter_publish(uuid) rename to cl_base_content_filter_publish;
revoke all on function machimoa_review.cl_base_content_filter_publish(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_publish(p_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare m machimoa_review.review_classification_candidates%rowtype;cid uuid;begin perform machimoa_review.classification_candidate_guard(p_id);select * into m from machimoa_review.review_classification_candidates where candidate_id=p_id;if not found then perform machimoa_review.cl_base_content_filter_publish(p_id);return;end if;select published_curation_id into cid from machimoa_review.curation_candidates where id=p_id;if cid is not null then update public.curations set content_filters=m.filters where id=cid;end if;end
$function$;
revoke all on function machimoa_review.content_filter_publish(uuid) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.publish_curation_candidate(uuid,text,text,boolean)','CREATE OR REPLACE FUNCTION machimoa_review.publish_curation_candidate(p_candidate_id uuid, p_reviewed_by text, p_review_notes text DEFAULT NULL::text, p_allow_overwrite boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''''
AS $function$
declare result uuid;begin
 -- Validate before publication and update public projection in the same transaction.
 perform machimoa_review.content_filter_publish(p_candidate_id);
 result:=machimoa_review.cf_base_publish_curation_candidate(p_candidate_id,p_reviewed_by,p_review_notes,p_allow_overwrite);
 perform machimoa_review.content_filter_publish(p_candidate_id);
 return result;
end
$function$
','{postgres=X/postgres}','machimoa_review.cl_base_publish_curation_candidate(uuid,text,text,boolean)');
alter function machimoa_review.publish_curation_candidate(uuid,text,text,boolean) rename to cl_base_publish_curation_candidate;
revoke all on function machimoa_review.cl_base_publish_curation_candidate(uuid,text,text,boolean) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.publish_curation_candidate(p_candidate_id uuid, p_reviewed_by text, p_review_notes text DEFAULT NULL::text, p_allow_overwrite boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin perform machimoa_review.classification_candidate_guard(p_candidate_id);return machimoa_review.cl_base_publish_curation_candidate(p_candidate_id,p_reviewed_by,p_review_notes,p_allow_overwrite);end
$function$;
revoke all on function machimoa_review.publish_curation_candidate(uuid,text,text,boolean) from public,anon,authenticated,service_role;
insert into machimoa_review.classification_function_backup values('public.admin_myseoul_program_detail(uuid)','CREATE OR REPLACE FUNCTION public.admin_myseoul_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''''
AS $function$
declare item jsonb;info jsonb;begin
 item:=machimoa_review.cf_base_pub_admin_myseoul_program_detail(p_id);info:=machimoa_review.content_filter_info(p_id,item->>''revision'');
 if info is not null then
 item:=item||jsonb_build_object(''filterInfo'',info,''version'',encode(sha256(convert_to(jsonb_build_array(item->>''version'',info)::text,''UTF8'')),''hex''));
 if item->>''status''<>''excluded'' and jsonb_array_length(info->''missing'')>0 then item:=item||jsonb_build_object(''status'',''open'',''aiStatus'',''blocked'');end if;
 end if;return item;
end
$function$
','{postgres=X/postgres,service_role=X/postgres}','machimoa_review.cl_base_pub_admin_myseoul_program_detail(uuid)');
alter function public.admin_myseoul_program_detail(uuid) rename to cl_base_pub_admin_myseoul_program_detail;
alter function public.cl_base_pub_admin_myseoul_program_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.cl_base_pub_admin_myseoul_program_detail(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.admin_myseoul_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;c machimoa_review.review_classifications%rowtype;codes text[];begin item:=machimoa_review.cl_base_pub_admin_myseoul_program_detail(p_id);select * into c from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=item->>'revision';if not found then return item;end if;codes:=array(select distinct code from unnest(machimoa_review.classification_reasons(p_id,c.facts)||array(select unnest(j.reason_codes) from machimoa_review.processing_jobs j where j.source_item_id=p_id and j.revision_hash=c.revision_hash and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed'))) code);if c.native_snapshot is distinct from machimoa_review.classification_native(p_id) then codes:=array_append(codes,'classification_input_changed');end if;item:=jsonb_set(item,array['result','reasons'],to_jsonb(codes));item:=jsonb_set(item,array['result','decision'],to_jsonb(case when cardinality(codes)=0 then 'in_scope' else 'review_required' end));item:=item||jsonb_build_object('status',case when cardinality(codes)=0 then 'resolved' else 'open' end,'version',encode(sha256(convert_to(jsonb_build_array(item->>'version',to_jsonb(c))::text,'UTF8')),'hex'));return item;end
$function$;
revoke all on function public.admin_myseoul_program_detail(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_myseoul_program_detail(uuid) to service_role;
insert into machimoa_review.classification_function_backup values('public.admin_program_detail(uuid)','CREATE OR REPLACE FUNCTION public.admin_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''''
AS $function$
declare item jsonb;info jsonb;begin
 item:=machimoa_review.cf_base_pub_admin_program_detail(p_id);info:=machimoa_review.content_filter_info(p_id,item->>''revision'');
 if info is not null then
 item:=item||jsonb_build_object(''filterInfo'',info,''version'',encode(sha256(convert_to(jsonb_build_array(item->>''version'',info)::text,''UTF8'')),''hex''));
 if item->>''status''<>''excluded'' and jsonb_array_length(info->''missing'')>0 then item:=item||jsonb_build_object(''status'',''open'',''aiStatus'',''blocked'');end if;
 end if;return item;
end
$function$
','{postgres=X/postgres,service_role=X/postgres}','machimoa_review.cl_base_pub_admin_program_detail(uuid)');
alter function public.admin_program_detail(uuid) rename to cl_base_pub_admin_program_detail;
alter function public.cl_base_pub_admin_program_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.cl_base_pub_admin_program_detail(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.admin_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;c machimoa_review.review_classifications%rowtype;codes text[];begin item:=machimoa_review.cl_base_pub_admin_program_detail(p_id);select * into c from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=item->>'revision';if not found then return item;end if;codes:=array(select distinct code from unnest(machimoa_review.classification_reasons(p_id,c.facts)||array(select unnest(j.reason_codes) from machimoa_review.processing_jobs j where j.source_item_id=p_id and j.revision_hash=c.revision_hash and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed'))) code);if c.native_snapshot is distinct from machimoa_review.classification_native(p_id) then codes:=array_append(codes,'classification_input_changed');end if;item:=jsonb_set(item,array['result','reasons'],to_jsonb(codes));item:=jsonb_set(item,array['result','decision'],to_jsonb(case when cardinality(codes)=0 then 'in_scope' else 'review_required' end));item:=item||jsonb_build_object('status',case when cardinality(codes)=0 then 'resolved' else 'open' end,'version',encode(sha256(convert_to(jsonb_build_array(item->>'version',to_jsonb(c))::text,'UTF8')),'hex'));return item;end
$function$;
revoke all on function public.admin_program_detail(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_program_detail(uuid) to service_role;
insert into machimoa_review.classification_function_backup values('machimoa_review.claim_processing_jobs(text,integer,text,integer)','CREATE OR REPLACE FUNCTION machimoa_review.claim_processing_jobs(p_stage text, p_limit integer, p_worker_id text, p_lease_seconds integer DEFAULT 300)
 RETURNS TABLE(job_id uuid, source_item_id uuid, source_id text, external_key text, revision_hash text, processing_stage text, curation_source text, normalized_payload jsonb, disposition text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''''
AS $function$
declare
  v_claims jsonb;
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_limit pg_catalog.int4 := coalesce(p_limit, 10);
  v_worker pg_catalog.text := pg_catalog.btrim(coalesce(p_worker_id, ''''));
  v_lease pg_catalog.int4 := coalesce(p_lease_seconds, 300);
begin
  if p_stage is distinct from ''ai_enrichment'' then
    return;
  end if;
  if v_limit < 1 or v_limit > 10 then
    raise exception ''invalid claim limit'';
  end if;
  if pg_catalog.char_length(v_worker) not between 1 and 64 then
    raise exception ''invalid worker_id'';
  end if;

  with picked as (
    select j.id
    from machimoa_review.processing_jobs as j
    join machimoa_review.source_items as si
      on si.id = j.source_item_id
     and si.revision_hash is not distinct from j.revision_hash
    where si.source_id <> ''myseoul_program''
      and j.processing_stage = ''ai_enrichment''
      and si.disposition = ''target''
      and si.body_usable is true
      and si.has_source_url is true
      and (
        (
          j.status = ''queued''
          and j.available_at <= v_now
          and (j.next_retry_at is null or j.next_retry_at <= v_now)
        )
        or (
          j.status = ''claimed''
          and j.claim_lease_until is not null
          and j.claim_lease_until <= v_now
        )
      )
      and (
        (
          exists (
            select 1
            from machimoa_review.source_item_product_types as pt
            where pt.source_item_id = j.source_item_id
              and pt.revision_hash is not distinct from j.revision_hash
              and pt.gate_facts is null
              and pt.assessment_schema_version is null
              and pt.evaluated_profile is null
              and pt.evaluated_at is null
          )
          and exists (
            select 1
            from machimoa_review.ingest_review_decisions as d
            where d.source_item_id = j.source_item_id
              and d.revision_hash is not distinct from j.revision_hash
              and d.decision = ''approve_ai''
          )
        )
        or (
          exists (
            select 1
            from machimoa_review.source_item_product_types as pt
            where pt.source_item_id = j.source_item_id
              and pt.revision_hash is not distinct from j.revision_hash
              and pt.gate_facts is not null
              and pt.gate_facts <> ''{}''::pg_catalog.jsonb
              and pt.assessment_schema_version is not distinct from ''gate-facts-v1''
              and pt.evaluated_profile is not distinct from ''capital_v1''
              and pt.evaluated_at is not null
              and case
                when machimoa_review.gate_facts_row_is_complete_v1(
                  pt.product_type,
                  pt.gate_facts,
                  pt.assessment_schema_version,
                  pt.evaluated_profile,
                  pt.evaluated_at,
                  ''capital_v1''
                ) then exists (
                  select 1
                  from machimoa_review.evaluate_source_item_gates(
                    si.body_usable,
                    si.has_source_url,
                    si.attachment_present,
                    pt.product_type,
                    pt.reason_codes,
                    pt.gate_facts
                  ) as ev
                  where ev.disposition is not distinct from ''target''
                )
                else false
              end
          )
        )
      )
      and machimoa_review.category_period_ready(j.source_item_id, j.revision_hash)
      and machimoa_review.content_filter_ready(j.source_item_id,j.revision_hash)
      -- A captured filter attempt is never automatically reacquired, even after lease expiry.
      and (si.source_id not in (''youthcenter_content'',''youthcenter_policy'') or not exists(select 1 from machimoa_review.content_filter_claim_inputs prior where prior.job_id=j.id))
      and not exists (
        select 1
        from machimoa_review.processing_jobs as r
        where r.source_item_id = j.source_item_id
          and r.revision_hash is not distinct from j.revision_hash
          and r.processing_stage in (
            ''region_review'',
            ''relevance_review'',
            ''content_review'',
            ''product_type_review''
          )
          and r.status in (''queued'', ''claimed'')
      )
    order by j.queued_at, j.id
    for update of j skip locked
    limit v_limit
  ),
  updated as (
    update machimoa_review.processing_jobs as j
    set
      status = ''claimed'',
      claimed_at = v_now,
      claim_lease_until = v_now + (v_lease || '' seconds'')::pg_catalog.interval,
      claimed_by = v_worker
    from picked
    where j.id = picked.id
    returning j.*
  )
  select coalesce(jsonb_agg(jsonb_build_object(''job_id'',u.id,''source_item_id'',u.source_item_id,''source_id'',si.source_id,
    ''external_key'',si.external_key,''revision_hash'',u.revision_hash,''processing_stage'',u.processing_stage,
    ''curation_source'',s.legacy_curation_source,''normalized_payload'',si.normalized_payload,''disposition'',si.disposition,''claimed_at'',u.claimed_at)),''[]'') into v_claims
  from updated as u
  join machimoa_review.source_items as si
    on si.id = u.source_item_id
  join machimoa_review.ingest_sources as s
    on s.source_id = si.source_id;
  -- AFTER triggers have now captured the version/fence; read it in the next statement.
  return query select r.job_id,r.source_item_id,r.source_id,r.external_key,r.revision_hash,r.processing_stage,r.curation_source,
    r.normalized_payload||case when machimoa_review.content_filter_claim_context(r.job_id,r.claimed_at) is null then ''{}''::jsonb else jsonb_build_object(''content_filter_context'',machimoa_review.content_filter_claim_context(r.job_id,r.claimed_at)) end,r.disposition
  from jsonb_to_recordset(v_claims) r(job_id uuid,source_item_id uuid,source_id text,external_key text,revision_hash text,processing_stage text,curation_source text,normalized_payload jsonb,disposition text,claimed_at timestamptz);
end
$function$
','{postgres=X/postgres}',NULL);
CREATE OR REPLACE FUNCTION machimoa_review.claim_processing_jobs(p_stage text, p_limit integer, p_worker_id text, p_lease_seconds integer DEFAULT 300)
 RETURNS TABLE(job_id uuid, source_item_id uuid, source_id text, external_key text, revision_hash text, processing_stage text, curation_source text, normalized_payload jsonb, disposition text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_claims jsonb;
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

  with picked as (
    select j.id
    from machimoa_review.processing_jobs as j
    join machimoa_review.source_items as si
      on si.id = j.source_item_id
     and si.revision_hash is not distinct from j.revision_hash
    where si.source_id <> 'myseoul_program'
      and j.processing_stage = 'ai_enrichment'
      and si.disposition = 'target'
      and si.body_usable is true
      and si.has_source_url is true
      and (
        (
          j.status = 'queued'
          and j.available_at <= v_now
          and (j.next_retry_at is null or j.next_retry_at <= v_now)
        )
        or (
          j.status = 'claimed'
          and j.claim_lease_until is not null
          and j.claim_lease_until <= v_now
        )
      )
      and (
        (
          exists (
            select 1
            from machimoa_review.source_item_product_types as pt
            where pt.source_item_id = j.source_item_id
              and pt.revision_hash is not distinct from j.revision_hash
              and pt.gate_facts is null
              and pt.assessment_schema_version is null
              and pt.evaluated_profile is null
              and pt.evaluated_at is null
          )
          and exists (
            select 1
            from machimoa_review.ingest_review_decisions as d
            where d.source_item_id = j.source_item_id
              and d.revision_hash is not distinct from j.revision_hash
              and d.decision = 'approve_ai'
          )
        )
        or (
          exists (
            select 1
            from machimoa_review.source_item_product_types as pt
            where pt.source_item_id = j.source_item_id
              and pt.revision_hash is not distinct from j.revision_hash
              and pt.gate_facts is not null
              and pt.gate_facts <> '{}'::pg_catalog.jsonb
              and pt.assessment_schema_version is not distinct from 'gate-facts-v1'
              and pt.evaluated_profile is not distinct from 'capital_v1'
              and pt.evaluated_at is not null
              and case
                when machimoa_review.gate_facts_row_is_complete_v1(
                  pt.product_type,
                  pt.gate_facts,
                  pt.assessment_schema_version,
                  pt.evaluated_profile,
                  pt.evaluated_at,
                  'capital_v1'
                ) then exists (
                  select 1
                  from machimoa_review.evaluate_source_item_gates(
                    si.body_usable,
                    si.has_source_url,
                    si.attachment_present,
                    pt.product_type,
                    pt.reason_codes,
                    pt.gate_facts
                  ) as ev
                  where ev.disposition is not distinct from 'target'
                )
                else false
              end
          )
        )
      )
      and machimoa_review.category_period_ready(j.source_item_id, j.revision_hash)
      and not exists(select 1 from machimoa_review.review_classifications cl where cl.source_item_id=j.source_item_id and cl.revision_hash=j.revision_hash)
      and machimoa_review.content_filter_ready(j.source_item_id,j.revision_hash)
      -- A captured filter attempt is never automatically reacquired, even after lease expiry.
      and (si.source_id not in ('youthcenter_content','youthcenter_policy') or not exists(select 1 from machimoa_review.content_filter_claim_inputs prior where prior.job_id=j.id))
      and not exists (
        select 1
        from machimoa_review.processing_jobs as r
        where r.source_item_id = j.source_item_id
          and r.revision_hash is not distinct from j.revision_hash
          and r.processing_stage in (
            'region_review',
            'relevance_review',
            'content_review',
            'product_type_review'
          )
          and r.status in ('queued', 'claimed')
      )
    order by j.queued_at, j.id
    for update of j skip locked
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
  select coalesce(jsonb_agg(jsonb_build_object('job_id',u.id,'source_item_id',u.source_item_id,'source_id',si.source_id,
    'external_key',si.external_key,'revision_hash',u.revision_hash,'processing_stage',u.processing_stage,
    'curation_source',s.legacy_curation_source,'normalized_payload',si.normalized_payload,'disposition',si.disposition,'claimed_at',u.claimed_at)),'[]') into v_claims
  from updated as u
  join machimoa_review.source_items as si
    on si.id = u.source_item_id
  join machimoa_review.ingest_sources as s
    on s.source_id = si.source_id;
  -- AFTER triggers have now captured the version/fence; read it in the next statement.
  return query select r.job_id,r.source_item_id,r.source_id,r.external_key,r.revision_hash,r.processing_stage,r.curation_source,
    r.normalized_payload||case when machimoa_review.content_filter_claim_context(r.job_id,r.claimed_at) is null then '{}'::jsonb else jsonb_build_object('content_filter_context',machimoa_review.content_filter_claim_context(r.job_id,r.claimed_at)) end,r.disposition
  from jsonb_to_recordset(v_claims) r(job_id uuid,source_item_id uuid,source_id text,external_key text,revision_hash text,processing_stage text,curation_source text,normalized_payload jsonb,disposition text,claimed_at timestamptz);
end
$function$
;

create function machimoa_review.classification_table_metadata(p_name text) returns jsonb
language sql stable set search_path='' as $$
 select jsonb_build_object('owner',pg_get_userbyid(c.relowner),'acl',c.relacl::text,'rls',c.relrowsecurity,'forceRls',c.relforcerowsecurity,
 'columns',(select jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid)) order by a.attnum) from pg_attribute a left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped),
 'constraints',(select coalesce(jsonb_agg(jsonb_build_array(conname,pg_get_constraintdef(oid),convalidated) order by conname),'[]') from pg_constraint where conrelid=c.oid),
 'indexes',(select coalesce(jsonb_agg(jsonb_build_array(indexrelid::regclass::text,pg_get_indexdef(indexrelid),indisvalid) order by indexrelid::regclass::text),'[]') from pg_index where indrelid=c.oid),
 'policies',(select coalesce(jsonb_agg(jsonb_build_array(polname,polcmd,polpermissive,polroles,pg_get_expr(polqual,polrelid),pg_get_expr(polwithcheck,polrelid)) order by polname),'[]') from pg_policy where polrelid=c.oid)) from pg_class c where c.oid=to_regclass(p_name)
$$;

do $$ declare r record;begin
 for r in select c.oid::regclass name from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_review' and c.relname in ('review_classifications','review_classification_history','review_classification_claims','review_classification_candidates','review_classification_publications','classification_function_backup','classification_installed_objects') loop
 execute format('alter table %s enable row level security',r.name);execute format('revoke all on table %s from public,anon,authenticated,service_role',r.name);end loop;
 for r in select p.oid::regprocedure name,n.nspname schema_name from pg_proc p join pg_namespace n on n.oid=p.pronamespace where (n.nspname='machimoa_review' and p.proname like 'classification_%') or (n.nspname='public' and p.proname in ('admin_review_classification_detail','admin_review_reclassify','claim_reclassified_content_ai','finish_reclassified_content_ai','reclassified_content_ai_status','admin_review_apply_public_classification')) loop
 execute format('alter function %s owner to postgres',r.name);execute format('revoke all on function %s from public,anon,authenticated,service_role',r.name);if r.schema_name='public' then execute format('grant execute on function %s to service_role',r.name);end if;end loop;
end $$;
create table machimoa_review.classification_installed_objects(kind text not null,name text not null,definition text not null,acl text,primary key(kind,name));
alter table machimoa_review.classification_installed_objects enable row level security;
revoke all on machimoa_review.classification_installed_objects from public,anon,authenticated,service_role;
insert into machimoa_review.classification_installed_objects select 'function',n.nspname||'.'||p.proname||'('||replace(oidvectortypes(p.proargtypes),', ',',')||')',pg_get_functiondef(p.oid),jsonb_build_object('acl',p.proacl::text,'owner',pg_get_userbyid(p.proowner))::text from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_review' and (p.proname like 'classification_%' or p.proname like 'cl_base_%') or p.oid in (select to_regprocedure(name) from machimoa_review.classification_function_backup) or n.nspname='public' and p.proname in ('admin_review_classification_detail','admin_review_reclassify','claim_reclassified_content_ai','finish_reclassified_content_ai','reclassified_content_ai_status','admin_review_apply_public_classification');
insert into machimoa_review.classification_installed_objects select 'trigger',tgname,pg_get_triggerdef(oid),null from pg_trigger where tgname in ('classification_claim_guard','classification_candidate_update');

insert into machimoa_review.classification_installed_objects select 'table','machimoa_review.'||name,machimoa_review.classification_table_metadata('machimoa_review.'||name)::text,null from unnest(array['review_classifications','review_classification_history','review_classification_claims','review_classification_candidates','review_classification_publications','classification_function_backup','classification_installed_objects']) name;
notify pgrst,'reload schema';
commit;
