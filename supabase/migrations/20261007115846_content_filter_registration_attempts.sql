-- Local follow-up: explicit deferred enrollment, generic start retention, fenced terminal failure.
-- No backfill, source state changes, jobs creation or legacy enrollment in migration.
begin;
set local lock_timeout='5s';set local statement_timeout='30s';
do $$ declare r record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values
('machimoa_review.content_filter_observe(text,jsonb,jsonb)','5cbcfd3e088e6e651b635086b4fdb58f9dec99e21f141f762debc6891b363ca7','{postgres=X/postgres}'),
('machimoa_review.content_filter_after_facts(uuid,text)','2a23baec185282870e7ff0c37d1946e48aa145b68e3888d10fbd90f263d6ab54','{postgres=X/postgres}'),
('machimoa_review.content_filter_ready(uuid,text)','f297c92c8afd9a9a6d2623539529119aef379cce1ef9768cbe8fbb6e690505fd','{postgres=X/postgres}'),
('machimoa_review.content_filter_consistent(uuid,text,jsonb)','9f17ad7c684894a7d26e850da542a4d0290d58ad786faa6d1dadb4cd747d16b8','{postgres=X/postgres}'),
('machimoa_review.claim_processing_jobs(text,integer,text,integer)','f83a95ce5f6eb52b0b2c9c787fe04b2b8e2bcd08b1dbbcd25d4052a12446643f','{postgres=X/postgres}'),
('public.observe_myseoul_program(uuid,jsonb,jsonb)','e6f1a3b9cee7e7b06b1171bc5df2740e14c64e81b8709ffea5a84b09315f6bd9','{postgres=X/postgres,service_role=X/postgres}'),
('public.observe_seoul_program(uuid,jsonb,jsonb)','55b44e4a34b777e43094545975f046561cc31906bdb9a23a17984a10efde702d','{postgres=X/postgres,service_role=X/postgres}'),
('public.upsert_source_observations_v4(text,uuid,jsonb,jsonb)','f9880ca576c0ce825d93f19f3d7224c44816765d020839e5ba7a9dfd013b1111','{postgres=X/postgres,service_role=X/postgres}')
) v(name,hash,acl) loop
 if to_regprocedure(r.name) is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure(r.name)),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash then raise exception 'content_filter_gap_predecessor_changed: %',r.name;end if;
 if (select proacl::text from pg_proc where oid=to_regprocedure(r.name)) is distinct from r.acl then raise exception 'content_filter_gap_predecessor_acl_changed: %',r.name;end if;
 end loop;end $$;
