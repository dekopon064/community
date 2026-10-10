-- Explicit administrator judgment, separate from source facts. No backfill or execution.
begin;
set local lock_timeout='5s';set local statement_timeout='30s';
do $$ begin
if current_user<>'postgres' then raise exception 'postgres_required';end if;
if to_regprocedure('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'38c9f663f0838ea7c7441ce468e417fb26d64aa2373cf811f06f80cb6bffa928' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)';end if;
if to_regprocedure('public.admin_myseoul_program_detail(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('public.admin_myseoul_program_detail(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'ca6aba94742ff5176e456feeaf64215991b9e608d6e8257b44d13894e4a2ac88' or (select proacl::text from pg_proc where oid=to_regprocedure('public.admin_myseoul_program_detail(uuid)')) is distinct from '{postgres=X/postgres,service_role=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('public.admin_myseoul_program_detail(uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('public.admin_myseoul_program_detail(uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','public.admin_myseoul_program_detail(uuid)';end if;
if to_regprocedure('machimoa_review.myseoul_admin_lock(uuid,text,text,uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.myseoul_admin_lock(uuid,text,text,uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'1432dbe8a4453ff0fd9cd3aef982011216870f50f6831e1d81a2b5c3322a7353' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_admin_lock(uuid,text,text,uuid)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_admin_lock(uuid,text,text,uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_admin_lock(uuid,text,text,uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','machimoa_review.myseoul_admin_lock(uuid,text,text,uuid)';end if;
if to_regprocedure('public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'6893a3debf5321edf8426fc06b27a8c61a1419e0e7fcea87e289714e82409835' or (select proacl::text from pg_proc where oid=to_regprocedure('public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)')) is distinct from '{postgres=X/postgres,service_role=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)';end if;
if to_regprocedure('machimoa_review.myseoul_refresh(uuid,timestamp with time zone)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.myseoul_refresh(uuid,timestamp with time zone)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'7ba8661546d6d4d951ca213a8ccee0e97c3c9a83b035cf5e7b38534721d2b4e8' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_refresh(uuid,timestamp with time zone)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_refresh(uuid,timestamp with time zone)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_refresh(uuid,timestamp with time zone)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','machimoa_review.myseoul_refresh(uuid,timestamp with time zone)';end if;
if to_regprocedure('machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'4bb1b878e20fcb56c888912f65b86209fdb2a0fbee912e9930e5d38e7590c98e' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)';end if;
if to_regprocedure('public.admin_review_exclude_reason(uuid,text,text,text,text,uuid,uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('public.admin_review_exclude_reason(uuid,text,text,text,text,uuid,uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'c8cf4963a8febfae571868f7626174d49a07e1f1b89e153bae921aaf903f201b' or (select proacl::text from pg_proc where oid=to_regprocedure('public.admin_review_exclude_reason(uuid,text,text,text,text,uuid,uuid)')) is distinct from '{postgres=X/postgres,service_role=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('public.admin_review_exclude_reason(uuid,text,text,text,text,uuid,uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('public.admin_review_exclude_reason(uuid,text,text,text,text,uuid,uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','public.admin_review_exclude_reason(uuid,text,text,text,text,uuid,uuid)';end if;
if to_regprocedure('public.admin_review_restore(uuid,text,text,uuid,uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('public.admin_review_restore(uuid,text,text,uuid,uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'0f1e9fb1edf38a8e7db9d0b219e52a1eb465214e617afbf46368605eedda580c' or (select proacl::text from pg_proc where oid=to_regprocedure('public.admin_review_restore(uuid,text,text,uuid,uuid)')) is distinct from '{postgres=X/postgres,service_role=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('public.admin_review_restore(uuid,text,text,uuid,uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('public.admin_review_restore(uuid,text,text,uuid,uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','public.admin_review_restore(uuid,text,text,uuid,uuid)';end if;
if to_regprocedure('machimoa_review.classification_native(uuid)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.classification_native(uuid)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'fd1f88f8e33d65cf2a39bcf59f51fd2ac1f4e90d9eb08216683accadac7210e1' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.classification_native(uuid)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.classification_native(uuid)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.classification_native(uuid)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','machimoa_review.classification_native(uuid)';end if;
if to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'85a3d04d2359a278ee6a34d7717ed53fcad5fa4a12abb9f6fa01a545f31210af' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','machimoa_review.classification_reasons(uuid,jsonb)';end if;
if to_regprocedure('machimoa_review.classification_table_metadata(text)') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.classification_table_metadata(text)')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'fc280d69b3db727c0b1007895efcb189cafd8d8bd63c317d89be841354353b3f' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.classification_table_metadata(text)')) is distinct from '{postgres=X/postgres}' or (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.classification_table_metadata(text)'))<>'postgres' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.classification_table_metadata(text)')) is distinct from array['search_path=""']::text[] then raise exception 'residence_predecessor_changed: %','machimoa_review.classification_table_metadata(text)';end if;
if to_regclass('machimoa_review.myseoul_residence_reviews') is not null or to_regprocedure('public.admin_myseoul_residence_confirm(uuid,text,text,boolean,text,text,jsonb,uuid,uuid)') is not null then raise exception 'residence_name_collision';end if;
end $$;
create table machimoa_review.residence_function_backup(name text primary key,definition text not null,metadata jsonb not null);
insert into machimoa_review.residence_function_backup
select v.name,pg_get_functiondef(p.oid),jsonb_build_object('acl',p.proacl::text,'owner',pg_get_userbyid(p.proowner),'config',p.proconfig)
from (values ('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)'),('public.admin_myseoul_program_detail(uuid)'))v(name) join pg_proc p on p.oid=to_regprocedure(v.name);
create table machimoa_review.myseoul_residence_reviews(
 request_id uuid primary key,event_id bigint not null unique references machimoa_review.admin_review_events(id),
 source_item_id uuid not null references machimoa_review.source_items(id),revision_hash text not null check(revision_hash ~ '^[a-f0-9]{64}$'),
 context_hash text not null check(context_hash ~ '^[a-f0-9]{64}$'),decision text not null check(decision in ('no_restriction','restricted')),
 actor uuid not null,input jsonb not null,active boolean not null default true,confirmed_at timestamptz not null default clock_timestamp());
create unique index myseoul_residence_active on machimoa_review.myseoul_residence_reviews(source_item_id,revision_hash) where active;
create function machimoa_review.myseoul_residence_context(f jsonb) returns text
language sql immutable set search_path='' as $$
select encode(sha256(convert_to(jsonb_build_array(f->'official_url',f->'source_revision',f->'delivery_mode',f->'application_actor',f->'target',f->'description',f->'qualification_note',f->'conditions',f->'residence_scope',f->'residence',f->'residence_evidence',f->'scope_exclusions',f->'conflicts',f->'evidence',
 coalesce((select jsonb_agg(v order by v::text) from jsonb_array_elements(f->'issues')v where v->>'code'<>'online_residence_unknown'),'[]'::jsonb))::text,'UTF8')),'hex')
$$;
create function machimoa_review.myseoul_residence_confirmed(f jsonb) returns boolean
language sql stable set search_path='' as $$
select exists(select 1 from machimoa_review.myseoul_residence_reviews r
 join machimoa_review.source_items s on s.id=r.source_item_id and s.source_id='myseoul_program' and s.revision_hash=r.revision_hash
 join machimoa_review.source_item_program_facts p on p.source_item_id=s.id and p.revision_hash=r.revision_hash
 where r.active and r.decision='no_restriction' and not p.manual_excluded and r.revision_hash=f->>'source_revision'
 and p.observed_facts->>'official_url'=f->>'official_url' and r.context_hash=machimoa_review.myseoul_residence_context(f))
$$;
create function machimoa_review.invalidate_myseoul_residence() returns trigger
language plpgsql set search_path='' as $$ begin
if tg_table_name='source_items' then
 if old.revision_hash is distinct from new.revision_hash then
 update machimoa_review.myseoul_residence_reviews set active=false where source_item_id=new.id and active;
 end if;return new;
end if;
if old.manual_excluded is distinct from new.manual_excluded or machimoa_review.myseoul_residence_context(old.facts) is distinct from machimoa_review.myseoul_residence_context(new.facts) then
update machimoa_review.myseoul_residence_reviews set active=false where source_item_id=new.source_item_id and revision_hash=new.revision_hash and active;end if;
return new;end $$;
create trigger invalidate_myseoul_residence before update on machimoa_review.source_item_program_facts for each row execute function machimoa_review.invalidate_myseoul_residence();
create trigger invalidate_myseoul_residence_revision before update of revision_hash on machimoa_review.source_items for each row execute function machimoa_review.invalidate_myseoul_residence();
do $$ declare d text;anchor text;begin
 d:=pg_get_functiondef('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)'::regprocedure);
 anchor:='elsif f->>''residence_scope'' not in (''nationwide'',''includes_capital'',''capital'') or f->''residence_evidence''=''[]''::jsonb then';
 if position(anchor in d)=0 then raise exception 'residence_evaluator_anchor_missing';end if;
 execute replace(d,anchor,'elsif (f->>''residence_scope'' not in (''nationwide'',''includes_capital'',''capital'') or f->''residence_evidence''=''[]''::jsonb) and not machimoa_review.myseoul_residence_confirmed(f) then');
 d:=pg_get_functiondef('public.admin_myseoul_program_detail(uuid)'::regprocedure);
 anchor:='return item;';
 if position(anchor in d)=0 then raise exception 'residence_detail_anchor_missing';end if;
 execute replace(d,anchor,'return item||jsonb_build_object(''residenceReview'',jsonb_build_object(''confirmed'',not (item->''result''->''reasons'') ? ''online_residence_unknown'' and item->''facts''->>''delivery_mode''=''online'' and (machimoa_review.myseoul_residence_confirmed(item->''facts'') or item->''facts''->>''residence_scope'' in (''nationwide'',''includes_capital'',''capital'') and item->''facts''->''residence_evidence''<>''[]''::jsonb), ''basis'',case when machimoa_review.myseoul_residence_confirmed(item->''facts'') then ''operator_no_restriction'' when item->''facts''->>''residence_scope'' in (''nationwide'',''includes_capital'',''capital'') and item->''facts''->''residence_evidence''<>''[]''::jsonb then ''source_evidence'' else ''unconfirmed'' end));');
end $$;
create function public.admin_myseoul_residence_confirm(p_id uuid,p_revision text,p_version text,p_restricted boolean,p_scope text,p_condition text,p_evidence jsonb,p_actor uuid,p_request uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item jsonb;f jsonb;input jsonb;prior machimoa_review.myseoul_residence_reviews%rowtype;eid bigint;ctx text;
begin
if p_request is null or p_actor is null or p_restricted is null or p_scope is null or p_condition is null or p_evidence is null then raise sqlstate 'PT422' using message='invalid_myseoul_command';end if;
input:=jsonb_build_array(p_id,p_revision,p_version,p_restricted,p_scope,p_condition,p_evidence);
perform 1 from machimoa_review.source_items where id=p_id and source_id='myseoul_program' and revision_hash=p_revision for update;
if not found then raise sqlstate 'PT409' using message='myseoul_version_conflict';end if;
select * into prior from machimoa_review.myseoul_residence_reviews where request_id=p_request;
if found then
 if prior.actor<>p_actor or prior.input<>input then raise sqlstate 'PT422' using message='invalid_myseoul_command';end if;
 if not prior.active then raise sqlstate 'PT409' using message='myseoul_version_conflict';end if;
 return public.admin_myseoul_program_detail(p_id);
end if;
item:=machimoa_review.myseoul_admin_lock(p_id,p_revision,p_version,p_actor);f:=item->'facts';
if f->>'delivery_mode'<>'online' or not (item->'result'->'reasons') ? 'online_residence_unknown' then raise sqlstate 'PT409' using message='myseoul_already_processed';end if;
if exists(select 1 from jsonb_array_elements(f->'conflicts')v where v->>'field' in ('residence','target','mode')) or exists(select 1 from jsonb_array_elements_text(item->'result'->'reasons')v where v like 'source_change_conflict:%' or v like 'source_fact_conflict:%') then raise sqlstate 'PT409' using message='myseoul_version_conflict';end if;
if p_restricted then
 if p_scope not in ('capital','includes_capital') or btrim(p_condition)='' then raise sqlstate 'PT422' using message='invalid_myseoul_command';end if;
 item:=public.admin_myseoul_program_save_v2(p_id,p_revision,p_version,jsonb_build_object('residence_scope',p_scope,'residence',p_condition,'residence_evidence',p_evidence),p_actor);
 if (item->'result'->'reasons') ? 'online_residence_unknown' then raise sqlstate 'PT422' using message='invalid_myseoul_command';end if;
 f:=item->'facts';
else
 if p_scope<>'' or p_condition<>'' or p_evidence<>'[]'::jsonb or f->>'residence_scope' not in ('unknown','nationwide') then raise sqlstate 'PT422' using message='invalid_myseoul_command';end if;
 -- Resolve only this explicit review reason; never change the source scope or evidence.
 f:=jsonb_set(f,'{issues}',coalesce((select jsonb_agg(v) from jsonb_array_elements(f->'issues')v where v->>'code'<>'online_residence_unknown'),'[]'::jsonb));
 update machimoa_review.source_item_program_facts set facts=f,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision;
end if;
update machimoa_review.myseoul_residence_reviews set active=false where source_item_id=p_id and revision_hash=p_revision and active;
insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
values(p_id,p_revision,'save_facts',p_actor,case when p_restricted then '참가 거주 조건 확인' else '원문 대상·신청 조건 검토 후 거주 지역 제한 없음으로 판단 · 원문 명시와 구분' end,array['residence_review']) returning id into eid;
ctx:=machimoa_review.myseoul_residence_context(f);
insert into machimoa_review.myseoul_residence_reviews(request_id,event_id,source_item_id,revision_hash,context_hash,decision,actor,input)
values(p_request,eid,p_id,p_revision,ctx,case when p_restricted then 'restricted' else 'no_restriction' end,p_actor,input);
perform machimoa_review.myseoul_refresh(p_id);
return public.admin_myseoul_program_detail(p_id);
end $$;
create table machimoa_review.residence_installed_objects(name text primary key,kind text not null,definition text not null,metadata jsonb);
do $$ declare r record;begin
for r in select p.oid,p.oid::regprocedure::text name from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_review' and p.proname in ('myseoul_residence_context','myseoul_residence_confirmed','invalidate_myseoul_residence') or n.nspname='public' and p.proname='admin_myseoul_residence_confirm' loop
execute 'revoke all on function '||r.name||' from public,anon,authenticated,service_role';end loop;
end $$;
grant execute on function public.admin_myseoul_residence_confirm(uuid,text,text,boolean,text,text,jsonb,uuid,uuid) to service_role;
alter table machimoa_review.residence_function_backup enable row level security;
alter table machimoa_review.myseoul_residence_reviews enable row level security;
alter table machimoa_review.residence_installed_objects enable row level security;
revoke all on machimoa_review.residence_function_backup,machimoa_review.myseoul_residence_reviews,machimoa_review.residence_installed_objects from public,anon,authenticated,service_role;
insert into machimoa_review.residence_installed_objects
select v.name,'function',pg_get_functiondef(p.oid),jsonb_build_object('acl',p.proacl::text,'owner',pg_get_userbyid(p.proowner),'config',p.proconfig)
from (values ('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)'),('public.admin_myseoul_program_detail(uuid)'),('machimoa_review.myseoul_residence_context(jsonb)'),('machimoa_review.myseoul_residence_confirmed(jsonb)'),('machimoa_review.invalidate_myseoul_residence()'),('public.admin_myseoul_residence_confirm(uuid,text,text,boolean,text,text,jsonb,uuid,uuid)'))v(name) join pg_proc p on p.oid=to_regprocedure(v.name);
insert into machimoa_review.residence_installed_objects select name,'table',machimoa_review.classification_table_metadata(name)::text,null from (values ('machimoa_review.myseoul_residence_reviews'),('machimoa_review.residence_function_backup'),('machimoa_review.residence_installed_objects'))v(name);
insert into machimoa_review.residence_installed_objects select tgname,'trigger',pg_get_triggerdef(oid),jsonb_build_object('table',tgrelid::regclass::text) from pg_trigger where tgrelid='machimoa_review.source_item_program_facts'::regclass and tgname='invalidate_myseoul_residence' or tgrelid='machimoa_review.source_items'::regclass and tgname='invalidate_myseoul_residence_revision';
notify pgrst,'reload schema';commit;
