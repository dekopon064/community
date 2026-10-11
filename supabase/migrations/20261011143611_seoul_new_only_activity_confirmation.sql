begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- No source activation, backfill or existing candidate updates.
-- admin_program_detail accepts only the verified LF/CRLF predecessor bodies; ACL/owner/config stay exact.

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('public.admin_program_detail(uuid)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('public.admin_program_detail(uuid)')),'UTF8')),'hex')not in ('c69d4d135f4ed55bda72b93ec269990d64db12510c11b33ab16c750fa4bec77d','7649d0a900ac1f95420ed1627e4ed17079f802924202603ecda89a5b56067cfc') or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('public.admin_program_detail(uuid)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres,service_role=X/postgres}", "config": ["search_path=\"\""], "definer": true}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','public.admin_program_detail(uuid)';end if;end $$;

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('public.observe_seoul_program(uuid,jsonb,jsonb)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('public.observe_seoul_program(uuid,jsonb,jsonb)')),'UTF8')),'hex')<>'52fb63602d2258873fb00fdf4ee62cea950e49b574f963aa70d320ee5833e952' or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('public.observe_seoul_program(uuid,jsonb,jsonb)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres,service_role=X/postgres}", "config": ["search_path=\"\""], "definer": true}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','public.observe_seoul_program(uuid,jsonb,jsonb)';end if;end $$;

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('public.claim_seoul_program_ai(uuid,text,text,integer)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('public.claim_seoul_program_ai(uuid,text,text,integer)')),'UTF8')),'hex')<>'7a688f02bf13f477051aa287e8a5dde01973a803c3557039c1e96c5f0a2f0b06' or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('public.claim_seoul_program_ai(uuid,text,text,integer)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres,service_role=X/postgres}", "config": ["search_path=\"\""], "definer": true}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','public.claim_seoul_program_ai(uuid,text,text,integer)';end if;end $$;

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)')),'UTF8')),'hex')<>'79c14dcfc779abd549d6b96dafb0d4a59e8264fd391d595ef0b54be14c23a24b' or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres}", "config": ["search_path=\"\""], "definer": false}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','machimoa_review.classification_reasons(uuid,jsonb)';end if;end $$;

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.program_ai_check(uuid,text,bigint)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('machimoa_review.program_ai_check(uuid,text,bigint)')),'UTF8')),'hex')<>'84cb7378c0e165cf2b9e233110f97c16f7943cc44022c962becfd0b3e48d193b' or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('machimoa_review.program_ai_check(uuid,text,bigint)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres}", "config": ["search_path=\"\""], "definer": true}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','machimoa_review.program_ai_check(uuid,text,bigint)';end if;end $$;

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.program_publication_check(uuid,text,bigint)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('machimoa_review.program_publication_check(uuid,text,bigint)')),'UTF8')),'hex')<>'a6cd120eb1b2bde789bf4db5a286230bdb3c672ac5981d54a72fd0e6dbab9288' or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('machimoa_review.program_publication_check(uuid,text,bigint)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres}", "config": ["search_path=\"\""], "definer": true}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','machimoa_review.program_publication_check(uuid,text,bigint)';end if;end $$;

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.program_evaluate(jsonb,timestamp with time zone)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('machimoa_review.program_evaluate(jsonb,timestamp with time zone)')),'UTF8')),'hex')<>'b0af88e39a12eda491b248bc44ef7581eedf8baae804d84b602a90bc6f08ed9c' or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('machimoa_review.program_evaluate(jsonb,timestamp with time zone)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres}", "config": ["search_path=\"\""], "definer": true}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','machimoa_review.program_evaluate(jsonb,timestamp with time zone)';end if;end $$;

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.program_candidate_info_before_myseoul_changes(uuid)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('machimoa_review.program_candidate_info_before_myseoul_changes(uuid)')),'UTF8')),'hex')<>'6586e7c00b65b3bfbd1caf7905654168a9e685a7897f00163d01cbdcca034c17' or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('machimoa_review.program_candidate_info_before_myseoul_changes(uuid)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres}", "config": ["search_path=\"\""], "definer": true}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','machimoa_review.program_candidate_info_before_myseoul_changes(uuid)';end if;end $$;

do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.cf_base_program_refresh(uuid,timestamp with time zone)') is null or encode(sha256(convert_to(pg_get_functiondef(to_regprocedure('machimoa_review.cf_base_program_refresh(uuid,timestamp with time zone)')),'UTF8')),'hex')<>'7b8a4347d474fde2d4bca6342f04b9cc2f5f14163b93a10d45c5af7541aca46b' or (select jsonb_build_object('owner',pg_get_userbyid(proowner),'acl',proacl::text,'config',proconfig,'definer',prosecdef) from pg_proc where oid=to_regprocedure('machimoa_review.cf_base_program_refresh(uuid,timestamp with time zone)')) is distinct from '{"owner": "postgres", "acl": "{postgres=X/postgres}", "config": ["search_path=\"\""], "definer": true}'::jsonb then raise exception 'seoul_workflow_predecessor_changed: %','machimoa_review.cf_base_program_refresh(uuid,timestamp with time zone)';end if;end $$;


-- Audit records stay private. Values are confirmed against this source revision,
-- not copied into API observations or represented as an invented source quote.
create table machimoa_review.seoul_activity_confirmations (
 event_id bigint primary key references machimoa_review.admin_review_events(id),
 source_item_id uuid not null, revision_hash text not null,
 before_facts_version bigint not null check(before_facts_version>0),
 confirmed_facts_version bigint not null check(confirmed_facts_version=before_facts_version+1),
 confirmed_filter_version bigint not null check(confirmed_filter_version>0),
 confirmed_values jsonb not null, source_reference jsonb not null,
 foreign key(source_item_id,revision_hash) references machimoa_review.source_item_program_facts(source_item_id,revision_hash)
);
create index seoul_activity_confirmations_item on machimoa_review.seoul_activity_confirmations(source_item_id,revision_hash);
alter table machimoa_review.seoul_activity_confirmations enable row level security;
revoke all on machimoa_review.seoul_activity_confirmations from public,anon,authenticated,service_role;

create function machimoa_review.seoul_activity_binding(f jsonb,d jsonb) returns jsonb
language sql immutable set search_path='' as $$
 select jsonb_build_object('delivery_mode',f->'delivery_mode','activity_region',f->'activity_region',
 'activity_evidence',f->'activity_evidence','official_url',f->'official_url','location',d->'location','delivery',d->'delivery');
$$;
create function machimoa_review.seoul_activity_confirmed(p_id uuid,p_revision text) returns boolean
language sql stable set search_path='' as $$
 select exists(select 1 from machimoa_review.seoul_activity_confirmations r
 join machimoa_review.source_items s on s.id=r.source_item_id and s.revision_hash=r.revision_hash and s.source_id='seoul_reservation'
 join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
 join machimoa_review.source_item_content_filters cf on cf.source_item_id=s.id and cf.revision_hash=s.revision_hash
 where r.source_item_id=p_id and r.revision_hash=p_revision
 and r.confirmed_values=machimoa_review.seoul_activity_binding(f.facts,cf.data)
 and r.source_reference=jsonb_build_object('revision',s.revision_hash,'officialUrl',s.normalized_payload->'source_url')
 and f.facts->>'delivery_mode' in ('offline','hybrid') and f.facts->>'activity_region'='capital');
$$;

CREATE OR REPLACE FUNCTION machimoa_review.program_evaluate_with_confirmation(p jsonb, p_now timestamp with time zone, p_activity_confirmed boolean)
 RETURNS jsonb
 LANGUAGE plpgsql
 IMMUTABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare excluded text[]:='{}'; reasons text[]:='{}'; unavailable text[]:='{}'; d jsonb; a jsonb; b jsonb; kind text; result text;
begin
 perform machimoa_review.program_validate(p);
 if p_now is null then raise exception using errcode='PT422',message='program_now_required'; end if;
 if p->>'content_kind' in ('employment','institutional_business') then excluded:=array_append(excluded,'service_scope_excluded'); end if;
 if p->>'application_actor' in ('institution','nationality_excluded') and not (p->'conflicts' ? 'application_actor_conflict') then
   excluded:=array_append(excluded,case when p->>'application_actor'='institution' then 'individual_participation_excluded' else 'nationality_explicitly_excluded' end); end if;
 if p->>'activity_region' in ('noncapital','mixed') and p->>'delivery_mode'<>'online' then excluded:=array_append(excluded,'activity_outside_capital'); end if;
 if p->>'residence_scope'='noncapital' then excluded:=array_append(excluded,'residence_outside_capital'); end if;
 if cardinality(excluded)>0 then return jsonb_build_object('decision','out_of_scope','disposition','non_target','reasons',to_jsonb(excluded)); end if;
 reasons:=array(select jsonb_array_elements_text(p->'missing')) || array(select jsonb_array_elements_text(p->'conflicts'));
 if p->>'official_url'='' then reasons:=array_append(reasons,'missing_source_url');end if;
 if char_length(btrim(p->>'description'))<20 and not reasons && array['attachment_dependent','program_description_missing'] then
 reasons:=array_append(reasons,'program_description_missing');end if;
 if exists(select 1 from jsonb_each(p->'periods') x where x.value->>'status'<>'ok') then reasons:=array_append(reasons,'period_missing_or_unparsed');end if;
 foreach kind in array array['RCPT','SVCOPN'] loop
   a:=p->'periods'->(kind||'BGNDT');b:=p->'periods'->(kind||'ENDDT');
   if a->>'status'='ok' and b->>'status'='ok' and
     (left(a->>'value',10)>left(b->>'value',10) or
      a->>'precision'='second' and b->>'precision'='second' and (a->>'value')::timestamptz>(b->>'value')::timestamptz) then
      reasons:=array_append(reasons,'period_order_conflict');end if;
 end loop;
 if p->>'fee_kind'='free' and exists(select 1 from jsonb_array_elements_text(p->'fee_amounts') x where x ~ '^[1-9][0-9,]*(\.[0-9]+)?\s*(만\s*)?원') then
 reasons:=array_append(reasons,'fee_conflict');end if;
 if p->>'content_kind'<>'program' then reasons:=array_append(reasons,case when p->>'content_kind'='policy_finance' then 'policy_eligibility_unconfirmed' else 'program_purpose_unconfirmed' end); end if;
 if p->>'delivery_mode'='unknown' then reasons:=array_append(reasons,'delivery_mode_unknown'); end if;
 if p->>'delivery_mode' in ('offline','hybrid') and (p->>'activity_region'<>'capital' or (p->'activity_evidence'='[]'::jsonb and not coalesce(p_activity_confirmed,false))) then reasons:=array_append(reasons,'activity_location_unknown'); end if;
 if p->>'residence_scope'='unknown' or p->>'delivery_mode'='online' and
 (p->>'residence_scope' not in ('nationwide','includes_capital','capital') or p->'residence_evidence'='[]'::jsonb) then reasons:=array_append(reasons,'residence_scope_unknown'); end if;
 if p->>'source_status'='unknown' then reasons:=array_append(reasons,'source_status_unknown'); end if;
 -- Stable first occurrence order, also used by Python.
 reasons:=array(select reason from unnest(reasons) with ordinality r(reason,n) group by reason order by min(n));
 d:=p->'periods'->'RCPTENDDT';
 if p->>'source_status' in ('reservation_closed','application_closed') or
 (d->>'status'='ok' and (case when d->>'precision'='day' then (p_now at time zone 'Asia/Seoul')::date>(d->>'value')::date else p_now>(d->>'value')::timestamptz end))
 then unavailable:=array_append(unavailable,'not_currently_accepting'); end if;
 d:=p->'periods'->'SVCOPNENDDT';
 if d->>'status'='ok' and (case when d->>'precision'='day' then (p_now at time zone 'Asia/Seoul')::date>(d->>'value')::date else p_now>(d->>'value')::timestamptz end)
 then unavailable:=array_append(unavailable,'program_ended'); end if;
 d:=p->'periods'->'RCPTBGNDT';
 if d->>'status'='ok' and (case when d->>'precision'='day' then (p_now at time zone 'Asia/Seoul')::date<(d->>'value')::date else p_now<(d->>'value')::timestamptz end)
 then unavailable:=array_append(unavailable,'application_not_started'); end if;
 if cardinality(unavailable)>0 and cardinality(reasons)=0 then result:='not_currently_available';reasons:=unavailable;
 elsif cardinality(reasons)>0 then result:='review_required';else result:='in_scope';end if;
 return jsonb_build_object('decision',result,'disposition',case when result='in_scope' then 'target' else 'observe_only' end,'reasons',to_jsonb(reasons));
end $function$
;


create or replace function machimoa_review.program_evaluate(p jsonb,p_now timestamptz) returns jsonb
language sql immutable security definer set search_path='' as $$
 select machimoa_review.program_evaluate_with_confirmation(p,p_now,false);
$$;
create function machimoa_review.program_evaluate_reviewed(p jsonb,p_now timestamptz,p_id uuid,p_revision text) returns jsonb
language sql stable set search_path='' as $$
 select machimoa_review.program_evaluate_with_confirmation(p,p_now,
 coalesce((select f.facts=p and machimoa_review.seoul_activity_confirmed(p_id,p_revision)
 from machimoa_review.source_item_program_facts f where f.source_item_id=p_id and f.revision_hash=p_revision),false));
$$;

CREATE OR REPLACE FUNCTION machimoa_review.cf_base_program_refresh(p_id uuid, p_now timestamp with time zone DEFAULT clock_timestamp())
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 v_result jsonb; stage text; reason text[]; allowed boolean;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash for update;
 if not found then raise exception using errcode='PT404',message='program_facts_not_found';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
   raise exception using errcode='PT409',message='program_processing_active';end if;
 select enabled and permission_status in ('approved_noncommercial','approved_commercial') into allowed
 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 v_result:=case when f.manual_excluded then jsonb_build_object('decision','out_of_scope','disposition','non_target','reasons',jsonb_build_array('manual_service_scope_excluded'))
 else machimoa_review.program_evaluate_reviewed(f.facts,p_now,p_id,s.revision_hash) end;
 if not f.manual_excluded and machimoa_review.admin_trash_pending(p_id,s.revision_hash) then
   v_result:=v_result||jsonb_build_object('decision','review_required','disposition','observe_only',
     'reasons',coalesce(v_result->'reasons','[]'::jsonb)||jsonb_build_array('restored_review_pending'));
 end if;
 update machimoa_review.source_item_program_facts set result=v_result where source_item_id=p_id and revision_hash=s.revision_hash;
 update machimoa_review.source_items set disposition=v_result->>'disposition' where id=p_id;
 -- Old revisions cannot remain queued. Completed jobs are never resurrected.
 update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp()
 where source_item_id=p_id and revision_hash<>s.revision_hash and status in ('queued','failed');
 stage:=case when v_result->>'decision'='review_required' then 'content_review'
             when machimoa_review.publication_temporal_ready(v_result) and allowed then 'ai_enrichment' else null end;
 update machimoa_review.processing_jobs set status=case when processing_stage='content_review' and machimoa_review.publication_temporal_ready(v_result) then 'completed' else 'cancelled' end,
 completed_at=clock_timestamp(),reason_codes=case when processing_stage='content_review' then '{}'::text[] else reason_codes end
 where source_item_id=p_id and revision_hash=s.revision_hash and status in ('queued','failed') and processing_stage is distinct from stage;
 if stage is not null then
   reason:=case when stage='content_review' then array(select jsonb_array_elements_text(v_result->'reasons')) else '{}'::text[] end;
   insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
   values(p_id,s.revision_hash,stage,'queued',clock_timestamp(),clock_timestamp(),reason)
   on conflict(source_item_id,revision_hash,processing_stage) do update
   set reason_codes=excluded.reason_codes,status='queued',completed_at=null
   where machimoa_review.processing_jobs.status in ('queued','cancelled','failed');
 end if;
end $function$
;

CREATE OR REPLACE FUNCTION machimoa_review.program_ai_check(p_id uuid, p_revision text, p_version bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; allowed boolean;
begin
 if not machimoa_review.content_filter_ready(p_id,p_revision) then raise sqlstate 'PT409' using message='content_filter_not_ready';end if;
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found or s.revision_hash is distinct from p_revision then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 select enabled and permission_status in ('approved_noncommercial','approved_commercial') into allowed
 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 if not found or f.facts_version is distinct from p_version or
 f.schema_version<>'program-scope-v1-local' or f.evaluated_profile<>'program_capital_v1_local' then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 if not coalesce(allowed,false) or f.manual_excluded or machimoa_review.admin_trash_pending(p_id,p_revision) or
 not machimoa_review.publication_temporal_ready(machimoa_review.program_evaluate_reviewed(f.facts,clock_timestamp(),p_id,p_revision)) or
 s.normalized_payload->'provider_fields'->>'MAXCLASSNM' is distinct from '문화체험' or
 exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) then
  raise exception using errcode='PT409',message='program_ai_unavailable';end if;
end $function$
;

CREATE OR REPLACE FUNCTION machimoa_review.program_publication_check(p_id uuid, p_revision text, p_version bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; allowed boolean;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found or s.revision_hash is distinct from p_revision then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 select enabled and permission_status in ('approved_noncommercial','approved_commercial') into allowed
 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 if not found or f.facts_version is distinct from p_version or
 f.schema_version<>'program-scope-v1-local' or f.evaluated_profile<>'program_capital_v1_local' then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 if not coalesce(allowed,false) or f.manual_excluded or machimoa_review.admin_trash_pending(p_id,p_revision) or
 not machimoa_review.publication_temporal_ready(machimoa_review.program_evaluate_reviewed(f.facts,clock_timestamp(),p_id,p_revision)) or
 s.normalized_payload->'provider_fields'->>'MAXCLASSNM' is distinct from '문화체험' or
 exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) then
  raise exception using errcode='PT409',message='program_ai_unavailable';end if;
end $function$
;

CREATE OR REPLACE FUNCTION machimoa_review.program_candidate_info_before_myseoul_changes(p_id uuid)
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
 select jsonb_build_object('inputFactsVersion',m.facts_version,'currentFactsVersion',f.facts_version,
 'inputChanged',m.facts_version<>f.facts_version,
 'canPublish',m.facts_version=f.facts_version and not f.manual_excluded and not machimoa_review.admin_trash_pending(s.id,s.revision_hash) and src.enabled and
 src.permission_status in ('approved_noncommercial','approved_commercial') and
 (s.source_id<>'myseoul_program' or not exists(select 1 from machimoa_review.processing_jobs
 where source_item_id=s.id and revision_hash=s.revision_hash and processing_stage<>'ai_enrichment' and status in ('queued','claimed'))) and
 machimoa_review.publication_temporal_ready(case when s.source_id='myseoul_program' then machimoa_review.myseoul_evaluate(f.facts,statement_timestamp()) else machimoa_review.program_evaluate_reviewed(f.facts,statement_timestamp(),s.id,s.revision_hash) end)
    and s.source_id='seoul_reservation' and f.schema_version='program-scope-v1-local' and f.evaluated_profile='program_capital_v1_local'
    and s.normalized_payload->'provider_fields'->>'MAXCLASSNM'='문화체험'
    and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=s.revision_hash and processing_stage<>'ai_enrichment' and status in ('queued','claimed')),
 'applicationPeriod',case when s.source_id='myseoul_program' then coalesce((select string_agg(value->>'raw',' / ') from jsonb_array_elements(m.input_facts->'periods'->'application')),'공식 안내 확인') else concat(m.input_facts->'periods'->'RCPTBGNDT'->>'value',' ~ ',m.input_facts->'periods'->'RCPTENDDT'->>'value') end,
 'operatingPeriod',case when s.source_id='myseoul_program' then coalesce((select string_agg(value->>'raw',' / ') from jsonb_array_elements(m.input_facts->'periods'->'operation')),'공식 안내 확인') else concat(m.input_facts->'periods'->'SVCOPNBGNDT'->>'value',' ~ ',m.input_facts->'periods'->'SVCOPNENDDT'->>'value') end)
 from machimoa_review.program_candidate_inputs m join machimoa_review.source_item_program_facts f
 on f.source_item_id=m.source_item_id and f.revision_hash=m.revision_hash
 join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash
 join machimoa_review.ingest_sources src on src.source_id=s.source_id where m.candidate_id=p_id;