create table machimoa_review.content_filter_gap_backup(name text primary key,definition text not null,acl text,installed text,installed_acl text);
alter table machimoa_review.content_filter_gap_backup enable row level security;
revoke all on machimoa_review.content_filter_gap_backup from public,anon,authenticated,service_role;
insert into machimoa_review.content_filter_gap_backup(name,definition,acl) select 'machimoa_review.content_filter_observe(text,jsonb,jsonb)',pg_get_functiondef(oid),proacl::text from pg_proc where oid='machimoa_review.content_filter_observe(text,jsonb,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_gap_backup(name,definition,acl) select 'machimoa_review.content_filter_after_facts(uuid,text)',pg_get_functiondef(oid),proacl::text from pg_proc where oid='machimoa_review.content_filter_after_facts(uuid,text)'::regprocedure;
insert into machimoa_review.content_filter_gap_backup(name,definition,acl) select 'machimoa_review.content_filter_ready(uuid,text)',pg_get_functiondef(oid),proacl::text from pg_proc where oid='machimoa_review.content_filter_ready(uuid,text)'::regprocedure;
insert into machimoa_review.content_filter_gap_backup(name,definition,acl) select 'machimoa_review.content_filter_consistent(uuid,text,jsonb)',pg_get_functiondef(oid),proacl::text from pg_proc where oid='machimoa_review.content_filter_consistent(uuid,text,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_gap_backup(name,definition,acl) select 'machimoa_review.claim_processing_jobs(text,integer,text,integer)',pg_get_functiondef(oid),proacl::text from pg_proc where oid='machimoa_review.claim_processing_jobs(text,integer,text,integer)'::regprocedure;
insert into machimoa_review.content_filter_gap_backup(name,definition,acl) select 'public.observe_myseoul_program(uuid,jsonb,jsonb)',pg_get_functiondef(oid),proacl::text from pg_proc where oid='public.observe_myseoul_program(uuid,jsonb,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_gap_backup(name,definition,acl) select 'public.observe_seoul_program(uuid,jsonb,jsonb)',pg_get_functiondef(oid),proacl::text from pg_proc where oid='public.observe_seoul_program(uuid,jsonb,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_gap_backup(name,definition,acl) select 'public.upsert_source_observations_v4(text,uuid,jsonb,jsonb)',pg_get_functiondef(oid),proacl::text from pg_proc where oid='public.upsert_source_observations_v4(text,uuid,jsonb,jsonb)'::regprocedure;
create table machimoa_review.content_filter_enrollments(
 source_item_id uuid not null references machimoa_review.source_items(id),revision_hash text not null,
 schema_version text not null default 'content-filters-v1' check(schema_version='content-filters-v1'),
 created_at timestamptz not null default clock_timestamp(),primary key(source_item_id,revision_hash)
);
alter table machimoa_review.content_filter_enrollments enable row level security;
revoke all on machimoa_review.content_filter_enrollments from public,anon,authenticated,service_role;

create function machimoa_review.content_filter_register_pending(p_id uuid,p_revision text) returns void
language plpgsql set search_path='' as $$
declare s machimoa_review.source_items%rowtype;cat text;d jsonb;k text;values_v jsonb;origins_v jsonb:='{}';version_v bigint;
begin
 select * into s from machimoa_review.source_items where id=p_id and revision_hash=p_revision for update;
 if not found or not exists(select 1 from machimoa_review.content_filter_enrollments where source_item_id=p_id and revision_hash=p_revision) or exists(select 1 from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision) then return;end if;
 cat:=machimoa_review.content_filter_category(p_id,p_revision);
 if cat is null or cat not in ('program','event','youth_space') then return;end if;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed' and (claim_lease_until is null or claim_lease_until>clock_timestamp())) then raise sqlstate 'PT409' using message='content_filter_processing_active';end if;
 d:=jsonb_build_object('schema','content-filters-v1','category',cat);
 for k in select unnest(array['topic','location','delivery','audience','spaceKind','application','schedule']) loop
 d:=d||jsonb_build_object(k,jsonb_build_object('status',case when (cat='program' and k in ('spaceKind','schedule')) or (cat='event' and k in ('delivery','audience','spaceKind','application')) or (cat='youth_space' and k in ('topic','delivery','audience','application','schedule')) then 'not_applicable' else 'unknown' end,'value',null));
 origins_v:=origins_v||jsonb_build_object(k,'source_change');end loop;
 select coalesce(max(filter_version),0)+1 into version_v from machimoa_review.source_item_content_filters where source_item_id=p_id;
 insert into machimoa_review.source_item_content_filters(source_item_id,revision_hash,filter_version,data,observed_data,origins,evidence,source_binding)
 values(p_id,p_revision,version_v,d,d,origins_v,'{}',machimoa_review.content_filter_binding(p_id,p_revision));
 values_v:=machimoa_review.content_filter_fact_values(p_id,p_revision);
 if cat='program' then
 for k in select jsonb_object_keys(values_v) loop
 d:=jsonb_set(d,array[k],jsonb_build_object('status','known','value',values_v->k));origins_v:=origins_v||jsonb_build_object(k,'confirmed_facts');end loop;
 if d->'delivery'->>'value'='online' then d:=jsonb_set(d,array['location'],jsonb_build_object('status','not_applicable','value',null));end if;end if;
 perform machimoa_review.content_filter_validate(d);
 update machimoa_review.source_item_content_filters set data=d,origins=origins_v where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.content_filter_edits(source_item_id,revision_hash,filter_version,origin,fields,after_data)
 values(p_id,p_revision,version_v,'source_change',array['deferred_registration'],d);
 perform machimoa_review.content_filter_review_sync(p_id,p_revision);
end $$;
revoke all on function machimoa_review.content_filter_register_pending(uuid,text) from public,anon,authenticated,service_role;

create function public.fail_content_filter_ai(p_job_id uuid,p_revision text,p_filter_version bigint,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_error_code text) returns text
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;m machimoa_review.content_filter_claim_inputs%rowtype;
begin
 if p_error_code is null or p_error_code not in ('ai_or_enqueue_failed','ai_blocked_cost_cap','ai_cost_bound_breach','ai_refusal','ai_schema_error','ai_timeout','ai_network','ai_http_400','ai_http_401','ai_http_403','ai_http_404','ai_http_429','ai_http_4xx','ai_http_5xx','ai_unexpected_thinking','ai_call_budget','ai_sampling_forbidden') then raise sqlstate 'PT422' using message='invalid_ai_error_code';end if;
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs job on job.source_item_id=si.id where job.id=p_job_id for update of si;
 if not found or s.source_id not in ('youthcenter_content','youthcenter_policy') then raise sqlstate 'PT409' using message='content_filter_identity_changed';end if;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 select * into m from machimoa_review.content_filter_claim_inputs where job_id=p_job_id and claimed_at=p_claimed_at;
 if j.processing_stage<>'ai_enrichment' or j.revision_hash is distinct from p_revision or m.job_id is null or m.revision_hash is distinct from p_revision or m.source_item_id is distinct from s.id or m.filter_version is distinct from p_filter_version or m.worker_id is distinct from p_worker_id or m.lease_until is distinct from p_lease_until then raise sqlstate 'PT409' using message='content_filter_fence_lost';end if;
 if j.status='failed' and j.error_code=p_error_code then return 'failed';end if;
 if j.status<>'claimed' or j.claimed_at is distinct from p_claimed_at or j.claimed_by is distinct from p_worker_id or j.claim_lease_until is distinct from p_lease_until or j.claim_lease_until<=clock_timestamp() then raise sqlstate 'PT409' using message='content_filter_fence_lost';end if;
 update machimoa_review.processing_jobs set status='failed',error_code=p_error_code,retry_count=retry_count+1,next_retry_at=null,claimed_by=null,claim_lease_until=null where id=j.id;
 return 'failed';
end $$;
revoke all on function public.fail_content_filter_ai(uuid,text,bigint,timestamptz,timestamptz,text,text) from public,anon,authenticated;
grant execute on function public.fail_content_filter_ai(uuid,text,bigint,timestamptz,timestamptz,text,text) to service_role;

CREATE OR REPLACE FUNCTION machimoa_review.content_filter_observe(p_source text, p_items jsonb, p_outcomes jsonb DEFAULT NULL::jsonb)
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare item jsonb;sid uuid;s machimoa_review.source_items%rowtype;f machimoa_review.source_item_content_filters%rowtype;
 d jsonb;e jsonb;k text;origin_map jsonb;material text;ref jsonb;current_data jsonb;changed text[];source_facts jsonb;result text;confirmed jsonb;
begin
 for item in select value from jsonb_array_elements(p_items) loop
 if item ? 'filterContract' and (jsonb_typeof(item->'filterContract') is distinct from 'string' or item->>'filterContract'<>'content-filters-v1' or p_source not in ('myseoul_program','seoul_reservation','youthcenter_content')) then raise sqlstate 'PT422' using message='invalid_content_filter_contract';end if;

 select * into s from machimoa_review.source_items where source_id=p_source and external_key=item->>'external_key' and revision_hash=item->>'revision_hash' for update;
 if not found then raise sqlstate 'PT409' using message='content_filter_identity_changed';end if;sid:=s.id;
 if item ? 'filterContract' or item ? 'filterFacts' then
 select value->>'outcome' into result from jsonb_array_elements(coalesce(p_outcomes,'[]')) where value->>'id'=sid::text;
 if result='new' or exists(select 1 from machimoa_review.content_filter_enrollments where source_item_id=sid) or exists(select 1 from machimoa_review.source_item_content_filters where source_item_id=sid) then
 insert into machimoa_review.content_filter_enrollments(source_item_id,revision_hash) values(sid,s.revision_hash) on conflict do nothing;
 end if;end if;
 if not item ? 'filterFacts' and exists(select 1 from machimoa_review.content_filter_enrollments where source_item_id=sid and revision_hash=s.revision_hash) then
 perform machimoa_review.content_filter_register_pending(sid,s.revision_hash);
 if machimoa_review.content_filter_category(sid,s.revision_hash) is null then continue;end if;
 end if;

 if not item ? 'filterFacts' then
 if not exists(select 1 from machimoa_review.source_item_content_filters where source_item_id=sid) or exists(select 1 from machimoa_review.source_item_content_filters where source_item_id=sid and revision_hash=s.revision_hash) then continue;end if;
 d:=jsonb_build_object('schema','content-filters-v1','category',machimoa_review.content_filter_category(sid,s.revision_hash));
 for k in select unnest(array['topic','location','delivery','audience','spaceKind','application','schedule']) loop
 d:=d||jsonb_build_object(k,jsonb_build_object('status',case when (d->>'category'='program' and k in ('spaceKind','schedule')) or (d->>'category'='event' and k in ('delivery','audience','spaceKind','application')) or (d->>'category'='youth_space' and k in ('topic','delivery','audience','application','schedule')) then 'not_applicable' else 'unknown' end,'value',null));end loop;
 item:=item||jsonb_build_object('filterFacts',jsonb_build_object('data',d,'evidence','{}'::jsonb));end if;
 select * into f from machimoa_review.source_item_content_filters where source_item_id=sid and revision_hash=s.revision_hash for update;
 if not found and not exists(select 1 from machimoa_review.source_item_content_filters where source_item_id=sid) then
 select value->>'outcome' into result from jsonb_array_elements(coalesce(p_outcomes,'[]')) where value->>'id'=sid::text;
 if result is distinct from 'new' then continue;end if;end if;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=sid and status='claimed' and (claim_lease_until is null or claim_lease_until>clock_timestamp())) then raise sqlstate 'PT409' using message='content_filter_processing_active';end if;
 if jsonb_typeof(item->'filterFacts') is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(item->'filterFacts') key) is distinct from array['data','evidence'] then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 d:=item->'filterFacts'->'data';e:=item->'filterFacts'->'evidence';perform machimoa_review.content_filter_validate(d);
 -- A proposed category may be retained while the existing category review remains unresolved.
 -- It cannot become ready or authorize AI until the server confirms the same category.
 if (machimoa_review.content_filter_category(sid,s.revision_hash) is not null and d->>'category' is distinct from machimoa_review.content_filter_category(sid,s.revision_hash)) or jsonb_typeof(e) is distinct from 'object' or octet_length(e::text)>12000 then raise sqlstate 'PT422' using message='content_filter_category_changed';end if;
 if exists(select 1 from jsonb_object_keys(e) key where key not in ('topic','location','delivery','audience','spaceKind','application','schedule')) then raise sqlstate 'PT422' using message='invalid_content_filter_evidence';end if;
 select observed_facts into source_facts from machimoa_review.source_item_program_facts where source_item_id=sid and revision_hash=s.revision_hash;
 origin_map:='{}';
 for k in select key from jsonb_each(d-'schema'-'category') loop
 origin_map:=origin_map||jsonb_build_object(k,'automatic');
 if d->k->>'status'='known' then
 ref:=e->k;
 if ref is null or jsonb_typeof(ref) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(ref) key) is distinct from array['excerpt','sourceField'] or jsonb_typeof(ref->'sourceField') is distinct from 'string' or jsonb_typeof(ref->'excerpt') is distinct from 'string' or char_length(ref->>'excerpt') not between 1 and 1000 or (ref->>'excerpt')~'[<>]' then raise sqlstate 'PT422' using message='invalid_content_filter_evidence';end if;
 material:=case when left(ref->>'sourceField',6)='facts.' then source_facts->>substring(ref->>'sourceField',7) when left(ref->>'sourceField',8)='payload.' then s.normalized_payload->>substring(ref->>'sourceField',9) else null end;
 if material is null or strpos(material,ref->>'excerpt')=0 then raise sqlstate 'PT422' using message='invalid_content_filter_evidence';end if;
 end if;end loop;
 current_data:=d;confirmed:=machimoa_review.content_filter_fact_values(sid,s.revision_hash);
 if d->>'category'='program' then
 for k in select jsonb_object_keys(confirmed) loop
 if d->k->>'status'='unknown' then current_data:=jsonb_set(current_data,array[k],jsonb_build_object('status','known','value',confirmed->k));origin_map:=jsonb_set(origin_map,array[k],to_jsonb('confirmed_facts'::text));end if;end loop;
 if current_data->'delivery'->>'value'='online' then current_data:=jsonb_set(current_data,array['location'],jsonb_build_object('status','not_applicable','value',null));end if;end if;
 if f.source_item_id is not null then
 for k in select key from jsonb_each(d-'schema'-'category') loop
 if f.origins->>k='operator' then current_data:=jsonb_set(current_data,array[k],f.data->k);origin_map:=jsonb_set(origin_map,array[k],to_jsonb('operator'::text));end if;end loop;
 perform machimoa_review.content_filter_validate(current_data);
 if f.observed_data=d then continue;end if;
 end if;
 perform machimoa_review.content_filter_validate(current_data);
 if not machimoa_review.content_filter_consistent(sid,s.revision_hash,current_data) then raise sqlstate 'PT422' using message='content_filter_facts_mismatch';end if;
 insert into machimoa_review.source_item_content_filters(source_item_id,revision_hash,data,observed_data,origins,evidence,source_binding)
 values(sid,s.revision_hash,current_data,d,origin_map,e,machimoa_review.content_filter_binding(sid,s.revision_hash))
 on conflict(source_item_id,revision_hash) do update set data=excluded.data,observed_data=excluded.observed_data,origins=excluded.origins,evidence=excluded.evidence,filter_version=machimoa_review.source_item_content_filters.filter_version+1,updated_at=clock_timestamp();
 insert into machimoa_review.content_filter_edits(source_item_id,revision_hash,filter_version,origin,fields,before_data,after_data)
 select sid,s.revision_hash,filter_version,'automatic',array['initial_observation'],f.data,data from machimoa_review.source_item_content_filters where source_item_id=sid and revision_hash=s.revision_hash;
 perform machimoa_review.content_filter_review_sync(sid,s.revision_hash);
 perform machimoa_review.content_filter_register_pending(sid,s.revision_hash);
 end loop;
