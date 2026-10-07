-- Opt-in filter facts. Existing observations/candidates/publications are not enrolled.
-- Filled and guarded by scripts/_local_content_filter_sql_build.py from a NEW isolated DB.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $$ declare r record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values
('public.observe_myseoul_program(uuid,jsonb,jsonb)','6293829634f202f4b42ff684b942e32e48368335f3daa1d949c1d08a9596d11d'),
('public.observe_seoul_program(uuid,jsonb,jsonb)','0c165a151bd0d811dd351e9a74d81e07d14234f3770f4bf13df346892cef2b3d'),
('public.upsert_source_observations_v4(text,uuid,jsonb,jsonb)','8daaf7d88cb22673e1bbf94536b1c1196f74c4de604f182db76395094b7926f7'),
('machimoa_review.claim_processing_jobs(text,integer,text,integer)','1e502670e8c04f7214fb490c248a97a07b984c8ab1d9f460e74045e5c3a373e8'),
('machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)','64fabc5765bd3dac20f7f08eb19c09c0c5f7c64039cca2963ee576badc51498d'),
('machimoa_review.program_ai_check(uuid,text,bigint)','8b9174a624c8078459d445122c8e6dc4891e5d071c0a7e6250209b04f2d666d7'),
('public.claim_myseoul_program_ai(uuid,text,text,integer)','8af6fe138bf1625ad923423c5a5eba05fff9482fe0397f1eca851de8ac68068f'),
('public.finish_myseoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb)','d7dfe6ff0aedb4594b5623bbfdb96e8322c92024b8edbcf2249434a0d66af0b0'),
('public.claim_seoul_program_ai(uuid,text,text,integer)','9f86c46a7654bd5d38f989a0d804ee2e43f02c95a34b8845a23b24807c008f32'),
('public.finish_seoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb)','dec7fcdf96713ef4d2ed1d2ba6fa6ed5532a49b5c45d95ffb35ab08e8f305947'),
('machimoa_review.admin_review_snapshot(text,uuid)','264d4a71b907878b929c7c0c2cec79a631244c9e6c1fd4b4fac3d88ecd48ba09'),
('machimoa_review.admin_review_item(text,uuid)','25455a249af2db7ccede765be4b4a93d6c02e5f58e9f41b17e25834b2a650abe'),
('public.admin_myseoul_program_detail(uuid)','bcb4458e5c85f33a3d641653b3ae7c6c59f07e313a71c3a96c5dbfa2a17a29a9'),
('public.admin_program_detail(uuid)','717b730d199728809237e85b89ec2fcbcf447ae2327b4801b9911c1ef38fa720'),
('machimoa_review.myseoul_refresh(uuid,timestamp with time zone)','8ed99925edc57e2a56656a3054e557af8081178ddd185ec6f5b0a6704089c48f'),
('machimoa_review.program_refresh(uuid,timestamp with time zone)','649276294816793dec490583fbca750f851bec3ee527a2214f81d80e3f2c21a1'),
('public.admin_review_save_facts(uuid,text,text,jsonb,uuid)','03a90e8c65d24b0256a02a106087bc49c70b76a6943b46ff8179b5c36efd9bc7'),
('public.admin_review_save_candidate(uuid,text,text,jsonb,uuid)','a1589818145a5fc748482bb69b7612bc3b05ea8efda9f8bf86e7bf9b9734fd7b'),
('public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid)','f4cb87a9e81d377d5621557416ac2deb3a76b714704dd091d7f417ed2f09d2b1'),
('machimoa_review.publish_curation_candidate(uuid,text,text,boolean)','8c983b5f8110a21cbdac422d647d0e3bd9b9b1398c67ba357c3f348ca571cffb'),
('public.admin_program_list(integer,integer)','8c5611c2b4a2dec70f470aaa0980a2f9ac6727cf0171297e2d26cea10aad910e'),
('public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)','69e1a60c1128672803c532763d05464cfae63d5ee2cc7bd933b3f170da417158')
) v(name,hash) loop
 if to_regprocedure(r.name) is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure(r.name)),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash then raise exception 'content_filter_predecessor_changed: %',r.name;end if;
 end loop;end $$;
create table machimoa_review.content_filter_function_backup(name text primary key,definition text not null,acl text,base_name text,installed text,base_installed text,installed_acl text,base_installed_acl text);
alter table machimoa_review.content_filter_function_backup enable row level security;
revoke all on machimoa_review.content_filter_function_backup from public,anon,authenticated,service_role;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.observe_myseoul_program(uuid,jsonb,jsonb)',pg_get_functiondef('public.observe_myseoul_program(uuid,jsonb,jsonb)'::regprocedure),proacl::text,NULL from pg_proc where oid='public.observe_myseoul_program(uuid,jsonb,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.observe_seoul_program(uuid,jsonb,jsonb)',pg_get_functiondef('public.observe_seoul_program(uuid,jsonb,jsonb)'::regprocedure),proacl::text,NULL from pg_proc where oid='public.observe_seoul_program(uuid,jsonb,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.upsert_source_observations_v4(text,uuid,jsonb,jsonb)',pg_get_functiondef('public.upsert_source_observations_v4(text,uuid,jsonb,jsonb)'::regprocedure),proacl::text,'machimoa_review.cf_base_pub_upsert_source_observations_v4(text,uuid,jsonb,jsonb)' from pg_proc where oid='public.upsert_source_observations_v4(text,uuid,jsonb,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'machimoa_review.claim_processing_jobs(text,integer,text,integer)',pg_get_functiondef('machimoa_review.claim_processing_jobs(text,integer,text,integer)'::regprocedure),proacl::text,NULL from pg_proc where oid='machimoa_review.claim_processing_jobs(text,integer,text,integer)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)',pg_get_functiondef('machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)'::regprocedure),proacl::text,NULL from pg_proc where oid='machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'machimoa_review.program_ai_check(uuid,text,bigint)',pg_get_functiondef('machimoa_review.program_ai_check(uuid,text,bigint)'::regprocedure),proacl::text,NULL from pg_proc where oid='machimoa_review.program_ai_check(uuid,text,bigint)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.claim_myseoul_program_ai(uuid,text,text,integer)',pg_get_functiondef('public.claim_myseoul_program_ai(uuid,text,text,integer)'::regprocedure),proacl::text,NULL from pg_proc where oid='public.claim_myseoul_program_ai(uuid,text,text,integer)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.finish_myseoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb)',pg_get_functiondef('public.finish_myseoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb)'::regprocedure),proacl::text,NULL from pg_proc where oid='public.finish_myseoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.claim_seoul_program_ai(uuid,text,text,integer)',pg_get_functiondef('public.claim_seoul_program_ai(uuid,text,text,integer)'::regprocedure),proacl::text,NULL from pg_proc where oid='public.claim_seoul_program_ai(uuid,text,text,integer)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.finish_seoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb)',pg_get_functiondef('public.finish_seoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb)'::regprocedure),proacl::text,NULL from pg_proc where oid='public.finish_seoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'machimoa_review.admin_review_snapshot(text,uuid)',pg_get_functiondef('machimoa_review.admin_review_snapshot(text,uuid)'::regprocedure),proacl::text,'machimoa_review.cf_base_admin_review_snapshot(text,uuid)' from pg_proc where oid='machimoa_review.admin_review_snapshot(text,uuid)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'machimoa_review.admin_review_item(text,uuid)',pg_get_functiondef('machimoa_review.admin_review_item(text,uuid)'::regprocedure),proacl::text,'machimoa_review.cf_base_admin_review_item(text,uuid)' from pg_proc where oid='machimoa_review.admin_review_item(text,uuid)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.admin_myseoul_program_detail(uuid)',pg_get_functiondef('public.admin_myseoul_program_detail(uuid)'::regprocedure),proacl::text,'machimoa_review.cf_base_pub_admin_myseoul_program_detail(uuid)' from pg_proc where oid='public.admin_myseoul_program_detail(uuid)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.admin_program_detail(uuid)',pg_get_functiondef('public.admin_program_detail(uuid)'::regprocedure),proacl::text,'machimoa_review.cf_base_pub_admin_program_detail(uuid)' from pg_proc where oid='public.admin_program_detail(uuid)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'machimoa_review.myseoul_refresh(uuid,timestamp with time zone)',pg_get_functiondef('machimoa_review.myseoul_refresh(uuid,timestamp with time zone)'::regprocedure),proacl::text,'machimoa_review.cf_base_myseoul_refresh(uuid,timestamp with time zone)' from pg_proc where oid='machimoa_review.myseoul_refresh(uuid,timestamp with time zone)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'machimoa_review.program_refresh(uuid,timestamp with time zone)',pg_get_functiondef('machimoa_review.program_refresh(uuid,timestamp with time zone)'::regprocedure),proacl::text,'machimoa_review.cf_base_program_refresh(uuid,timestamp with time zone)' from pg_proc where oid='machimoa_review.program_refresh(uuid,timestamp with time zone)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.admin_review_save_facts(uuid,text,text,jsonb,uuid)',pg_get_functiondef('public.admin_review_save_facts(uuid,text,text,jsonb,uuid)'::regprocedure),proacl::text,'machimoa_review.cf_base_pub_admin_review_save_facts(uuid,text,text,jsonb,uuid)' from pg_proc where oid='public.admin_review_save_facts(uuid,text,text,jsonb,uuid)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.admin_review_save_candidate(uuid,text,text,jsonb,uuid)',pg_get_functiondef('public.admin_review_save_candidate(uuid,text,text,jsonb,uuid)'::regprocedure),proacl::text,'machimoa_review.cf_base_pub_admin_review_save_candidate(uuid,text,text,jsonb,uuid)' from pg_proc where oid='public.admin_review_save_candidate(uuid,text,text,jsonb,uuid)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid)',pg_get_functiondef('public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid)'::regprocedure),proacl::text,'machimoa_review.cf_base_pub_admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid)' from pg_proc where oid='public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'machimoa_review.publish_curation_candidate(uuid,text,text,boolean)',pg_get_functiondef('machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'::regprocedure),proacl::text,'machimoa_review.cf_base_publish_curation_candidate(uuid,text,text,boolean)' from pg_proc where oid='machimoa_review.publish_curation_candidate(uuid,text,text,boolean)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.admin_program_list(integer,integer)',pg_get_functiondef('public.admin_program_list(integer,integer)'::regprocedure),proacl::text,NULL from pg_proc where oid='public.admin_program_list(integer,integer)'::regprocedure;
insert into machimoa_review.content_filter_function_backup(name,definition,acl,base_name) select 'public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)',pg_get_functiondef('public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)'::regprocedure),proacl::text,'machimoa_review.cf_base_pub_enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)' from pg_proc where oid='public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text)'::regprocedure;