$function$
;

CREATE OR REPLACE FUNCTION machimoa_review.classification_reasons(p_id uuid, f jsonb)
 RETURNS text[]
 LANGUAGE plpgsql
 STABLE
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype;pf machimoa_review.source_item_program_facts%rowtype;r jsonb;codes text[];g jsonb;d jsonb;venue_mode boolean;venue_ready boolean:=false;
begin
 select * into s from machimoa_review.source_items where id=p_id;
 select * into pf from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash;
 if pf.source_item_id is not null then
 r:=case when s.source_id='myseoul_program' then machimoa_review.myseoul_evaluate(pf.facts,statement_timestamp()) else machimoa_review.program_evaluate_reviewed(pf.facts,statement_timestamp(),s.id,s.revision_hash) end;
 if pf.manual_excluded or r->>'decision'='out_of_scope' then return array['classification_source_excluded'];end if;
 select array(select code from jsonb_array_elements_text(coalesce(r->'reasons','[]')) code where not (machimoa_review.publication_temporal_ready(r) and code in ('application_not_started','application_closed','operation_ended','not_currently_accepting','program_ended')) and code not in
 ('category_unresolved','delivery_mode_unknown','activity_region_unknown','application_period_unknown','operation_period_unknown','application_state_unknown','online_residence_unknown') and code not like 'content_filter:%') into codes;
 else codes:='{}';end if;
 if f->>'productType' not in ('event_program','policy_reference','living_guide') then return array_append(codes,'classification_missing_facts');end if;
 select to_jsonb(gate) into g from machimoa_review.evaluate_source_item_gates(s.body_usable or machimoa_review.myseoul_review_body_ready(p_id,s.revision_hash),s.has_source_url,s.attachment_present,f->>'productType','{}',machimoa_review.classification_gate(f)) gate;
 select filters into d from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=s.revision_hash;
 if (d is null or d->>'category' is distinct from f->>'category') and f->>'category' in ('program','event','youth_space') then d:=machimoa_review.classification_draft(p_id,f->>'category')->'filters';end if;
 venue_mode:=f->>'productType'='event_program' and f->>'category' in ('program','event','youth_space') and f->>'delivery' in ('offline','hybrid') and (f->>'category'<>'youth_space' or d->'spaceKind'->>'value' is distinct from 'news');
 if venue_mode then
 select filters into d from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=s.revision_hash;
 if d is null or d->>'category' is distinct from f->>'category' then d:=machimoa_review.classification_draft(p_id,f->>'category')->'filters';end if;
 venue_ready:=d->'location'->>'status'='known' and (d->'location'->'value'->>'scope'='nationwide' or d->'location'->'value'->>'scope'='specific' and jsonb_array_length(d->'location'->'value'->'venues')>0 and not exists(select 1 from jsonb_array_elements(d->'location'->'value'->'venues') x where x->>'province' not in ('11','28','41')));
 if coalesce(venue_ready,false) is not true then codes:=array_append(codes,'activity_region_unknown');end if;
 end if;
 codes:=codes||array(select code from jsonb_array_elements(coalesce(g->'jobs','[]')) job cross join lateral jsonb_array_elements_text(job->'reason_codes') code where not (venue_mode and coalesce(venue_ready,false) and code='region_scope_unknown'));
 if g->>'disposition'<>'target' and cardinality(codes)=0 and not (venue_mode and coalesce(venue_ready,false) and g->>'disposition'='region_review_required' and g->>'region_status'='review_required' and g->>'audience_status'='not_applicable') then codes:=array_append(codes,'classification_scope_unresolved');end if;
 return array(select distinct c from unnest(codes) c);