end $function$
;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_after_facts(p_id uuid, p_revision text)
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare f machimoa_review.source_item_content_filters%rowtype;b jsonb;d jsonb;k text;fields text[]:='{}';cat text;confirmed jsonb;derived_origins jsonb:='{}';
begin
 select * into f from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision for update;
 if not found then
 perform machimoa_review.content_filter_register_pending(p_id,p_revision);
 select * into f from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision for update;
 if not found then return;end if;end if;b:=machimoa_review.content_filter_binding(p_id,p_revision);d:=f.data;cat:=b->>'category';
 if cat is distinct from d->>'category' then
 if cat not in ('program','event','youth_space') or cat is null then return;end if;
 d:=jsonb_build_object('schema','content-filters-v1','category',cat);
 for k in select unnest(array['topic','location','delivery','audience','spaceKind','application','schedule']) loop
 d:=d||jsonb_build_object(k,jsonb_build_object('status',case when (cat='program' and k in ('spaceKind','schedule')) or (cat='event' and k in ('delivery','audience','spaceKind','application')) or (cat='youth_space' and k in ('topic','delivery','audience','application','schedule')) then 'not_applicable' else 'unknown' end,'value',null));end loop;fields:=array['category'];
 else
 for k in select key from jsonb_each(b-'category') loop
 if b->k is distinct from f.source_binding->k and d->k->>'status'<>'not_applicable' then d:=jsonb_set(d,array[k],jsonb_build_object('status','unknown','value',null));fields:=array_append(fields,k);end if;end loop;
 -- A changed delivery mode requires a fresh location decision without inventing it.
 if 'delivery'=any(fields) and d->'location'->>'status'='not_applicable' then d:=jsonb_set(d,array['location'],jsonb_build_object('status','unknown','value',null));fields:=array_append(fields,'location');end if;
 end if;
 if d->>'category'='program' then
 confirmed:=machimoa_review.content_filter_fact_values(p_id,p_revision);
 for k in select jsonb_object_keys(confirmed) loop
 if d->k->>'status'='unknown' then -- Preserve a separately confirmed start while the authoritative deadline is unchanged.
 if k='application' and (select source_id from machimoa_review.source_items where id=p_id) in ('youthcenter_content','youthcenter_policy') and f.data->'application'->>'status'='known' and confirmed->k->'start'='null'::jsonb and confirmed->k->'end'=f.data->k->'value'->'end' then confirmed:=jsonb_set(confirmed,array[k,'start'],f.data->k->'value'->'start');end if;
 d:=jsonb_set(d,array[k],jsonb_build_object('status','known','value',confirmed->k));derived_origins:=derived_origins||jsonb_build_object(k,'confirmed_facts');end if;end loop;
 if d->'delivery'->>'value'='online' then d:=jsonb_set(d,array['location'],jsonb_build_object('status','not_applicable','value',null));end if;end if;
 if b is distinct from f.source_binding then
 update machimoa_review.source_item_content_filters set data=d,source_binding=b,origins=origins||coalesce((select jsonb_object_agg(field_key,'source_change') from unnest(array['topic','location','delivery','audience','spaceKind','application','schedule']) field_key where field_key=any(fields) or 'category'=any(fields)),'{}'::jsonb)||derived_origins,filter_version=filter_version+1,updated_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.content_filter_edits(source_item_id,revision_hash,filter_version,origin,fields,before_data,after_data)
 select p_id,p_revision,filter_version,'source_change',fields,f.data,d from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision;end if;
 perform machimoa_review.content_filter_review_sync(p_id,p_revision);