create table machimoa_review.source_item_content_filters (
 source_item_id uuid not null, revision_hash text not null,
 filter_version bigint not null default 1 check(filter_version>0), data jsonb not null,
 observed_data jsonb not null, origins jsonb not null, evidence jsonb not null,
 source_binding jsonb not null, updated_at timestamptz not null default clock_timestamp(),
 primary key(source_item_id,revision_hash),
 foreign key(source_item_id) references machimoa_review.source_items(id)
);
create table machimoa_review.content_filter_edits (
 id uuid primary key default gen_random_uuid(), source_item_id uuid not null, revision_hash text not null,
 filter_version bigint not null, actor uuid, origin text not null check(origin in ('automatic','operator','source_change')),
 fields text[] not null, before_data jsonb, after_data jsonb not null, created_at timestamptz not null default clock_timestamp(),
 foreign key(source_item_id,revision_hash) references machimoa_review.source_item_content_filters(source_item_id,revision_hash)
);
create table machimoa_review.content_filter_claim_inputs (
 job_id uuid not null references machimoa_review.processing_jobs(id), claimed_at timestamptz not null,
 lease_until timestamptz not null, worker_id text not null, source_item_id uuid not null, revision_hash text not null,
 filter_version bigint not null, data jsonb not null, primary key(job_id,claimed_at),
 foreign key(source_item_id,revision_hash) references machimoa_review.source_item_content_filters(source_item_id,revision_hash)
);
create table machimoa_review.candidate_content_filters (
 candidate_id uuid primary key references machimoa_review.curation_candidates(id), source_item_id uuid not null,
 revision_hash text not null, filter_version bigint not null, input_data jsonb not null,
 job_id uuid not null, claimed_at timestamptz not null,
 approved_version bigint not null, approved_revision text not null, approved_data jsonb not null,
 foreign key(job_id,claimed_at) references machimoa_review.content_filter_claim_inputs(job_id,claimed_at)
);
alter table public.curations add column content_filters jsonb;

create function machimoa_review.content_filter_district(p text,d text) returns boolean language sql immutable set search_path='' as $$
 select coalesce(case p when '11' then d=any(array['종로구','중구','용산구','성동구','광진구','동대문구','중랑구','성북구','강북구','도봉구','노원구','은평구','서대문구','마포구','양천구','강서구','구로구','금천구','영등포구','동작구','관악구','서초구','강남구','송파구','강동구']) when '41' then d=any(array['수원시','성남시','의정부시','안양시','부천시','광명시','평택시','동두천시','안산시','고양시','과천시','구리시','남양주시','오산시','시흥시','군포시','의왕시','하남시','용인시','파주시','이천시','안성시','김포시','화성시','광주시','양주시','포천시','여주시','연천군','가평군','양평군']) when '28' then d=any(array['제물포구','영종구','미추홀구','연수구','남동구','부평구','계양구','서구','검단구','강화군','옹진군']) else false end,false)
$$;
create function machimoa_review.content_filter_day(v text) returns date
language plpgsql immutable set search_path='' as $$
declare d date;
begin
 if v is null or v !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' or v<'1900-01-01' or v>'2199-12-31' then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 begin d:=v::date;exception when others then raise sqlstate 'PT422' using message='invalid_content_filters';end;
 if to_char(d,'YYYY-MM-DD')<>v then raise sqlstate 'PT422' using message='invalid_content_filters';end if;return d;
end $$;
create function machimoa_review.content_filter_endpoint(v jsonb) returns timestamptz
language plpgsql immutable set search_path='' as $$
begin
 if jsonb_typeof(v) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(v) key) is distinct from array['precision','value'] or
 jsonb_typeof(v->'value') is distinct from 'string' or v->>'precision' not in ('day','minute','second') or v->>'precision' is null then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 perform machimoa_review.content_filter_day(left(v->>'value',10));
 if v->>'precision'='day' then
 if length(v->>'value')<>10 then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 return ((v->>'value')::date)::timestamp at time zone 'Asia/Seoul';end if;
 if v->>'value' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9][+]09:00$' or
 (v->>'precision'='minute' and substring(v->>'value',18,2)<>'00') then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 return (v->>'value')::timestamptz;
end $$;
create function machimoa_review.content_filter_recurrence(r jsonb) returns jsonb
language plpgsql immutable set search_path='' as $$
declare a date;b date;d date;outcomes jsonb:='[]';unit text;start_v text;end_v text;
begin
 if jsonb_typeof(r) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(r) key) is distinct from array['endTime','exceptions','from','precision','startTime','through','weekdays'] then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 a:=machimoa_review.content_filter_day(r->>'from');b:=machimoa_review.content_filter_day(r->>'through');unit:=r->>'precision';
 if b<a or b-a>730 or unit is null or unit not in ('day','minute','second') or jsonb_typeof(r->'weekdays') is distinct from 'array' or
 jsonb_array_length(r->'weekdays') not between 1 and 7 or exists(select 1 from jsonb_array_elements(r->'weekdays') x where jsonb_typeof(x)<>'number' or x::text !~ '^[0-6]$') or
 (select count(distinct x) from jsonb_array_elements(r->'weekdays') x)<>jsonb_array_length(r->'weekdays') or jsonb_typeof(r->'exceptions') is distinct from 'array' or jsonb_array_length(r->'exceptions')>200 or
 (select count(distinct x) from jsonb_array_elements(r->'exceptions') x)<>jsonb_array_length(r->'exceptions') then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 if unit='day' then
 if r->'startTime' is distinct from 'null'::jsonb or r->'endTime' is distinct from 'null'::jsonb then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 elsif jsonb_typeof(r->'startTime') is distinct from 'string' or jsonb_typeof(r->'endTime') is distinct from 'string' or
 r->>'startTime' !~ (case when unit='minute' then '^([01][0-9]|2[0-3]):[0-5][0-9]$' else '^([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$' end) or
 r->>'endTime' !~ (case when unit='minute' then '^([01][0-9]|2[0-3]):[0-5][0-9]$' else '^([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$' end) or r->>'startTime'>r->>'endTime' then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 for start_v in select value#>>'{}' from jsonb_array_elements(r->'exceptions') loop
 d:=machimoa_review.content_filter_day(start_v);
 if d<a or d>b or not r->'weekdays' @> jsonb_build_array(extract(dow from d)::integer) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;end loop;
 d:=a;while d<=b loop
 if r->'weekdays' @> jsonb_build_array(extract(dow from d)::integer) and not r->'exceptions' @> jsonb_build_array(d::text) then
 start_v:=d::text;end_v:=d::text;
 if unit<>'day' then start_v:=start_v||'T'||(r->>'startTime')||case when unit='minute' then ':00' else '' end||'+09:00';end_v:=end_v||'T'||(r->>'endTime')||case when unit='minute' then ':00' else '' end||'+09:00';end if;
 outcomes:=outcomes||jsonb_build_array(jsonb_build_object('start',jsonb_build_object('value',start_v,'precision',unit),'end',jsonb_build_object('value',end_v,'precision',unit)));end if;d:=d+1;end loop;
 if jsonb_array_length(outcomes) not between 1 and 200 then raise sqlstate 'PT422' using message='invalid_content_filters';end if;return outcomes;
end $$;