end $function$
;

CREATE OR REPLACE FUNCTION public.claim_seoul_program_ai(p_source_item_id uuid, p_revision text, p_worker_id text, p_lease_seconds integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 j machimoa_review.processing_jobs%rowtype; v_now timestamptz;
begin
 if p_source_item_id is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or
 p_worker_id is null or char_length(btrim(p_worker_id)) not between 1 and 128 or p_worker_id<>btrim(p_worker_id) or
 p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 -- Direct target selection; a different source/job cannot win this claim.
 select * into s from machimoa_review.source_items where id=p_source_item_id and source_id='seoul_reservation' for update skip locked;
 if not found then return '[]'::jsonb;end if;
 -- Recover expired attempts even when gate is now closed. A queued row is not
 -- execution permission; the gate below remains authoritative. This prevents
 -- an abandoned claim from permanently blocking program refresh/admin edits.
 update machimoa_review.processing_jobs set status='queued',claimed_at=null,claimed_by=null,claim_lease_until=null
 where source_item_id=s.id and processing_stage='ai_enrichment' and status='claimed' and claim_lease_until<=clock_timestamp();
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision;
 if not found then return '[]'::jsonb;end if;
 begin perform machimoa_review.program_ai_check(s.id,p_revision,f.facts_version);
 exception when sqlstate 'PT409' then return '[]'::jsonb;end;
 if exists(select 1 from machimoa_review.curation_candidates where source='seoul_reservation'
 and source_item_id=s.external_key and source_revision_hash=p_revision) then return '[]'::jsonb;end if;
 v_now:=clock_timestamp();
 select * into j from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage='ai_enrichment' and ((status='queued' and available_at<=v_now and (next_retry_at is null or next_retry_at<=v_now))
 or (status='claimed' and claim_lease_until<=v_now)) for update skip locked;
 if not found then return '[]'::jsonb;end if;
 update machimoa_review.processing_jobs set status='claimed',claimed_at=v_now,
 claimed_by=p_worker_id,claim_lease_until=v_now+make_interval(secs=>p_lease_seconds) where id=j.id returning * into j;
 return jsonb_build_array(jsonb_build_object('jobId',j.id,'sourceItemId',s.id,'source','seoul_reservation',
 'externalKey',s.external_key,'revision',p_revision,'schema',f.schema_version,'profile',f.evaluated_profile,
 'factsVersion',f.facts_version,'title',s.min_fields->>'title','apiCategory','문화체험',
 'activityConfirmation',case when machimoa_review.seoul_activity_confirmed(s.id,p_revision) then jsonb_build_object('confirmed',true,'sourceItemId',s.id,'revision',p_revision,'factsVersion',f.facts_version,'filterVersion',(machimoa_review.content_filter_claim_context(j.id,j.claimed_at)->>'filterVersion')::bigint,'jobId',j.id,'claimedAt',j.claimed_at,'leaseUntil',j.claim_lease_until,'workerId',p_worker_id) else null end,
 'filterContext',machimoa_review.content_filter_claim_context(j.id,j.claimed_at),'facts',f.facts,'observedFacts',f.observed_facts,'claimedAt',j.claimed_at,'leaseUntil',j.claim_lease_until,'workerId',p_worker_id));
end $function$
;


alter function public.admin_program_detail(uuid) rename to seoul_base_admin_program_detail;
alter function public.seoul_base_admin_program_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.seoul_base_admin_program_detail(uuid) from public,anon,authenticated,service_role;
create function public.admin_program_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare item jsonb;begin
 item:=machimoa_review.seoul_base_admin_program_detail(p_id);
 return item||jsonb_build_object('activityReview',jsonb_build_object('supported',true,
 'confirmed',machimoa_review.seoul_activity_confirmed(p_id,item->>'revision'),
 'pending',(item->'result'->'reasons') ? 'activity_location_unknown'));
end $$;

create function public.admin_program_activity_confirm(p_id uuid,p_revision text,p_version text,p_facts_version bigint,
 p_filter_version bigint,p_filters jsonb,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;f machimoa_review.source_item_program_facts%rowtype;
 cf machimoa_review.source_item_content_filters%rowtype;item jsonb;d jsonb;next_f jsonb;mode text;ev bigint;
begin
 if p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$'
 or p_facts_version is null or p_filter_version is null or char_length(btrim(coalesce(p_note,''))) not between 1 and 4000
 or p_filters is null or jsonb_typeof(p_filters)<>'object' or octet_length(p_filters::text)>120000
 or not p_filters ? 'location' or exists(select 1 from jsonb_object_keys(p_filters) k where k not in ('location','delivery'))
 then raise sqlstate 'PT422' using message='invalid_program_confirmation';end if;
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise sqlstate 'PT404' using message='program_not_found';end if;
 if s.revision_hash<>p_revision then raise sqlstate 'PT409' using message='source_revision_conflict';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 item:=public.admin_program_detail(p_id);
 if item->>'version' is distinct from p_version or f.facts_version is distinct from p_facts_version then raise sqlstate 'PT409' using message='program_version_conflict';end if;
 if item->>'status'<>'open' or f.manual_excluded or exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed')
 or exists(select 1 from machimoa_review.curation_candidates where source='seoul_reservation' and source_item_id=s.external_key)
 or exists(select 1 from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision)
 or machimoa_review.admin_trash_pending(p_id,p_revision)
 then raise sqlstate 'PT409' using message='program_confirmation_boundary';end if;
 if not (item->'activityReview'->>'pending')::boolean then raise sqlstate 'PT409' using message='program_confirmation_not_pending';end if;
 select * into cf from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision for update;
 if not found or cf.filter_version is distinct from p_filter_version then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
 d:=cf.data||p_filters;perform machimoa_review.content_filter_validate(d);
 if d->>'category'<>'program' or d->>'category' is distinct from machimoa_review.content_filter_category(p_id,p_revision)
 or d->'location'->>'status'<>'known' or d->'location'->'value'->>'scope'<>'specific'
 or jsonb_array_length(d->'location'->'value'->'venues')=0
 or exists(select 1 from jsonb_array_elements(d->'location'->'value'->'venues') v where v->>'province' not in ('11','28','41'))
 or d->'delivery'->>'status'<>'known' or d->'delivery'->>'value' not in ('onsite','mixed')
 or f.facts->>'activity_region' not in ('capital','unknown') or f.facts->>'delivery_mode'='online'
 then raise sqlstate 'PT422' using message='program_confirmation_capital_required';end if;
 mode:=case d->'delivery'->>'value' when 'onsite' then 'offline' else 'hybrid' end;
 if f.facts->>'delivery_mode' not in ('unknown',mode) then raise sqlstate 'PT422' using message='program_confirmation_delivery_conflict';end if;
 next_f:=f.facts||jsonb_build_object('delivery_mode',mode,'activity_region','capital');
 next_f:=jsonb_set(next_f,'{missing}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_f->'missing') where value#>>'{}'<>'activity_location_unknown'),'[]'));
 -- Conflicting source assertions remain pending; confirmation cannot erase them.
 perform machimoa_review.program_validate(next_f);
 update machimoa_review.source_item_program_facts set facts=next_f,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 if not machimoa_review.content_filter_consistent(p_id,p_revision,d) then raise sqlstate 'PT422' using message='content_filter_facts_mismatch';end if;
 update machimoa_review.source_item_content_filters set data=d,filter_version=filter_version+1,
 source_binding=machimoa_review.content_filter_binding(p_id,p_revision),origins=origins||'{"location":"operator","delivery":"operator"}'::jsonb,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.content_filter_edits(source_item_id,revision_hash,filter_version,actor,origin,fields,before_data,after_data)
 values(p_id,p_revision,cf.filter_version+1,p_actor,'operator',array['location','delivery'],cf.data,d);
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,p_note,array['confirmed:activity_region']) returning id into ev;
 insert into machimoa_review.seoul_activity_confirmations values(ev,p_id,p_revision,f.facts_version,f.facts_version+1,cf.filter_version+1,
 machimoa_review.seoul_activity_binding(next_f,d),jsonb_build_object('revision',p_revision,'officialUrl',s.normalized_payload->'source_url'));
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $$;

-- Shares the sync-row lock with EVERY observation writer, before testing keys.
-- No preflight+upsert race and no existing item/job/fact/candidate writes.
create function public.observe_seoul_program_new_only(p_run_id uuid,p_items jsonb,p_next_checkpoint jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare st machimoa_review.source_sync_state%rowtype;entry jsonb;new_items jsonb:='[]';raw_result jsonb;
 outcomes jsonb:='[]';sid uuid;rev text;idx integer:=0;r jsonb;
begin
 if p_run_id is null or p_items is null or jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items)>40 or octet_length(p_items::text)>1000000
 then raise sqlstate 'PT422' using message='program_batch_invalid';end if;
 select * into st from machimoa_review.source_sync_state where source_id='seoul_reservation' for update;
 if not found or st.active_run_id is distinct from p_run_id or st.lease_owner is distinct from p_run_id or st.lease_expires_at is null or st.lease_expires_at<=clock_timestamp()
 or not exists(select 1 from machimoa_review.ingest_runs where id=p_run_id and source_id='seoul_reservation' and status='running')
 then raise sqlstate 'PT409' using message='lease_lost';end if;
 if (select count(distinct value->>'external_key') from jsonb_array_elements(p_items))<>jsonb_array_length(p_items)
 then raise sqlstate 'PT422' using message='duplicate_program_id';end if;
 for entry in select value from jsonb_array_elements(p_items) loop
 if jsonb_typeof(entry)<>'object' or coalesce(entry->>'external_key','') !~ '^[A-Za-z0-9_-]{1,128}$'
 or entry->'normalized_payload'->>'source_id' is distinct from 'seoul_reservation'
 or entry->'normalized_payload'->'provider_fields'->>'MAXCLASSNM' is distinct from '문화체험'
 then raise sqlstate 'PT422' using message='invalid_program_observation';end if;
 select id,revision_hash into sid,rev from machimoa_review.source_items where source_id='seoul_reservation' and external_key=entry->>'external_key';
 if found then outcomes:=outcomes||jsonb_build_array(jsonb_build_object('inputIndex',idx,'externalKey',entry->>'external_key','id',sid,'revision',rev,'outcome','existing_skipped'));
 else new_items:=new_items||jsonb_build_array(entry);end if;idx:=idx+1;
 end loop;
 if jsonb_array_length(new_items)>0 then
 raw_result:=public.observe_seoul_program(p_run_id,new_items,p_next_checkpoint);
 for r in select value from jsonb_array_elements(raw_result) loop
 if r->>'outcome' is distinct from 'new' then raise sqlstate 'PT409' using message='program_new_only_race';end if;
 select id into sid from machimoa_review.source_items where id=(r->>'id')::uuid;
 outcomes:=outcomes||jsonb_build_array(r||jsonb_build_object('outcome','new_saved',
 'externalKey',(select external_key from machimoa_review.source_items where id=sid),
 'inputIndex',(select (ordinality-1)::integer from jsonb_array_elements(p_items) with ordinality where value->>'external_key'=(select external_key from machimoa_review.source_items where id=sid)),
 'reviewWaiting',exists(select 1 from machimoa_review.processing_jobs where source_item_id=sid and processing_stage='content_review' and status='queued'),
 'aiWaiting',exists(select 1 from machimoa_review.processing_jobs where source_item_id=sid and processing_stage='ai_enrichment' and status='queued')));
 end loop;
 else perform * from machimoa_review.upsert_source_observations('seoul_reservation',p_run_id,'[]'::jsonb,p_next_checkpoint);end if;
 return coalesce((select jsonb_agg(value order by (value->>'inputIndex')::integer) from jsonb_array_elements(outcomes)),'[]');
end $$;
create function public.seoul_collection_contract() returns jsonb
language sql immutable security definer set search_path='' as $$
 select '{"contract":"seoul-new-only-v1","maxBatch":40,"category":"문화체험"}'::jsonb;
$$;

revoke all on function machimoa_review.seoul_activity_binding(jsonb,jsonb) from public,anon,authenticated,service_role;

revoke all on function machimoa_review.seoul_activity_confirmed(uuid,text) from public,anon,authenticated,service_role;

revoke all on function machimoa_review.program_evaluate_with_confirmation(jsonb,timestamp with time zone,boolean) from public,anon,authenticated,service_role;

revoke all on function machimoa_review.program_evaluate_reviewed(jsonb,timestamp with time zone,uuid,text) from public,anon,authenticated,service_role;

revoke all on function public.admin_program_detail(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_program_detail(uuid) to service_role;

revoke all on function public.admin_program_activity_confirm(uuid,text,text,bigint,bigint,jsonb,text,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_program_activity_confirm(uuid,text,text,bigint,bigint,jsonb,text,uuid) to service_role;

revoke all on function public.observe_seoul_program_new_only(uuid,jsonb,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.observe_seoul_program_new_only(uuid,jsonb,jsonb) to service_role;

revoke all on function public.seoul_collection_contract() from public,anon,authenticated,service_role;
grant execute on function public.seoul_collection_contract() to service_role;

notify pgrst,'reload schema';
commit;