end $function$
;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_ready(p_id uuid, p_revision text)
 RETURNS boolean
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
 select case when not exists(select 1 from machimoa_review.source_item_content_filters where source_item_id=p_id) then coalesce(not exists(select 1 from machimoa_review.content_filter_enrollments e where e.source_item_id=p_id) or machimoa_review.content_filter_category(p_id,p_revision) in ('policy','living'),false) else coalesce((select cardinality(machimoa_review.content_filter_missing(f.data))=0 and s.revision_hash=p_revision and f.source_binding=machimoa_review.content_filter_binding(p_id,p_revision) and machimoa_review.content_filter_consistent(p_id,p_revision,f.data)
 and f.data->>'category'=machimoa_review.content_filter_category(p_id,p_revision) from machimoa_review.source_item_content_filters f join machimoa_review.source_items s on s.id=f.source_item_id where source_item_id=p_id and f.revision_hash=p_revision),false) end
$function$
;
CREATE OR REPLACE FUNCTION machimoa_review.content_filter_consistent(p_id uuid, p_revision text, d jsonb)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE
 SET search_path TO ''
AS $function$
declare v jsonb:=machimoa_review.content_filter_fact_values(p_id,p_revision);f jsonb;windows jsonb:='[]';op jsonb;ends jsonb;o jsonb;ad date;bd date;covered boolean;
begin
 if d->>'category'='event' and v->>'delivery'='online' then return false;end if;
 if d->>'category'='program' then
 if v ? 'delivery' and d->'delivery'->>'status'='known' and d->'delivery'->>'value' is distinct from v->>'delivery' then return false;end if;
 if v ? 'application' and d->'application'->>'status'='known' and (d->'application'->'value'->'end' is distinct from v->'application'->'end' or ((select source_id from machimoa_review.source_items where id=p_id) not in ('youthcenter_content','youthcenter_policy') or v->'application'->'start' is distinct from 'null'::jsonb) and d->'application'->'value'->'start' is distinct from v->'application'->'start' or (v->'application'->>'sourceStatus'<>'unknown' and d->'application'->'value'->>'sourceStatus' is distinct from v->'application'->>'sourceStatus')) then return false;end if;end if;
 if d->>'category'='event' and d->'schedule'->>'status'='known' then
 select facts into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision;
 if jsonb_typeof(f->'periods'->'operation')='array' then
 for op in select value from jsonb_array_elements(f->'periods'->'operation') where value->>'status'='ok' loop
 ends:=op->'endpoints';if jsonb_array_length(ends)>0 then windows:=windows||jsonb_build_array(jsonb_build_object('start',ends->0,'end',ends->(jsonb_array_length(ends)-1)));end if;end loop;
 else select event_start_on,event_end_on into ad,bd from machimoa_review.source_item_event_periods where source_item_id=p_id and revision_hash=p_revision;
 if ad is not null and bd is not null then windows:=jsonb_build_array(jsonb_build_object('start',jsonb_build_object('value',ad::text,'precision','day'),'end',jsonb_build_object('value',bd::text,'precision','day')));end if;end if;
 for o in select value from jsonb_array_elements(d->'schedule'->'value'->'occurrences') loop
 select exists(select 1 from jsonb_array_elements(windows) w where machimoa_review.content_filter_endpoint(o->'start')>=machimoa_review.content_filter_endpoint(w->'start') and machimoa_review.content_filter_endpoint(o->'end')+case when o->'end'->>'precision'='day' then interval '1 day'-interval '1 microsecond' else interval '0' end<=machimoa_review.content_filter_endpoint(w->'end')+case when w->'end'->>'precision'='day' then interval '1 day'-interval '1 microsecond' else interval '0' end) into covered;
 if not covered then return false;end if;end loop;end if;
 return true;
