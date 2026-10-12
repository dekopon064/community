begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- No backfill. Existing source/fact/filter/candidate rows are untouched by DDL.
do $$ declare r record;f record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values
 ('public.admin_program_detail(uuid)','e564132c488c95199bd49eab88ff7ab9c13857c16480a312732cd01cf295610d'),
 ('public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)','a21565421dd90f4cfd550405795f0eb9db2c3883f7b0b77ecf221cd251202e40'),
 ('public.admin_program_activity_confirm(uuid,text,text,bigint,bigint,jsonb,text,uuid)','804021aef8b68e93a25a41ab58221c820866754fc8f511814d00d313d6528739')
 ) x(signature,hash) loop
 select * into f from pg_proc where oid=to_regprocedure(r.signature);
 if f.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(f.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash
 or pg_get_userbyid(f.proowner)<>'postgres' or f.proconfig is distinct from array['search_path=""']::text[] or not f.prosecdef
 or f.proacl::text is distinct from '{postgres=X/postgres,service_role=X/postgres}'
 then raise exception 'seoul_filter_sync_predecessor_changed: %',r.signature;end if;
 end loop;
end $$;

-- Keep receipt/history data, retire the extra public confirmation command.
revoke all on function public.admin_program_activity_confirm(uuid,text,text,bigint,bigint,jsonb,text,uuid) from public,anon,authenticated,service_role;
create or replace function public.admin_program_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare d jsonb;begin
 d:=machimoa_review.ai_recheck_base_program_detail(p_id);
 if d->>'status'<>'excluded' and machimoa_review.ai_recheck_pending(p_id,d->>'revision') then
  d:=d||jsonb_build_object('editableFields',to_jsonb(machimoa_review.ai_recheck_edit_fields('seoul_reservation')),'status','open','result',(d->'result')||jsonb_build_object('reasons',coalesce(d->'result'->'reasons','[]')||jsonb_build_array('ai_recheck_requested')));
 end if;
 return jsonb_set(d,'{activityReview,pending}','false'::jsonb);
end $$;

-- Called only after the ordinary authenticated filter save and its fences.
-- A manual filter selection is a review action, never a fabricated source quote.
create function machimoa_review.seoul_filter_facts_sync(p_id uuid,p_revision text,p_actor uuid) returns boolean
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;pf machimoa_review.source_item_program_facts%rowtype;
 cf machimoa_review.source_item_content_filters%rowtype;next_f jsonb;mode text;region text;ev bigint;reasons jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id;
 if s.source_id<>'seoul_reservation' then return false;end if;
 select * into pf from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision;
 select * into cf from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision;
 if pf.manual_excluded or cf.data->>'category'<>'program'
 or exists(select 1 from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision)
 or cf.origins->>'delivery' is distinct from 'operator' or cf.origins->>'location' is distinct from 'operator'
 or cf.data->'delivery'->>'status'<>'known' then return false;end if;
 reasons:=machimoa_review.program_evaluate_reviewed(pf.facts,statement_timestamp(),p_id,p_revision)->'reasons';
 if not (reasons ?| array['delivery_mode_unknown','activity_location_unknown']) then return false;end if;
 mode:=case cf.data->'delivery'->>'value' when 'onsite' then 'offline' when 'mixed' then 'hybrid' when 'online' then 'online' end;
 if mode='online' and cf.data->'location'->>'status'='not_applicable' then region:='not_applicable';
 elsif mode in ('offline','hybrid') and cf.data->'location'->>'status'='known'
 and cf.data->'location'->'value'->>'scope'='specific'
 and jsonb_array_length(cf.data->'location'->'value'->'venues')>0
 and not exists(select 1 from jsonb_array_elements(cf.data->'location'->'value'->'venues') v where v->>'province' not in ('11','28','41')) then region:='capital';
 else return false;end if;
 if pf.facts->>'delivery_mode' not in ('unknown',mode) or pf.facts->>'activity_region' not in ('unknown',region)
 then raise sqlstate 'PT422' using message='content_filter_facts_mismatch';end if;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed')
 or exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='ai_enrichment' and status in ('failed','completed'))
 or exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
 or machimoa_review.admin_trash_pending(p_id,p_revision)
 then raise sqlstate 'PT409' using message='review_conflict';end if;
 next_f:=pf.facts||jsonb_build_object('delivery_mode',mode,'activity_region',region);
 next_f:=jsonb_set(next_f,'{missing}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_f->'missing') where value#>>'{}' not in ('delivery_mode_unknown','activity_location_unknown')),'[]'));
 -- Other missing/conflicting facts, raw evidence and operator notes are preserved.
 perform machimoa_review.program_validate(next_f);
 update machimoa_review.source_item_program_facts set facts=next_f,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 update machimoa_review.source_item_content_filters set source_binding=machimoa_review.content_filter_binding(p_id,p_revision)
 where source_item_id=p_id and revision_hash=p_revision;
 if not machimoa_review.content_filter_consistent(p_id,p_revision,cf.data) then raise sqlstate 'PT422' using message='content_filter_facts_mismatch';end if;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,'필터 저장값을 사실 판정에 연결했습니다.',array['linked:delivery_mode','linked:activity_region']) returning id into ev;
 if mode in ('offline','hybrid') then
 insert into machimoa_review.seoul_activity_confirmations values(ev,p_id,p_revision,pf.facts_version,pf.facts_version+1,cf.filter_version,
 machimoa_review.seoul_activity_binding(next_f,cf.data),jsonb_build_object('revision',p_revision,'officialUrl',s.normalized_payload->'source_url'));
 end if;
 perform machimoa_review.program_refresh(p_id);
 perform machimoa_review.content_filter_review_sync(p_id,p_revision);
 return true;
end $$;
revoke all on function machimoa_review.seoul_filter_facts_sync(uuid,text,uuid) from public,anon,authenticated,service_role;

alter function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) rename to seoul_before_filter_fact_sync;
alter function public.seoul_before_filter_fact_sync(uuid,text,text,bigint,jsonb,uuid) set schema machimoa_review;
revoke all on function machimoa_review.seoul_before_filter_fact_sync(uuid,text,text,bigint,jsonb,uuid) from public,anon,authenticated,service_role;
create function public.admin_content_filter_save(p_id uuid,p_revision text,p_version text,p_filter_version bigint,p_patch jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
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
 if s.source_id='seoul_reservation' then perform machimoa_review.seoul_filter_facts_sync(p_id,p_revision,p_actor);end if;
 return public.admin_content_filter_detail(p_id);
end $$;
revoke all on function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) to service_role;
commit;