create function machimoa_review.content_filter_validate(v jsonb) returns void
language plpgsql immutable set search_path='' as $$
declare k text;f jsonb;x jsonb;p jsonb;cat text;required text[];irrelevant text[];unit text;a timestamptz;b timestamptz;previous_end timestamptz;
begin
 if v is null or jsonb_typeof(v) is distinct from 'object' or octet_length(v::text)>120000 or
 (select array_agg(key order by key) from jsonb_object_keys(v) key) is distinct from array['application','audience','category','delivery','location','schedule','schema','spaceKind','topic'] or v->>'schema' is distinct from 'content-filters-v1' or
 v->>'category' is null or v->>'category' not in ('program','event','youth_space') then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 cat:=v->>'category';required:=case cat when 'program' then array['topic','delivery','audience','application'] when 'event' then array['topic','schedule'] else array['spaceKind'] end;
 irrelevant:=case cat when 'program' then array['spaceKind','schedule'] when 'event' then array['delivery','audience','spaceKind','application'] else array['topic','delivery','audience','application','schedule'] end;
 for k,f in select key,value from jsonb_each(v-'schema'-'category') loop
 if jsonb_typeof(f) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(f) key) is distinct from array['status','value'] or f->>'status' is null or f->>'status' not in ('known','unknown','not_applicable') then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 if (k=any(required) and f->>'status'='not_applicable') or (k=any(irrelevant) and f->>'status'<>'not_applicable') then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 if f->>'status'<>'known' then if f->'value' is distinct from 'null'::jsonb then raise sqlstate 'PT422' using message='invalid_content_filters';end if;continue;end if;
 x:=f->'value';
 if k in ('topic','delivery','audience','spaceKind') then
 if jsonb_typeof(x) is distinct from 'string' or not (x#>>'{}')=any(case k when 'topic' then case cat when 'program' then array['language_learning','culture_experience','employment_career','daily_safety','community_exchange','other'] else array['festival_exchange','culture_arts','lecture_commemoration','other'] end when 'delivery' then array['online','onsite','mixed'] when 'audience' then array['children','other'] else array['introduction','news'] end) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 elsif k='location' then
 if jsonb_typeof(x) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(x) key) is distinct from array['scope','venues'] or x->>'scope' is null or x->>'scope' not in ('specific','nationwide') or jsonb_typeof(x->'venues') is distinct from 'array' or jsonb_array_length(x->'venues')>20 or (x->>'scope'='specific' and jsonb_array_length(x->'venues')=0) or (x->>'scope'='nationwide' and x->'venues'<>'[]'::jsonb) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 for p in select value from jsonb_array_elements(x->'venues') loop
 if jsonb_typeof(p) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(p) key) is distinct from array['address','district','facility','province'] or p->>'province' is null or p->>'province' not in ('11','28','41') or (p->'district'<>'null'::jsonb and (jsonb_typeof(p->'district')<>'string' or not machimoa_review.content_filter_district(p->>'province',p->>'district'))) or
 jsonb_typeof(p->'facility') is distinct from 'string' or char_length(p->>'facility')>200 or jsonb_typeof(p->'address') is distinct from 'string' or char_length(p->>'address')>500 or (p->>'facility')~'[<>[:cntrl:]]' or (p->>'address')~'[<>[:cntrl:]]' then raise sqlstate 'PT422' using message='invalid_content_filters';end if;end loop;
 if (select count(distinct elem.value) from jsonb_array_elements(x->'venues') elem(value))<>jsonb_array_length(x->'venues') then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 elsif k='application' then
 if jsonb_typeof(x) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(x) key) is distinct from array['deadlineKind','end','sourceStatus','start'] or x->>'deadlineKind' is null or x->>'deadlineKind' not in ('fixed','none') or x->>'sourceStatus' is null or x->>'sourceStatus' not in ('not_started','open','closed','unknown') or (x->>'deadlineKind'='fixed' and x->'end'='null'::jsonb) or (x->>'deadlineKind'='none' and x->'end'<>'null'::jsonb) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 a:=null;b:=null;if x->'start'<>'null'::jsonb then a:=machimoa_review.content_filter_endpoint(x->'start');end if;
 if x->'end'<>'null'::jsonb then b:=machimoa_review.content_filter_endpoint(x->'end');if x->'end'->>'precision'='day' then b:=b+interval '1 day'-interval '1 microsecond';end if;end if;
 if a>b then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 else
 if jsonb_typeof(x) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(x) key) is distinct from array['kind','occurrences','recurrence'] or x->>'kind' is null or x->>'kind' not in ('continuous','occurrences') or jsonb_typeof(x->'occurrences') is distinct from 'array' or jsonb_array_length(x->'occurrences') not between 1 and 200 or (x->>'kind'='continuous' and (jsonb_array_length(x->'occurrences')<>1 or x->'recurrence'<>'null'::jsonb)) then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 previous_end:=null;
 for p in select value from jsonb_array_elements(x->'occurrences') loop
 if jsonb_typeof(p) is distinct from 'object' or (select array_agg(key order by key) from jsonb_object_keys(p) key) is distinct from array['end','start'] then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 a:=machimoa_review.content_filter_endpoint(p->'start');b:=machimoa_review.content_filter_endpoint(p->'end');if p->'end'->>'precision'='day' then b:=b+interval '1 day'-interval '1 microsecond';end if;
 if a>b or previous_end>=a then raise sqlstate 'PT422' using message='invalid_content_filters';end if;previous_end:=b;end loop;
 if x->'recurrence'<>'null'::jsonb and machimoa_review.content_filter_recurrence(x->'recurrence') is distinct from x->'occurrences' then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 end if;end loop;
 if (cat='event' or (cat='program' and v->'delivery'->>'value' is distinct from 'online') or (cat='youth_space' and v->'spaceKind'->>'value'='introduction')) and v->'location'->>'status'='not_applicable' then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
 if ((cat='program' and v->'delivery'->>'value'='online') or (cat='youth_space' and v->'spaceKind'->>'value'='news')) and v->'location'->>'status'<>'not_applicable' then raise sqlstate 'PT422' using message='invalid_content_filters';end if;
end $$;

create function machimoa_review.content_filter_missing(v jsonb) returns text[]
language sql immutable set search_path='' as $$
 select coalesce(array_agg(distinct key order by key),'{}'::text[]) from (
 select key from jsonb_each(v-'schema'-'category') where value->>'status'='unknown'
 union all select 'location' where exists(select 1 from jsonb_array_elements(coalesce(v->'location'->'value'->'venues','[]')) p where p->'district'='null'::jsonb)
 union all select 'application' where v->'application'->'value'->>'deadlineKind'='none') q
$$;
create function machimoa_review.content_filter_category(p_id uuid,p_revision text) returns text
language sql stable set search_path='' as $$
 select coalesce(f.facts->>'public_category',case when s.source_id='seoul_reservation' then 'program' end,c.user_category)
 from machimoa_review.source_items s left join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
 left join machimoa_review.source_item_user_categories c on c.source_item_id=s.id and c.revision_hash=s.revision_hash
 where s.id=p_id and s.revision_hash=p_revision
$$;
create function machimoa_review.content_filter_binding(p_id uuid,p_revision text) returns jsonb
language sql stable set search_path='' as $$
 select jsonb_build_object('category',machimoa_review.content_filter_category(s.id,s.revision_hash),
 'topic',jsonb_build_array(f.facts->'purpose',f.facts->'content_kind',f.facts->'description'),
 'location',jsonb_build_array(f.facts->'activity_region',f.facts->'venue',f.facts->'activity_evidence'),
 'delivery',coalesce(f.facts->'delivery_mode',pt.gate_facts->'delivery_mode'),
 'audience',coalesce(f.facts->'target',f.facts->'target_raw'),
 'application',jsonb_build_array(coalesce(f.facts->'periods'->'application',jsonb_build_array(f.facts->'periods'->'RCPTBGNDT',f.facts->'periods'->'RCPTENDDT',ad.application_deadline_kind,ad.application_deadline_on)),f.facts->'source_status'),
 'schedule',coalesce(f.facts->'periods'->'operation',jsonb_build_array(f.facts->'periods'->'SVCOPNBGNDT',f.facts->'periods'->'SVCOPNENDDT',ep.event_start_on,ep.event_end_on,f.facts->'session_evidence')))
 from machimoa_review.source_items s left join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
 left join machimoa_review.source_item_product_types pt on pt.source_item_id=s.id and pt.revision_hash=s.revision_hash
 left join machimoa_review.source_item_application_deadlines ad on ad.source_item_id=s.id and ad.revision_hash=s.revision_hash
 left join machimoa_review.source_item_event_periods ep on ep.source_item_id=s.id and ep.revision_hash=s.revision_hash
 where s.id=p_id and s.revision_hash=p_revision
$$;
-- Reuse confirmed source facts without presenting an operator value as a quote.
create function machimoa_review.content_filter_fact_values(p_id uuid,p_revision text) returns jsonb
language plpgsql stable set search_path='' as $$
declare f jsonb;a jsonb;start_v jsonb;end_v jsonb;mode text;kind text;day_v date;r jsonb:='{}';
begin
 select facts into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision;
 mode:=f->>'delivery_mode';
 if mode is null then select gate_facts->>'delivery_mode' into mode from machimoa_review.source_item_product_types where source_item_id=p_id and revision_hash=p_revision;end if;
 if mode in ('online','offline','hybrid','mixed') then r:=r||jsonb_build_object('delivery',case mode when 'offline' then 'onsite' when 'hybrid' then 'mixed' else mode end);end if;
 if f->>'schema_version'='myseoul-program-v1' or f ? 'official_url' and jsonb_typeof(f->'periods'->'application')='array' then
 select value->'endpoints' into a from jsonb_array_elements(f->'periods'->'application') where value->>'status'='ok' limit 1;
 if a is not null and jsonb_array_length(a)>0 then start_v:=a->0;end_v:=a->(jsonb_array_length(a)-1);if jsonb_array_length(a)=1 then start_v:=null;end if;end if;
 elsif f->'periods'->'RCPTENDDT'->>'status'='ok' then
 end_v:=jsonb_build_object('value',f->'periods'->'RCPTENDDT'->>'value','precision',f->'periods'->'RCPTENDDT'->>'precision');
 if f->'periods'->'RCPTBGNDT'->>'status'='ok' then start_v:=jsonb_build_object('value',f->'periods'->'RCPTBGNDT'->>'value','precision',f->'periods'->'RCPTBGNDT'->>'precision');end if;
 else
 select application_deadline_kind,application_deadline_on into kind,day_v from machimoa_review.source_item_application_deadlines where source_item_id=p_id and revision_hash=p_revision;
 if kind='fixed' and day_v is not null then end_v:=jsonb_build_object('value',day_v::text,'precision','day');end if;end if;
 if end_v is null and (kind='none' or f->'periods'->'application'->0->>'status'='none' or f->'periods'->'RCPTENDDT'->>'status'='none') then r:=r||jsonb_build_object('application',jsonb_build_object('deadlineKind','none','start',start_v,'end',null,'sourceStatus','unknown'));end if;
 if end_v is not null then r:=r||jsonb_build_object('application',jsonb_build_object('deadlineKind','fixed','start',start_v,'end',end_v,'sourceStatus',case when f->>'source_status' in ('not_started','open','closed') then f->>'source_status' when f->>'source_status' in ('application_closed','reservation_closed') or f->'source_status' @> '["신청마감"]'::jsonb then 'closed' when f->'source_status' @> '["신청중"]'::jsonb then 'open' else 'unknown' end));end if;
 return r;