end $function$
;
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
CREATE OR REPLACE FUNCTION public.observe_myseoul_program(p_run_id uuid, p_items jsonb, p_next_checkpoint jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare filter_items jsonb:=p_items; entry jsonb; r record; sid uuid; existing machimoa_review.source_item_program_facts%rowtype; outcomes jsonb:='[]';previous_rows jsonb:='{}';prior jsonb;incoming_existing text[]:='{}';
begin
 p_items:=(select coalesce(jsonb_agg(value-'filterFacts'-'filterContract'),'[]') from jsonb_array_elements(p_items));
 if p_run_id is null or p_items is null or jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items) not between 1 and 40 then
 raise exception using errcode='PT422',message='invalid_myseoul_batch';end if;
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' for update;
 perform 1 from machimoa_review.source_items where source_id='myseoul_program'
 and external_key in (select value->>'external_key' from jsonb_array_elements(p_items)) order by external_key for update;
 if (select count(distinct value->>'external_key') from jsonb_array_elements(p_items))<>jsonb_array_length(p_items) then
 raise exception using errcode='PT422',message='duplicate_myseoul_id';end if;
 for entry in select value from jsonb_array_elements(p_items) loop
 perform machimoa_review.myseoul_validate(entry->'myseoul_facts');
 if coalesce(entry->>'external_key','') !~ '^[A-F0-9]{32}:[A-F0-9]{32}$' or entry->>'revision_hash' is distinct from entry->'myseoul_facts'->>'source_revision' or
 entry->>'disposition' is distinct from 'observe_only' or entry->'jobs' is distinct from '[]'::jsonb or entry->'relationships' is distinct from '[]'::jsonb or
 (entry->'normalized_payload'->>'center_id')||':'||(entry->'normalized_payload'->>'program_id') is distinct from entry->>'external_key' then
 raise exception using errcode='PT422',message='invalid_myseoul_observation';end if;
 if entry->'normalized_payload'->>'parser_version' is distinct from 'myseoul-html-v2-local' or
 entry->'normalized_payload'->>'revision_contract' is distinct from 'myseoul-semantic-v2' or entry->'normalized_payload'->>'source_language' is distinct from 'ko' or
 entry->'normalized_payload'->>'official_url' is distinct from entry->'myseoul_facts'->>'official_url' or
 entry->'myseoul_facts'->>'official_url' is distinct from 'https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmDetail.do?cntr_no='||split_part(entry->>'external_key',':',1)||'&prgrm_no='||split_part(entry->>'external_key',':',2)||'&lang=ko' then
 raise exception using errcode='PT422',message='myseoul_identity_mismatch';end if;
 select to_jsonb(f) into prior from machimoa_review.source_item_program_facts f join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash where s.source_id='myseoul_program' and s.external_key=entry->>'external_key';
 if prior is not null then previous_rows:=previous_rows||jsonb_build_object(entry->>'external_key',prior);end if;
 select f.* into existing from machimoa_review.source_item_program_facts f join machimoa_review.source_items s on s.id=f.source_item_id
 where s.source_id='myseoul_program' and s.external_key=entry->>'external_key' and f.revision_hash=entry->>'revision_hash';
 if found then incoming_existing:=array_append(incoming_existing,entry->>'external_key');end if;
 if found and (existing.schema_version<>'myseoul-program-facts-v1-local' or existing.evaluated_profile<>'myseoul-program-v1-local'
 or existing.observed_facts->>'parser_version' is distinct from entry->'myseoul_facts'->>'parser_version'
 or existing.observed_facts->>'revision_contract' is distinct from entry->'myseoul_facts'->>'revision_contract') then
 raise exception using errcode='PT409',message='myseoul_contract_conflict';end if;
 end loop;
 for r in select * from machimoa_review.upsert_source_observations('myseoul_program',p_run_id,p_items,p_next_checkpoint) loop
 entry:=p_items->r.input_index;
 select id into sid from machimoa_review.source_items where source_id='myseoul_program' and external_key=r.external_key;
 insert into machimoa_review.source_item_program_facts(source_item_id,revision_hash,schema_version,evaluated_profile,source_snapshot,observed_facts,facts)
 values(sid,entry->>'revision_hash','myseoul-program-facts-v1-local','myseoul-program-v1-local',entry-'myseoul_facts',entry->'myseoul_facts',entry->'myseoul_facts') on conflict do nothing;
 prior:=previous_rows->r.external_key;
 if r.outcome='changed' and prior is not null and not r.external_key=any(incoming_existing) then
 update machimoa_review.source_item_program_facts set facts=machimoa_review.myseoul_merge_facts(entry->'myseoul_facts',prior->'observed_facts',prior->'facts'),
 manual_excluded=(prior->>'manual_excluded')::boolean,updated_by=(prior->>'updated_by')::uuid,updated_at=clock_timestamp()
 where source_item_id=sid and revision_hash=entry->>'revision_hash';end if;
 -- Source reversion must never undo a human service-scope exclusion.
 if r.outcome='changed' and prior is not null and (prior->>'manual_excluded')::boolean then
 update machimoa_review.source_item_program_facts set manual_excluded=true,facts_version=facts_version+1,
 updated_by=(prior->>'updated_by')::uuid,updated_at=clock_timestamp()
 where source_item_id=sid and revision_hash=entry->>'revision_hash' and not manual_excluded;end if;
 perform machimoa_review.myseoul_refresh(sid);
 outcomes:=outcomes||jsonb_build_array(jsonb_build_object('id',sid,'outcome',r.outcome,'revision',entry->>'revision_hash'));
 end loop;perform machimoa_review.content_filter_observe('myseoul_program',filter_items,outcomes);return outcomes;
