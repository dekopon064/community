begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- Local contract only: no backfill, observation changes, AI or candidate writes.
do $$ declare r record;f record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values
 ('public.admin_program_detail(uuid)','c6b93405aba556a5e5ef193e9a2c3ef8aeb6d0bb550ea6ca4e2348af22314922'),
 ('public.admin_program_activity_confirm(uuid,text,text,bigint,bigint,jsonb,text,uuid)','5b227b6eb3b53f41fcd38e7bdc00f5cdc187749e95790b33f442674238ebf44a')
 ) x(signature,hash) loop
 select * into f from pg_proc where oid=to_regprocedure(r.signature);
 if f.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(f.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash
 or pg_get_userbyid(f.proowner)<>'postgres' or f.proconfig is distinct from array['search_path=""']::text[] or not f.prosecdef
 or f.proacl::text is distinct from '{postgres=X/postgres,service_role=X/postgres}'
 then raise exception 'seoul_delivery_predecessor_changed: %',r.signature;end if;
 end loop;
end $$;

CREATE OR REPLACE FUNCTION public.admin_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare d jsonb;begin
 d:=machimoa_review.ai_recheck_base_program_detail(p_id);
 if d->>'status'<>'excluded' and machimoa_review.ai_recheck_pending(p_id,d->>'revision') then
  d:=d||jsonb_build_object('editableFields',to_jsonb(machimoa_review.ai_recheck_edit_fields('seoul_reservation')),'status','open','result',(d->'result')||jsonb_build_object('reasons',coalesce(d->'result'->'reasons','[]')||jsonb_build_array('ai_recheck_requested')));
 end if;
 -- A saved filter is not a completed fact check. Advertise the explicit
 -- confirmation action only for the existing onsite/mixed capital contract.
 if (d->'result'->'reasons') ? 'delivery_mode_unknown'
 and d#>>'{facts,delivery_mode}' in ('unknown',case d#>>'{filterInfo,data,delivery,value}' when 'onsite' then 'offline' when 'mixed' then 'hybrid' end)
 and d#>>'{facts,activity_region}' in ('unknown','capital')
 and d#>>'{filterInfo,data,delivery,status}'='known'
 and d#>>'{filterInfo,data,delivery,value}' in ('onsite','mixed')
 and d#>>'{filterInfo,data,location,status}'='known'
 and d#>>'{filterInfo,data,location,value,scope}'='specific'
 and jsonb_array_length(coalesce(d#>'{filterInfo,data,location,value,venues}','[]'))>0
 and not exists(select 1 from jsonb_array_elements(d#>'{filterInfo,data,location,value,venues}') v
 where v->>'province' not in ('11','28','41')) then
  d:=jsonb_set(d,'{activityReview,pending}','true'::jsonb);
 end if;return d;
end $function$
;

create or replace function public.admin_program_activity_confirm(p_id uuid,p_revision text,p_version text,p_facts_version bigint,
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
 next_f:=jsonb_set(next_f,'{missing}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_f->'missing') where value#>>'{}' not in ('activity_location_unknown','delivery_mode_unknown')),'[]'));
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
 values(p_id,p_revision,'save_facts',p_actor,p_note,array['confirmed:activity_region','confirmed:delivery_mode']) returning id into ev;
 insert into machimoa_review.seoul_activity_confirmations values(ev,p_id,p_revision,f.facts_version,f.facts_version+1,cf.filter_version+1,
 machimoa_review.seoul_activity_binding(next_f,d),jsonb_build_object('revision',p_revision,'officialUrl',s.normalized_payload->'source_url'));
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $$;

commit;