end $$;
create function machimoa_review.content_filter_consistent(p_id uuid,p_revision text,d jsonb) returns boolean
language plpgsql stable set search_path='' as $$
declare v jsonb:=machimoa_review.content_filter_fact_values(p_id,p_revision);f jsonb;windows jsonb:='[]';op jsonb;ends jsonb;o jsonb;ad date;bd date;covered boolean;
begin
 if d->>'category'='event' and v->>'delivery'='online' then return false;end if;
 if d->>'category'='program' then
 if v ? 'delivery' and d->'delivery'->>'status'='known' and d->'delivery'->>'value' is distinct from v->>'delivery' then return false;end if;
 if v ? 'application' and d->'application'->>'status'='known' and (d->'application'->'value'->'end' is distinct from v->'application'->'end' or d->'application'->'value'->'start' is distinct from v->'application'->'start' or (v->'application'->>'sourceStatus'<>'unknown' and d->'application'->'value'->>'sourceStatus' is distinct from v->'application'->>'sourceStatus')) then return false;end if;end if;
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
end $$;
create function machimoa_review.content_filter_ready(p_id uuid,p_revision text) returns boolean
language sql stable set search_path='' as $$
 select case when not exists(select 1 from machimoa_review.source_item_content_filters where source_item_id=p_id) then true else coalesce((select cardinality(machimoa_review.content_filter_missing(f.data))=0 and s.revision_hash=p_revision and f.source_binding=machimoa_review.content_filter_binding(p_id,p_revision) and machimoa_review.content_filter_consistent(p_id,p_revision,f.data)
 and f.data->>'category'=machimoa_review.content_filter_category(p_id,p_revision) from machimoa_review.source_item_content_filters f join machimoa_review.source_items s on s.id=f.source_item_id where source_item_id=p_id and f.revision_hash=p_revision),false) end
$$;
create function machimoa_review.content_filter_review_sync(p_id uuid,p_revision text) returns void
language plpgsql set search_path='' as $$
declare reasons text[];
begin
 select array(select 'content_filter:'||k from unnest(machimoa_review.content_filter_missing(data)) k) into reasons from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision;
 if not found then return;end if;
 if cardinality(reasons)>0 then
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at)
 values(p_id,p_revision,'content_review','queued',reasons,clock_timestamp(),clock_timestamp()) on conflict(source_item_id,revision_hash,processing_stage) do update
 set status='queued',reason_codes=(select array_agg(distinct k) from unnest(case when machimoa_review.processing_jobs.status='queued' then array(select code from unnest(machimoa_review.processing_jobs.reason_codes) code where code not like 'content_filter:%') else '{}'::text[] end||reasons) k)
 where machimoa_review.processing_jobs.status in ('queued','completed','cancelled');
 else
 update machimoa_review.processing_jobs set reason_codes=array(select k from unnest(reason_codes) k where k not like 'content_filter:%'),
 status=case when not exists(select 1 from unnest(reason_codes) k where k not like 'content_filter:%') then 'completed' else status end
 where source_item_id=p_id and revision_hash=p_revision and processing_stage='content_review' and status='queued' and exists(select 1 from unnest(reason_codes) k where k like 'content_filter:%');end if;
end $$;
create function machimoa_review.content_filter_info(p_id uuid,p_revision text) returns jsonb
language sql stable set search_path='' as $$
 select jsonb_build_object('schema','content-filters-v1','revision',f.revision_hash,'filterVersion',f.filter_version,'data',f.data,
 'missing',to_jsonb(machimoa_review.content_filter_missing(f.data)),'origins',f.origins)
 from machimoa_review.source_item_content_filters f where source_item_id=p_id and revision_hash=p_revision
$$;

create function machimoa_review.content_filter_observe(p_source text,p_items jsonb,p_outcomes jsonb default null) returns void
language plpgsql set search_path='' as $$
declare item jsonb;sid uuid;s machimoa_review.source_items%rowtype;f machimoa_review.source_item_content_filters%rowtype;
 d jsonb;e jsonb;k text;origin_map jsonb;material text;ref jsonb;current_data jsonb;changed text[];source_facts jsonb;result text;confirmed jsonb;
begin
 for item in select value from jsonb_array_elements(p_items) loop
 select * into s from machimoa_review.source_items where source_id=p_source and external_key=item->>'external_key' and revision_hash=item->>'revision_hash' for update;
 if not found then raise sqlstate 'PT409' using message='content_filter_identity_changed';end if;sid:=s.id;
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
 end loop;
end $$;
create function machimoa_review.content_filter_after_facts(p_id uuid,p_revision text) returns void
language plpgsql set search_path='' as $$
declare f machimoa_review.source_item_content_filters%rowtype;b jsonb;d jsonb;k text;fields text[]:='{}';cat text;confirmed jsonb;derived_origins jsonb:='{}';
begin
 select * into f from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision for update;
 if not found then return;end if;b:=machimoa_review.content_filter_binding(p_id,p_revision);d:=f.data;cat:=b->>'category';
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
 if d->k->>'status'='unknown' then d:=jsonb_set(d,array[k],jsonb_build_object('status','known','value',confirmed->k));derived_origins:=derived_origins||jsonb_build_object(k,'confirmed_facts');end if;end loop;
 if d->'delivery'->>'value'='online' then d:=jsonb_set(d,array['location'],jsonb_build_object('status','not_applicable','value',null));end if;end if;
 if b is distinct from f.source_binding then
 update machimoa_review.source_item_content_filters set data=d,source_binding=b,origins=origins||coalesce((select jsonb_object_agg(field_key,'source_change') from unnest(array['topic','location','delivery','audience','spaceKind','application','schedule']) field_key where field_key=any(fields) or 'category'=any(fields)),'{}'::jsonb)||derived_origins,filter_version=filter_version+1,updated_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.content_filter_edits(source_item_id,revision_hash,filter_version,origin,fields,before_data,after_data)
 select p_id,p_revision,filter_version,'source_change',fields,f.data,d from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision;end if;
 perform machimoa_review.content_filter_review_sync(p_id,p_revision);
end $$;

create function machimoa_review.content_filter_claim_capture() returns trigger
language plpgsql security definer set search_path='' as $$
declare f machimoa_review.source_item_content_filters%rowtype;
begin
 if new.processing_stage<>'ai_enrichment' or new.status<>'claimed' or (old.status='claimed' and old.claimed_at is not distinct from new.claimed_at) then return new;end if;
 select * into f from machimoa_review.source_item_content_filters where source_item_id=new.source_item_id and revision_hash=new.revision_hash for share;
 if not found then return new;end if;
 if not machimoa_review.content_filter_ready(new.source_item_id,new.revision_hash) or new.claimed_at is null or new.claim_lease_until is null or new.claimed_by is null then raise sqlstate 'PT409' using message='content_filter_not_ready';end if;
 insert into machimoa_review.content_filter_claim_inputs(job_id,claimed_at,lease_until,worker_id,source_item_id,revision_hash,filter_version,data)
 values(new.id,new.claimed_at,new.claim_lease_until,new.claimed_by,new.source_item_id,new.revision_hash,f.filter_version,f.data);
 return new;
end $$;
create trigger content_filter_claim_capture after update on machimoa_review.processing_jobs for each row execute function machimoa_review.content_filter_claim_capture();
create function machimoa_review.content_filter_candidate_capture(p_id uuid,p_job uuid,p_claimed_at timestamptz) returns void
language plpgsql set search_path='' as $$
declare m machimoa_review.content_filter_claim_inputs%rowtype;f machimoa_review.source_item_content_filters%rowtype;c machimoa_review.curation_candidates%rowtype;s machimoa_review.source_items%rowtype;
begin
 select * into m from machimoa_review.content_filter_claim_inputs where job_id=p_job and claimed_at=p_claimed_at;
 if not found then return;end if;
 select * into s from machimoa_review.source_items where id=m.source_item_id;
 select * into f from machimoa_review.source_item_content_filters where source_item_id=m.source_item_id and revision_hash=m.revision_hash;
 select * into c from machimoa_review.curation_candidates where id=p_id;
 if f.filter_version is distinct from m.filter_version or f.data is distinct from m.data or s.revision_hash is distinct from m.revision_hash or c.source_item_id is distinct from s.external_key or c.source_revision_hash is distinct from m.revision_hash or c.user_category is distinct from m.data->>'category' then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
 insert into machimoa_review.candidate_content_filters(candidate_id,source_item_id,revision_hash,filter_version,input_data,job_id,claimed_at,approved_version,approved_revision,approved_data)
 values(p_id,m.source_item_id,m.revision_hash,m.filter_version,m.data,p_job,p_claimed_at,m.filter_version,m.revision_hash,m.data) on conflict(candidate_id) do nothing;
 if not exists(select 1 from machimoa_review.candidate_content_filters where candidate_id=p_id and job_id=p_job and claimed_at=p_claimed_at and filter_version=m.filter_version and input_data=m.data) then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
end $$;
create function machimoa_review.content_filter_candidate_info(p_id uuid) returns jsonb
language sql stable set search_path='' as $$
 select jsonb_build_object('schema','content-filters-v1','inputVersion',m.filter_version,'approvedVersion',m.approved_version,'currentVersion',coalesce(f.filter_version,1),
 'inputRevision',m.revision_hash,'approvedRevision',m.approved_revision,'currentRevision',s.revision_hash,
 'input',m.input_data,'approved',m.approved_data,'current',coalesce(f.data,m.approved_data),'changed',f.filter_version is distinct from m.approved_version or s.revision_hash is distinct from m.approved_revision,
 'canPublish',coalesce(f.filter_version=m.approved_version and s.revision_hash=m.approved_revision and machimoa_review.content_filter_ready(m.source_item_id,s.revision_hash),false))
 from machimoa_review.candidate_content_filters m join machimoa_review.source_items s on s.id=m.source_item_id left join machimoa_review.source_item_content_filters f on f.source_item_id=m.source_item_id and f.revision_hash=s.revision_hash where m.candidate_id=p_id
$$;
create function machimoa_review.content_filter_candidate_approve(p_id uuid) returns void
language plpgsql set search_path='' as $$
declare m machimoa_review.candidate_content_filters%rowtype;f machimoa_review.source_item_content_filters%rowtype;c machimoa_review.curation_candidates%rowtype;
begin
 select * into m from machimoa_review.candidate_content_filters where candidate_id=p_id for update;
 if not found then return;end if;
 select ff.* into f from machimoa_review.source_item_content_filters ff join machimoa_review.source_items s on s.id=ff.source_item_id and s.revision_hash=ff.revision_hash where ff.source_item_id=m.source_item_id for share of ff;
 select * into c from machimoa_review.curation_candidates where id=p_id;
 if f.source_item_id is null or not machimoa_review.content_filter_ready(m.source_item_id,f.revision_hash) or c.user_category is distinct from f.data->>'category' then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
 update machimoa_review.candidate_content_filters set approved_version=f.filter_version,approved_revision=f.revision_hash,approved_data=f.data where candidate_id=p_id;