end $function$
;
CREATE OR REPLACE FUNCTION public.observe_seoul_program(p_run_id uuid, p_items jsonb, p_next_checkpoint jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare filter_items jsonb:=p_items; entry jsonb; r record; sid uuid; outcomes jsonb:='[]';
begin
 p_items:=(select coalesce(jsonb_agg(value-'filterFacts'-'filterContract'),'[]') from jsonb_array_elements(p_items));
 if p_items is null or jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items) not between 1 and 40 then
   raise exception using errcode='PT422',message='program_batch_invalid';end if;
 -- Lease first, then items in stable order, consistent with the base observation contract.
 perform 1 from machimoa_review.source_sync_state where source_id='seoul_reservation' for update;
 perform 1 from machimoa_review.source_items where source_id='seoul_reservation'
 and external_key in (select value->>'external_key' from jsonb_array_elements(p_items)) order by external_key for update;
 if (select count(distinct value->>'external_key') from jsonb_array_elements(p_items))<>jsonb_array_length(p_items) then
   raise exception using errcode='PT422',message='duplicate_program_id';end if;
 for entry in select value from jsonb_array_elements(p_items) loop
   perform machimoa_review.program_validate(entry->'program_facts');
   if entry->>'disposition' is distinct from 'observe_only' or entry->'jobs'<>'[]'::jsonb or entry->'relationships'<>'[]'::jsonb
      or entry->'normalized_payload'->>'source_id' is distinct from 'seoul_reservation' then
     raise exception using errcode='PT422',message='invalid_program_observation';end if;
 end loop;
 for r in select * from machimoa_review.upsert_source_observations('seoul_reservation',p_run_id,p_items,p_next_checkpoint) loop
   entry:=p_items->r.input_index;
   select id into sid from machimoa_review.source_items where source_id='seoul_reservation' and external_key=r.external_key;
   insert into machimoa_review.source_item_program_facts(source_item_id,revision_hash,source_snapshot,observed_facts,facts)
   values(sid,entry->>'revision_hash',entry-'program_facts',entry->'program_facts',entry->'program_facts') on conflict do nothing;
   perform machimoa_review.program_refresh(sid);
   outcomes:=outcomes||jsonb_build_array(jsonb_build_object('id',sid,'outcome',r.outcome,'revision',entry->>'revision_hash'));
 end loop;perform machimoa_review.content_filter_observe('seoul_reservation',filter_items,outcomes);return outcomes;
end $function$
;
CREATE OR REPLACE FUNCTION public.upsert_source_observations_v4(p_source_id text, p_run_id uuid, p_items jsonb, p_next_checkpoint jsonb)
 RETURNS TABLE(input_index integer, external_key text, outcome text, duplicate_in_batch boolean)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare result_rows jsonb;observations jsonb;begin
 select coalesce(jsonb_agg(value-'filterFacts'-'filterContract'),'[]') into observations from jsonb_array_elements(p_items);
 select coalesce(jsonb_agg(to_jsonb(r)),'[]') into result_rows from machimoa_review.cf_base_pub_upsert_source_observations_v4(p_source_id,p_run_id,observations,p_next_checkpoint) r;
 perform machimoa_review.content_filter_observe(p_source_id,p_items,(select coalesce(jsonb_agg(jsonb_build_object('id',s.id,'outcome',r.outcome)),'[]') from jsonb_to_recordset(result_rows) r(external_key text,outcome text) join machimoa_review.source_items s on s.source_id=p_source_id and s.external_key=r.external_key));
 return query select * from jsonb_to_recordset(result_rows) r(input_index integer,external_key text,outcome text,duplicate_in_batch boolean);
end
$function$
;

update machimoa_review.content_filter_gap_backup set installed=pg_get_functiondef(to_regprocedure(name)),installed_acl=(select proacl::text from pg_proc where oid=to_regprocedure(name));
create table machimoa_review.content_filter_gap_installed(name text primary key,definition text not null,acl text);
alter table machimoa_review.content_filter_gap_installed enable row level security;
revoke all on machimoa_review.content_filter_gap_installed from public,anon,authenticated,service_role;
insert into machimoa_review.content_filter_gap_installed select p.oid::regprocedure::text,pg_get_functiondef(p.oid),p.proacl::text from pg_proc p join pg_namespace n on n.oid=p.pronamespace where (n.nspname='machimoa_review' and p.proname='content_filter_register_pending') or (n.nspname='public' and p.proname='fail_content_filter_ai');
notify pgrst,'reload schema';commit;