end $$;
create function machimoa_review.content_filter_publish(p_id uuid) returns void
language plpgsql set search_path='' as $$
declare m machimoa_review.candidate_content_filters%rowtype;f machimoa_review.source_item_content_filters%rowtype;c machimoa_review.curation_candidates%rowtype;
begin
 select * into m from machimoa_review.candidate_content_filters where candidate_id=p_id for share;
 if not found then return;end if;
 select ff.* into f from machimoa_review.source_item_content_filters ff join machimoa_review.source_items s on s.id=ff.source_item_id and s.revision_hash=ff.revision_hash where ff.source_item_id=m.source_item_id for share of ff;
 select * into c from machimoa_review.curation_candidates where id=p_id;
 if f.filter_version is distinct from m.approved_version or f.revision_hash is distinct from m.approved_revision or f.data is distinct from m.approved_data or not machimoa_review.content_filter_ready(m.source_item_id,m.approved_revision) or c.user_category is distinct from m.approved_data->>'category' then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
 if c.published_curation_id is not null then update public.curations set content_filters=m.approved_data where id=c.published_curation_id;end if;
end $$;

create function public.admin_content_filter_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;item jsonb;info jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id;
 if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 item:=case s.source_id when 'myseoul_program' then public.admin_myseoul_program_detail(p_id) when 'seoul_reservation' then public.admin_program_detail(p_id) else machimoa_review.admin_review_item('facts',p_id) end;
 info:=machimoa_review.content_filter_info(p_id,s.revision_hash);
 if info is null then raise sqlstate 'PT404' using message='review_not_found';end if;
 return info||jsonb_build_object('id',p_id,'version',item->>'version','editable',item->>'status'='open');
end $$;
create function public.admin_content_filter_save(p_id uuid,p_revision text,p_version text,p_filter_version bigint,p_patch jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
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
end $$;
create function machimoa_review.content_filter_claim_context(p_job uuid,p_at timestamptz) returns jsonb
language plpgsql volatile set search_path='' as $$
declare r jsonb;begin
 select jsonb_build_object('schema','content-filters-v1','filterVersion',filter_version,'data',data,'claimedAt',claimed_at,'leaseUntil',lease_until,'workerId',worker_id)
 into r from machimoa_review.content_filter_claim_inputs where job_id=p_job and claimed_at=p_at;return r;
end $$;
CREATE OR REPLACE FUNCTION public.observe_myseoul_program(p_run_id uuid, p_items jsonb, p_next_checkpoint jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare filter_items jsonb:=p_items; entry jsonb; r record; sid uuid; existing machimoa_review.source_item_program_facts%rowtype; outcomes jsonb:='[]';previous_rows jsonb:='{}';prior jsonb;incoming_existing text[]:='{}';
begin
 p_items:=(select coalesce(jsonb_agg(value-'filterFacts'),'[]') from jsonb_array_elements(p_items));
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
revoke all on function public.observe_myseoul_program(uuid,jsonb,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.observe_myseoul_program(uuid,jsonb,jsonb) to postgres;
grant execute on function public.observe_myseoul_program(uuid,jsonb,jsonb) to service_role;
CREATE OR REPLACE FUNCTION public.observe_seoul_program(p_run_id uuid, p_items jsonb, p_next_checkpoint jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare filter_items jsonb:=p_items; entry jsonb; r record; sid uuid; outcomes jsonb:='[]';
begin
 p_items:=(select coalesce(jsonb_agg(value-'filterFacts'),'[]') from jsonb_array_elements(p_items));
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
revoke all on function public.observe_seoul_program(uuid,jsonb,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.observe_seoul_program(uuid,jsonb,jsonb) to postgres;
grant execute on function public.observe_seoul_program(uuid,jsonb,jsonb) to service_role;
alter function public.upsert_source_observations_v4(text,uuid,jsonb,jsonb) rename to cf_base_pub_upsert_source_observations_v4;
alter function public.cf_base_pub_upsert_source_observations_v4(text,uuid,jsonb,jsonb) set schema machimoa_review;
revoke all on function machimoa_review.cf_base_pub_upsert_source_observations_v4(text,uuid,jsonb,jsonb) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.upsert_source_observations_v4(p_source_id text, p_run_id uuid, p_items jsonb, p_next_checkpoint jsonb)
 RETURNS TABLE(input_index integer, external_key text, outcome text, duplicate_in_batch boolean)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare result_rows jsonb;observations jsonb;begin
 select coalesce(jsonb_agg(value-'filterFacts'),'[]') into observations from jsonb_array_elements(p_items);
 select coalesce(jsonb_agg(to_jsonb(r)),'[]') into result_rows from machimoa_review.cf_base_pub_upsert_source_observations_v4(p_source_id,p_run_id,observations,p_next_checkpoint) r;
 perform machimoa_review.content_filter_observe(p_source_id,p_items,(select coalesce(jsonb_agg(jsonb_build_object('id',s.id,'outcome',r.outcome)),'[]') from jsonb_to_recordset(result_rows) r(external_key text,outcome text) join machimoa_review.source_items s on s.source_id=p_source_id and s.external_key=r.external_key));
 return query select * from jsonb_to_recordset(result_rows) r(input_index integer,external_key text,outcome text,duplicate_in_batch boolean);
end
$function$
;
revoke all on function public.upsert_source_observations_v4(text,uuid,jsonb,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.upsert_source_observations_v4(text,uuid,jsonb,jsonb) to postgres;
grant execute on function public.upsert_source_observations_v4(text,uuid,jsonb,jsonb) to service_role;
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
revoke all on function machimoa_review.claim_processing_jobs(text,integer,text,integer) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.claim_processing_jobs(text,integer,text,integer) to postgres;
CREATE OR REPLACE FUNCTION machimoa_review.myseoul_ai_preparation_check(p_id uuid, p_revision text, p_version bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; allowed boolean;
begin
 if not machimoa_review.content_filter_ready(p_id,p_revision) then raise sqlstate 'PT409' using message='content_filter_not_ready';end if;
 select * into s from machimoa_review.source_items where id=p_id and source_id='myseoul_program' for update;
 if not found or s.revision_hash is distinct from p_revision then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 if not found or f.facts_version is distinct from p_version or
 f.schema_version<>'myseoul-program-facts-v1-local' or f.evaluated_profile<>'myseoul-program-v1-local' then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=s.id order by revision_hash,processing_stage for update;
 select enabled and permission_status in ('approved_noncommercial','approved_commercial') into allowed
 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 if not coalesce(allowed,false) or f.manual_excluded or machimoa_review.admin_trash_pending(p_id,p_revision) or
 not machimoa_review.myseoul_ai_ready(machimoa_review.myseoul_evaluate(f.facts,clock_timestamp())) or
 f.facts->>'public_category' not in ('program','event') or
 exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) then
  raise exception using errcode='PT409',message='program_ai_unavailable';end if;
end $function$
;
revoke all on function machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint) to postgres;
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
 not machimoa_review.publication_temporal_ready(machimoa_review.program_evaluate(f.facts,clock_timestamp())) or
 s.normalized_payload->'provider_fields'->>'MAXCLASSNM' is distinct from '문화체험' or
 exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) then
  raise exception using errcode='PT409',message='program_ai_unavailable';end if;
end $function$
;
revoke all on function machimoa_review.program_ai_check(uuid,text,bigint) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.program_ai_check(uuid,text,bigint) to postgres;
CREATE OR REPLACE FUNCTION public.claim_myseoul_program_ai(p_source_item_id uuid, p_revision text, p_worker_id text, p_lease_seconds integer)
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
 select * into s from machimoa_review.source_items where id=p_source_item_id and source_id='myseoul_program' for update skip locked;
 if not found then return '[]'::jsonb;end if;
 -- Recover expired attempts even when gate is now closed. A queued row is not
 -- execution permission; the gate below remains authoritative. This prevents
 -- an abandoned claim from permanently blocking program refresh/admin edits.
 update machimoa_review.processing_jobs set status='queued',claimed_at=null,claimed_by=null,claim_lease_until=null
 where source_item_id=s.id and processing_stage='ai_enrichment' and status='claimed' and claim_lease_until<=clock_timestamp();
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision;
 if not found then return '[]'::jsonb;end if;
 begin perform machimoa_review.myseoul_ai_preparation_check(s.id,p_revision,f.facts_version);
 exception when sqlstate 'PT409' then return '[]'::jsonb;end;
 if exists(select 1 from machimoa_review.curation_candidates where source='myseoul_program'
 and source_item_id=s.external_key) then return '[]'::jsonb;end if;
 v_now:=clock_timestamp();
 select * into j from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage='ai_enrichment' and ((status='queued' and available_at<=v_now and (next_retry_at is null or next_retry_at<=v_now))
 or (status='claimed' and claim_lease_until<=v_now)) for update skip locked;
 if not found then return '[]'::jsonb;end if;
 update machimoa_review.processing_jobs set status='claimed',claimed_at=v_now,
 claimed_by=p_worker_id,claim_lease_until=v_now+make_interval(secs=>p_lease_seconds) where id=j.id returning * into j;
 return jsonb_build_array(jsonb_build_object('jobId',j.id,'sourceItemId',s.id,'source','myseoul_program',
 'externalKey',s.external_key,'revision',p_revision,'schema',f.schema_version,'profile',f.evaluated_profile,
 'factsVersion',f.facts_version,'title',s.min_fields->>'title','publicCategory',f.facts->>'public_category',
 'filterContext',machimoa_review.content_filter_claim_context(j.id,j.claimed_at),'facts',f.facts,'observedFacts',f.observed_facts,'claimedAt',j.claimed_at,'leaseUntil',j.claim_lease_until,'workerId',p_worker_id));
end $function$
;
revoke all on function public.claim_myseoul_program_ai(uuid,text,text,integer) from public,anon,authenticated,service_role;
grant execute on function public.claim_myseoul_program_ai(uuid,text,text,integer) to postgres;
grant execute on function public.claim_myseoul_program_ai(uuid,text,text,integer) to service_role;
CREATE OR REPLACE FUNCTION public.finish_myseoul_program_ai(p_job_id uuid, p_revision text, p_facts_version bigint, p_claimed_at timestamp with time zone, p_lease_until timestamp with time zone, p_worker_id text, p_output jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 j machimoa_review.processing_jobs%rowtype; m machimoa_review.program_candidate_inputs%rowtype;
 v_id uuid; k text; v text; v_now timestamptz; v_hash text; deadline date; deadline_kind text; event_start date; event_end date; category text; ap jsonb; op jsonb;
begin
 if p_job_id is null or p_revision is null or p_facts_version is null or p_claimed_at is null or p_lease_until is null or
 p_worker_id is null or p_output is null or jsonb_typeof(p_output)<>'object' or octet_length(p_output::text)>600000 or
 (select array_agg(key order by key) from jsonb_object_keys(p_output) key) is distinct from
 array['aiModel','contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 for k,v in select key,value from jsonb_each_text(p_output) loop
 if jsonb_typeof(p_output->k)<>'string' or char_length(btrim(v)) not between 1 and
 (case when k like 'title%' then 300 when k like 'summary%' then 1000 when k='aiModel' then 100 else 200000 end) then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 p_output:=jsonb_set(p_output,array[k],to_jsonb(btrim(v)));end loop;
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs pj on pj.source_item_id=si.id
 where pj.id=p_job_id and si.source_id='myseoul_program' for update of si;
 if not found then raise exception using errcode='PT409',message='program_ai_stale';end if;
 perform machimoa_review.myseoul_ai_preparation_check(s.id,p_revision,p_facts_version);
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 if j.revision_hash is distinct from p_revision or j.processing_stage<>'ai_enrichment' or
 p_output->>'titleKo' is distinct from s.min_fields->>'title' then
 raise exception using errcode='PT409',message='program_ai_stale';end if;
 v_hash:=encode(sha256(convert_to(p_output::text,'UTF8')),'hex');
 select * into m from machimoa_review.program_candidate_inputs where job_id=p_job_id;
 if found then
 if j.status<>'completed' or m.facts_version<>p_facts_version or m.claimed_at is distinct from p_claimed_at or
 m.lease_until is distinct from p_lease_until or m.worker_id is distinct from p_worker_id or m.output_hash<>v_hash then
 raise exception using errcode='PT409',message='program_ai_stale';end if;
 return jsonb_build_object('candidateId',m.candidate_id,'outcome','duplicate');end if;
 v_now:=clock_timestamp();
 if j.status<>'claimed' or j.claimed_by is distinct from p_worker_id or j.claimed_at is distinct from p_claimed_at or
 j.claim_lease_until is distinct from p_lease_until or j.claim_lease_until<=v_now then
 raise exception using errcode='PT409',message='program_ai_lease_lost';end if;
 perform pg_advisory_xact_lock(hashtextextended('myseoul_program:'||s.external_key,0));
 if exists(select 1 from machimoa_review.curation_candidates where source='myseoul_program' and source_item_id=s.external_key
 and source_revision_hash=p_revision) then raise exception using errcode='PT409',message='program_ai_stale';end if;
 category:=f.facts->>'public_category';
 select value->'endpoints' into ap from jsonb_array_elements(f.facts->'periods'->'application') where value->>'status'='ok' limit 1;
 select value->'endpoints' into op from jsonb_array_elements(f.facts->'periods'->'operation') where value->>'status'='ok' limit 1;
 if category='program' then
 deadline_kind:=case when ap is null then 'none' else 'fixed' end;
 deadline:=left(ap->(jsonb_array_length(ap)-1)->>'value',10)::date;
 else
 event_start:=left(op->0->>'value',10)::date;
 event_end:=left(op->(jsonb_array_length(op)-1)->>'value',10)::date;
 if event_start is null or event_end is null or event_start>event_end then
 raise exception using errcode='PT422',message='event_period_required';end if;
 end if;
 v_id:=gen_random_uuid();
 update machimoa_review.curation_candidates set review_status='superseded',superseded_at=v_now,superseded_by_candidate_id=v_id
 where source='myseoul_program' and source_item_id=s.external_key and review_status='pending';
 insert into machimoa_review.curation_candidates(id,source,source_item_id,source_revision_hash,slug,category,user_category,
 title,summary,content,ai_status,title_ko,summary_ko,content_ko,ai_status_ko,title_ja,summary_ja,content_ja,ai_status_ja,
 source_url,ai_model,raw_payload,application_deadline_kind,application_deadline_on,event_start_on,event_end_on)
 values(v_id,'myseoul_program',s.external_key,p_revision,'myseoul-'||substr(encode(sha256(convert_to(s.external_key,'UTF8')),'hex'),1,32),
 coalesce(nullif(left(f.facts->>'source_category',100),''),category),category,p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',
 p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',
 p_output->>'titleJa',p_output->>'summaryJa',p_output->>'contentJa','success',f.facts->>'official_url',p_output->>'aiModel',
 jsonb_build_object('schema',f.schema_version,'profile',f.evaluated_profile,'factsVersion',f.facts_version,'sourceCategory',f.facts->'source_category','publicCategory',category),
 deadline_kind,deadline,event_start,event_end);
 insert into machimoa_review.program_candidate_inputs(candidate_id,source_item_id,revision_hash,facts_version,job_id,claimed_at,
 lease_until,worker_id,schema_version,profile,api_category,input_facts,output_hash)
 values(v_id,s.id,p_revision,f.facts_version,j.id,p_claimed_at,p_lease_until,p_worker_id,f.schema_version,f.evaluated_profile,
 coalesce(nullif(left(f.facts->>'source_category',100),''),category),f.facts,v_hash);
 perform machimoa_review.content_filter_candidate_capture(v_id,j.id,p_claimed_at);
 perform machimoa_review.complete_processing_job(j.id,p_worker_id);
 return jsonb_build_object('candidateId',v_id,'outcome','inserted');
end $function$
;
revoke all on function public.finish_myseoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.finish_myseoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb) to postgres;
grant execute on function public.finish_myseoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb) to service_role;
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
 'filterContext',machimoa_review.content_filter_claim_context(j.id,j.claimed_at),'facts',f.facts,'observedFacts',f.observed_facts,'claimedAt',j.claimed_at,'leaseUntil',j.claim_lease_until,'workerId',p_worker_id));
end $function$
;
revoke all on function public.claim_seoul_program_ai(uuid,text,text,integer) from public,anon,authenticated,service_role;
grant execute on function public.claim_seoul_program_ai(uuid,text,text,integer) to postgres;
grant execute on function public.claim_seoul_program_ai(uuid,text,text,integer) to service_role;
CREATE OR REPLACE FUNCTION public.finish_seoul_program_ai(p_job_id uuid, p_revision text, p_facts_version bigint, p_claimed_at timestamp with time zone, p_lease_until timestamp with time zone, p_worker_id text, p_output jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 j machimoa_review.processing_jobs%rowtype; m machimoa_review.program_candidate_inputs%rowtype;
 v_id uuid; k text; v text; v_now timestamptz; v_hash text; deadline date;
begin
 if p_job_id is null or p_revision is null or p_facts_version is null or p_claimed_at is null or p_lease_until is null or
 p_worker_id is null or p_output is null or jsonb_typeof(p_output)<>'object' or octet_length(p_output::text)>600000 or
 (select array_agg(key order by key) from jsonb_object_keys(p_output) key) is distinct from
 array['aiModel','contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 for k,v in select key,value from jsonb_each_text(p_output) loop
 if jsonb_typeof(p_output->k)<>'string' or char_length(btrim(v)) not between 1 and
 (case when k like 'title%' then 300 when k like 'summary%' then 1000 when k='aiModel' then 100 else 200000 end) then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 p_output:=jsonb_set(p_output,array[k],to_jsonb(btrim(v)));end loop;
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs pj on pj.source_item_id=si.id
 where pj.id=p_job_id and si.source_id='seoul_reservation' for update of si;
 if not found then raise exception using errcode='PT409',message='program_ai_stale';end if;
 perform machimoa_review.program_ai_check(s.id,p_revision,p_facts_version);
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 if j.revision_hash is distinct from p_revision or j.processing_stage<>'ai_enrichment' or
 p_output->>'titleKo' is distinct from s.min_fields->>'title' then
 raise exception using errcode='PT409',message='program_ai_stale';end if;
 v_hash:=encode(sha256(convert_to(p_output::text,'UTF8')),'hex');
 select * into m from machimoa_review.program_candidate_inputs where job_id=p_job_id;
 if found then
 if j.status<>'completed' or m.facts_version<>p_facts_version or m.claimed_at is distinct from p_claimed_at or
 m.lease_until is distinct from p_lease_until or m.worker_id is distinct from p_worker_id or m.output_hash<>v_hash then
 raise exception using errcode='PT409',message='program_ai_stale';end if;
 return jsonb_build_object('candidateId',m.candidate_id,'outcome','duplicate');end if;
 v_now:=clock_timestamp();
 if j.status<>'claimed' or j.claimed_by is distinct from p_worker_id or j.claimed_at is distinct from p_claimed_at or
 j.claim_lease_until is distinct from p_lease_until or j.claim_lease_until<=v_now then
 raise exception using errcode='PT409',message='program_ai_lease_lost';end if;
 perform pg_advisory_xact_lock(hashtextextended('seoul_reservation:'||s.external_key,0));
 if exists(select 1 from machimoa_review.curation_candidates where source='seoul_reservation' and source_item_id=s.external_key
 and source_revision_hash=p_revision) then raise exception using errcode='PT409',message='program_ai_stale';end if;
 deadline:=left(f.facts->'periods'->'RCPTENDDT'->>'value',10)::date;
 v_id:=gen_random_uuid();
 update machimoa_review.curation_candidates set review_status='superseded',superseded_at=v_now,superseded_by_candidate_id=v_id
 where source='seoul_reservation' and source_item_id=s.external_key and review_status='pending';
 insert into machimoa_review.curation_candidates(id,source,source_item_id,source_revision_hash,slug,category,user_category,
 title,summary,content,ai_status,title_ko,summary_ko,content_ko,ai_status_ko,title_ja,summary_ja,content_ja,ai_status_ja,
 source_url,ai_model,raw_payload,application_deadline_kind,application_deadline_on)
 values(v_id,'seoul_reservation',s.external_key,p_revision,'seoul-'||substr(encode(sha256(convert_to(s.external_key,'UTF8')),'hex'),1,32),
 '문화체험','program',p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',
 p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',
 p_output->>'titleJa',p_output->>'summaryJa',p_output->>'contentJa','success',f.facts->>'official_url',p_output->>'aiModel',
 jsonb_build_object('schema',f.schema_version,'profile',f.evaluated_profile,'factsVersion',f.facts_version,'apiCategory','문화체험'),
 'fixed',deadline);
 insert into machimoa_review.program_candidate_inputs(candidate_id,source_item_id,revision_hash,facts_version,job_id,claimed_at,
 lease_until,worker_id,schema_version,profile,api_category,input_facts,output_hash)
 values(v_id,s.id,p_revision,f.facts_version,j.id,p_claimed_at,p_lease_until,p_worker_id,f.schema_version,f.evaluated_profile,
 '문화체험',f.facts,v_hash);
 perform machimoa_review.content_filter_candidate_capture(v_id,j.id,p_claimed_at);
 perform machimoa_review.complete_processing_job(j.id,p_worker_id);
 return jsonb_build_object('candidateId',v_id,'outcome','inserted');
end $function$
;
revoke all on function public.finish_seoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.finish_seoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb) to postgres;
grant execute on function public.finish_seoul_program_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb) to service_role;
alter function machimoa_review.admin_review_snapshot(text,uuid) rename to cf_base_admin_review_snapshot;
revoke all on function machimoa_review.cf_base_admin_review_snapshot(text,uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.admin_review_snapshot(p_kind text, p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 return machimoa_review.cf_base_admin_review_snapshot(p_kind,p_id)||jsonb_build_object('contentFilter',case when p_kind='facts' then
 (select to_jsonb(f) from machimoa_review.source_item_content_filters f join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash where s.id=p_id)
 else (select jsonb_build_array(to_jsonb(m),to_jsonb(f)) from machimoa_review.candidate_content_filters m left join machimoa_review.source_item_content_filters f on f.source_item_id=m.source_item_id and f.revision_hash=m.revision_hash where m.candidate_id=p_id) end);
end
$function$
;
revoke all on function machimoa_review.admin_review_snapshot(text,uuid) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.admin_review_snapshot(text,uuid) to postgres;
alter function machimoa_review.admin_review_item(text,uuid) rename to cf_base_admin_review_item;
revoke all on function machimoa_review.cf_base_admin_review_item(text,uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.admin_review_item(p_kind text, p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;info jsonb;sid uuid;rev text;begin
 item:=machimoa_review.cf_base_admin_review_item(p_kind,p_id);sid:=machimoa_review.admin_review_source(p_kind,p_id);
 select revision_hash into rev from machimoa_review.source_items where id=sid;
 if p_kind='facts' then
 info:=machimoa_review.content_filter_info(sid,rev);
 if info is not null then item:=item||jsonb_build_object('filterInfo',info);
 if item->>'status'<>'excluded' and jsonb_array_length(info->'missing')>0 then item:=item||jsonb_build_object('status','open','aiStatus','blocked');end if;end if;
 else
 info:=machimoa_review.content_filter_candidate_info(p_id);
 if info is not null then item:=item||jsonb_build_object('filterInfo',info);
 if item ? 'programInfo' and not (info->>'canPublish')::boolean then item:=jsonb_set(item,array['programInfo','canPublish'],'false');end if;end if;
 end if;return item;
end
$function$
;
revoke all on function machimoa_review.admin_review_item(text,uuid) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.admin_review_item(text,uuid) to postgres;
alter function public.admin_myseoul_program_detail(uuid) rename to cf_base_pub_admin_myseoul_program_detail;
alter function public.cf_base_pub_admin_myseoul_program_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.cf_base_pub_admin_myseoul_program_detail(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.admin_myseoul_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;info jsonb;begin
 item:=machimoa_review.cf_base_pub_admin_myseoul_program_detail(p_id);info:=machimoa_review.content_filter_info(p_id,item->>'revision');
 if info is not null then
 item:=item||jsonb_build_object('filterInfo',info,'version',encode(sha256(convert_to(jsonb_build_array(item->>'version',info)::text,'UTF8')),'hex'));
 if item->>'status'<>'excluded' and jsonb_array_length(info->'missing')>0 then item:=item||jsonb_build_object('status','open','aiStatus','blocked');end if;
 end if;return item;
end
$function$
;
revoke all on function public.admin_myseoul_program_detail(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_myseoul_program_detail(uuid) to postgres;
grant execute on function public.admin_myseoul_program_detail(uuid) to service_role;
alter function public.admin_program_detail(uuid) rename to cf_base_pub_admin_program_detail;
alter function public.cf_base_pub_admin_program_detail(uuid) set schema machimoa_review;
revoke all on function machimoa_review.cf_base_pub_admin_program_detail(uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.admin_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;info jsonb;begin
 item:=machimoa_review.cf_base_pub_admin_program_detail(p_id);info:=machimoa_review.content_filter_info(p_id,item->>'revision');
 if info is not null then
 item:=item||jsonb_build_object('filterInfo',info,'version',encode(sha256(convert_to(jsonb_build_array(item->>'version',info)::text,'UTF8')),'hex'));
 if item->>'status'<>'excluded' and jsonb_array_length(info->'missing')>0 then item:=item||jsonb_build_object('status','open','aiStatus','blocked');end if;
 end if;return item;
end
$function$
;
revoke all on function public.admin_program_detail(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_program_detail(uuid) to postgres;
grant execute on function public.admin_program_detail(uuid) to service_role;
alter function machimoa_review.myseoul_refresh(uuid,timestamp with time zone) rename to cf_base_myseoul_refresh;
revoke all on function machimoa_review.cf_base_myseoul_refresh(uuid,timestamp with time zone) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.myseoul_refresh(p_id uuid, p_now timestamp with time zone DEFAULT clock_timestamp())
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
 perform machimoa_review.cf_base_myseoul_refresh(p_id,p_now);
 perform machimoa_review.content_filter_after_facts(p_id,(select revision_hash from machimoa_review.source_items where id=p_id));
end
$function$
;
revoke all on function machimoa_review.myseoul_refresh(uuid,timestamp with time zone) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.myseoul_refresh(uuid,timestamp with time zone) to postgres;
alter function machimoa_review.program_refresh(uuid,timestamp with time zone) rename to cf_base_program_refresh;
revoke all on function machimoa_review.cf_base_program_refresh(uuid,timestamp with time zone) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.program_refresh(p_id uuid, p_now timestamp with time zone DEFAULT clock_timestamp())
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 perform machimoa_review.cf_base_program_refresh(p_id,p_now);
 perform machimoa_review.content_filter_after_facts(p_id,(select revision_hash from machimoa_review.source_items where id=p_id));
end
$function$
;
revoke all on function machimoa_review.program_refresh(uuid,timestamp with time zone) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.program_refresh(uuid,timestamp with time zone) to postgres;
alter function public.admin_review_save_facts(uuid,text,text,jsonb,uuid) rename to cf_base_pub_admin_review_save_facts;
alter function public.cf_base_pub_admin_review_save_facts(uuid,text,text,jsonb,uuid) set schema machimoa_review;
revoke all on function machimoa_review.cf_base_pub_admin_review_save_facts(uuid,text,text,jsonb,uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.admin_review_save_facts(p_id uuid, p_revision text, p_version text, p_facts jsonb, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;begin
 item:=machimoa_review.cf_base_pub_admin_review_save_facts(p_id,p_revision,p_version,p_facts,p_actor);
 perform machimoa_review.content_filter_after_facts(p_id,p_revision);
 return machimoa_review.admin_review_item('facts',p_id);
end
$function$
;
revoke all on function public.admin_review_save_facts(uuid,text,text,jsonb,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_review_save_facts(uuid,text,text,jsonb,uuid) to postgres;
grant execute on function public.admin_review_save_facts(uuid,text,text,jsonb,uuid) to service_role;
alter function public.admin_review_save_candidate(uuid,text,text,jsonb,uuid) rename to cf_base_pub_admin_review_save_candidate;
alter function public.cf_base_pub_admin_review_save_candidate(uuid,text,text,jsonb,uuid) set schema machimoa_review;
revoke all on function machimoa_review.cf_base_pub_admin_review_save_candidate(uuid,text,text,jsonb,uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.admin_review_save_candidate(p_id uuid, p_revision text, p_version text, p_content jsonb, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;begin
 item:=machimoa_review.cf_base_pub_admin_review_save_candidate(p_id,p_revision,p_version,p_content,p_actor);
 perform machimoa_review.content_filter_candidate_approve(p_id);
 return machimoa_review.admin_review_item('candidates',p_id);
end
$function$
;
revoke all on function public.admin_review_save_candidate(uuid,text,text,jsonb,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_review_save_candidate(uuid,text,text,jsonb,uuid) to postgres;
grant execute on function public.admin_review_save_candidate(uuid,text,text,jsonb,uuid) to service_role;
alter function public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid) rename to cf_base_pub_admin_myseoul_review_change;
alter function public.cf_base_pub_admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid) set schema machimoa_review;
revoke all on function machimoa_review.cf_base_pub_admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.admin_myseoul_review_change(p_id uuid, p_revision text, p_version text, p_disposition text, p_note text, p_content jsonb, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;begin
 item:=machimoa_review.cf_base_pub_admin_myseoul_review_change(p_id,p_revision,p_version,p_disposition,p_note,p_content,p_actor);
 perform machimoa_review.content_filter_candidate_approve(p_id);
 perform machimoa_review.content_filter_publish(p_id);
 return machimoa_review.admin_review_item('candidates',p_id);
end
$function$
;
revoke all on function public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid) to postgres;
grant execute on function public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid) to service_role;
alter function machimoa_review.publish_curation_candidate(uuid,text,text,boolean) rename to cf_base_publish_curation_candidate;
revoke all on function machimoa_review.cf_base_publish_curation_candidate(uuid,text,text,boolean) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION machimoa_review.publish_curation_candidate(p_candidate_id uuid, p_reviewed_by text, p_review_notes text DEFAULT NULL::text, p_allow_overwrite boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare result uuid;begin
 -- Validate before publication and update public projection in the same transaction.
 perform machimoa_review.content_filter_publish(p_candidate_id);
 result:=machimoa_review.cf_base_publish_curation_candidate(p_candidate_id,p_reviewed_by,p_review_notes,p_allow_overwrite);
 perform machimoa_review.content_filter_publish(p_candidate_id);
 return result;
end
$function$
;
revoke all on function machimoa_review.publish_curation_candidate(uuid,text,text,boolean) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.publish_curation_candidate(uuid,text,text,boolean) to postgres;
CREATE OR REPLACE FUNCTION public.admin_program_list(p_offset integer DEFAULT 0, p_limit integer DEFAULT 25)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare items jsonb;
begin
 if p_offset is null or p_offset not between 0 and 999999 or p_limit is null or p_limit not between 1 and 25 then
 raise exception using errcode='PT422',message='invalid_page';end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',id,'title',title,'reasons',reasons)),'[]') into items from (
 select s.id,s.normalized_payload->>'title' title,f.result->'reasons' reasons
 from machimoa_review.source_items s join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash
 where s.source_id='seoul_reservation' and not f.manual_excluded and (f.result->>'decision'='review_required' or not machimoa_review.content_filter_ready(s.id,s.revision_hash))
 and exists(select 1 from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash
 and j.processing_stage='content_review' and j.status in ('queued','claimed'))
 order by s.first_seen_at,s.id offset p_offset limit p_limit) q;
 return items;
end $function$
;
revoke all on function public.admin_program_list(integer,integer) from public,anon,authenticated,service_role;
grant execute on function public.admin_program_list(integer,integer) to postgres;
grant execute on function public.admin_program_list(integer,integer) to service_role;
alter function public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text) rename to cf_base_pub_enqueue_curation_candidate;
alter function public.cf_base_pub_enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text) set schema machimoa_review;
revoke all on function machimoa_review.cf_base_pub_enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.enqueue_curation_candidate(p_source text, p_source_item_id text, p_source_revision_hash text, p_slug text, p_title_ko text, p_content_ko text, p_raw_payload jsonb, p_ai_status_ko text, p_category text DEFAULT NULL::text, p_summary_ko text DEFAULT NULL::text, p_source_url text DEFAULT NULL::text, p_ai_model text DEFAULT NULL::text, p_title_ja text DEFAULT NULL::text, p_content_ja text DEFAULT NULL::text, p_summary_ja text DEFAULT NULL::text, p_ai_status_ja text DEFAULT NULL::text)
 RETURNS TABLE(candidate_id uuid, outcome text, superseded_candidate_id uuid)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 if exists(select 1 from machimoa_review.source_item_content_filters f join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash join machimoa_review.ingest_sources src on src.source_id=s.source_id where src.legacy_curation_source=p_source and s.external_key=p_source_item_id and s.revision_hash=p_source_revision_hash) then raise sqlstate 'PT409' using message='content_filter_fence_required';end if;
 return query select * from machimoa_review.cf_base_pub_enqueue_curation_candidate(p_source,p_source_item_id,p_source_revision_hash,p_slug,p_title_ko,p_content_ko,p_raw_payload,p_ai_status_ko,p_category,p_summary_ko,p_source_url,p_ai_model,p_title_ja,p_content_ja,p_summary_ja,p_ai_status_ja);
end
$function$
;
revoke all on function public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text) from public,anon,authenticated,service_role;
grant execute on function public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text) to postgres;
grant execute on function public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text) to service_role;

-- This owned reason family is re-evaluated by after_facts in the same transaction.
-- All pre-existing unsupported reasons retain the original rollback protection.
do $$ declare definition text;needle text:='if k not in (''policy_lifecycle_uncertain''';begin
 definition:=pg_get_functiondef('machimoa_review.cf_base_pub_admin_review_save_facts(uuid,text,text,jsonb,uuid)'::regprocedure);
 if (length(definition)-length(replace(definition,needle,'')))/length(needle)<>1 then raise exception 'content_filter_review_predecessor_changed';end if;
 execute replace(definition,needle,'if k not like ''content_filter:%'' and k not in (''policy_lifecycle_uncertain''');
end $$;

create function public.finish_content_filter_ai(p_job_id uuid,p_revision text,p_filter_version bigint,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_output jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;m machimoa_review.content_filter_claim_inputs%rowtype;f machimoa_review.source_item_content_filters%rowtype;r record;src text;k text;original_payload jsonb;
begin
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs job on job.source_item_id=si.id where job.id=p_job_id for update of si;
 if not found or s.source_id not in ('youthcenter_content','youthcenter_policy') or s.revision_hash is distinct from p_revision then raise sqlstate 'PT409' using message='content_filter_identity_changed';end if;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 select * into m from machimoa_review.content_filter_claim_inputs where job_id=p_job_id and claimed_at=p_claimed_at;
 select * into f from machimoa_review.source_item_content_filters where source_item_id=s.id and revision_hash=p_revision for share;
 if j.processing_stage<>'ai_enrichment' or j.status<>'claimed' or j.revision_hash is distinct from p_revision or j.claimed_at is distinct from p_claimed_at or j.claim_lease_until is distinct from p_lease_until or j.claimed_by is distinct from p_worker_id or j.claim_lease_until<=clock_timestamp() or m.job_id is null or m.worker_id is distinct from p_worker_id or m.lease_until is distinct from p_lease_until or m.filter_version is distinct from p_filter_version or f.filter_version is distinct from p_filter_version or not machimoa_review.content_filter_ready(s.id,p_revision) then raise sqlstate 'PT409' using message='content_filter_fence_lost';end if;
 if not machimoa_review.category_period_ready(s.id,p_revision) or s.disposition<>'target' or exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) or not exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id and enabled and permission_status in ('approved_noncommercial','approved_commercial')) then raise sqlstate 'PT409' using message='program_candidate_unavailable';end if;
 if p_output is null or jsonb_typeof(p_output)<>'object' or (select array_agg(key order by key) from jsonb_object_keys(p_output) key) is distinct from array['aiModel','contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 for k in select jsonb_object_keys(p_output) loop
 if jsonb_typeof(p_output->k)<>'string' or char_length(btrim(p_output->>k)) not between 1 and (case when k like 'title%' then 300 when k like 'summary%' then 1000 when k='aiModel' then 100 else 200000 end) then raise sqlstate 'PT422' using message='review_invalid_input';end if;end loop;
 select legacy_curation_source into src from machimoa_review.ingest_sources where source_id=s.source_id;
 select coalesce(jsonb_object_agg(key,value),'{}') into original_payload from jsonb_each(s.normalized_payload) where lower(key) not in ('atchfile','atch_file','facts','content_filter_context','filterfacts');
 select * into r from machimoa_review.cf_base_pub_enqueue_curation_candidate(src,s.external_key,p_revision,(case when s.source_id='youthcenter_policy' then 'policy-' else 'content-' end)||replace(s.external_key,':','-'),p_output->>'titleKo',p_output->>'contentKo',original_payload,'success',coalesce(s.normalized_payload->>'plcyTpNm',s.normalized_payload->>'pstSeNm','기타'),p_output->>'summaryKo',s.normalized_payload->>'source_url',p_output->>'aiModel',p_output->>'titleJa',p_output->>'contentJa',p_output->>'summaryJa','success');
 if r.outcome<>'inserted' then raise sqlstate 'PT409' using message='content_filter_input_changed';end if;
 perform machimoa_review.content_filter_candidate_capture(r.candidate_id,j.id,p_claimed_at);
 perform machimoa_review.complete_processing_job(j.id,p_worker_id);
 return jsonb_build_object('candidateId',r.candidate_id,'outcome','inserted');
end $$;

do $$ declare r record;begin
 for r in select c.oid::regclass name from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_review' and c.relname in ('source_item_content_filters','content_filter_edits','content_filter_claim_inputs','candidate_content_filters') loop
 execute format('alter table %s enable row level security',r.name);execute format('revoke all on table %s from public,anon,authenticated,service_role',r.name);end loop;
 for r in select p.oid::regprocedure name,n.nspname schema_name from pg_proc p join pg_namespace n on n.oid=p.pronamespace where (n.nspname='machimoa_review' and p.proname like 'content_filter_%') or (n.nspname='public' and p.proname in ('admin_content_filter_detail','admin_content_filter_save','finish_content_filter_ai')) loop
 execute format('revoke all on function %s from public,anon,authenticated,service_role',r.name);if r.schema_name='public' then execute format('grant execute on function %s to service_role',r.name);end if;end loop;
end $$;
update machimoa_review.content_filter_function_backup set installed=pg_get_functiondef(to_regprocedure(name)),installed_acl=(select proacl::text from pg_proc where oid=to_regprocedure(name)),base_installed=case when base_name is null then null else pg_get_functiondef(to_regprocedure(base_name)) end,base_installed_acl=(select proacl::text from pg_proc where oid=to_regprocedure(base_name));
create table machimoa_review.content_filter_installed_objects(kind text not null,name text not null,definition text not null,acl text,primary key(kind,name));
alter table machimoa_review.content_filter_installed_objects enable row level security;
revoke all on machimoa_review.content_filter_installed_objects from public,anon,authenticated,service_role;
insert into machimoa_review.content_filter_installed_objects select 'function',p.oid::regprocedure::text,pg_get_functiondef(p.oid),p.proacl::text from pg_proc p join pg_namespace n on n.oid=p.pronamespace where (n.nspname='machimoa_review' and p.proname like 'content_filter_%') or (n.nspname='public' and p.proname in ('admin_content_filter_detail','admin_content_filter_save','finish_content_filter_ai'));
insert into machimoa_review.content_filter_installed_objects select 'trigger','content_filter_claim_capture',pg_get_triggerdef(oid),null from pg_trigger where tgname='content_filter_claim_capture' and tgrelid='machimoa_review.processing_jobs'::regclass;

notify pgrst,'reload schema';
commit;
