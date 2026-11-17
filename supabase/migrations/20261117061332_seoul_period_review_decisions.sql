begin;
set local lock_timeout='5s';
do $$ begin
 if encode(sha256(convert_to(replace(pg_get_functiondef('public.admin_program_save(uuid,text,text,jsonb,text[],text,uuid)'::regprocedure),chr(13),''),'UTF8')),'hex') <> '7ab355073b74191e03aad101f8d26e96f3cb7e50867110e7c1d0dd2a495b4225' then
 raise exception 'unexpected_program_save_predecessor'; end if;
end $$;

-- Strict bridge for legacy observations; input text, structured periods and existing operator decisions remain intact.
create function machimoa_review.seoul_annual_period(f jsonb) returns boolean
language sql immutable set search_path='' as $$
 select f->'missing' ? 'body_period_needs_confirmation'
 and not (((f->'missing') || (f->'conflicts')) ?| array['body_api_period_conflict','invalid_body_date','date_weekday_conflict','period_missing_or_unparsed','period_order_conflict'])
 and jsonb_array_length(f->'period_evidence')>0
 and not exists(select 1 from jsonb_array_elements_text(f->'period_evidence') e
                where e<>'및 요일' and e !~ '^연중(\s*운영)?(\s*\(\s*1월\s*[~～]\s*12월\s*\))?$')
 and exists(select 1 from jsonb_array_elements_text(f->'period_evidence') e
            where e like '연중%' and exists(select 1 from regexp_split_to_table(f->>'description',E'\n') line
              where btrim(line) ~ '^(운영|진행)\s*기간\s*[:：]' and btrim(regexp_replace(line,'^[^:：]+[:：]',''))=e))
 and not exists(select 1 from regexp_split_to_table(f->>'description',E'\n') line
                where line ~ '(신청|모집|접수)\s*기간.*연중')
 and f->'periods' ?& array['RCPTBGNDT','RCPTENDDT','SVCOPNBGNDT','SVCOPNENDDT']
 and not exists(select 1 from jsonb_each(f->'periods') x where x.value->>'status' is distinct from 'ok')
$$;

create function machimoa_review.program_save_decision(p_id uuid, p_revision text, p_version text, p_patch jsonb, p_resolve text[], p_note text, p_actor uuid, p_decision text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; item jsonb;
 next_facts jsonb; field text; reason text; allowed text[]:='{}'; active text[]; changed text[]:='{}'; d jsonb; same_period boolean:=false;
begin
 p_note:=btrim(coalesce(p_note,''));
 if p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$'
 or p_patch is null or jsonb_typeof(p_patch)<>'object' or p_resolve is null or cardinality(p_resolve)>30
 or char_length(btrim(coalesce(p_note,'')))>4000 then
 raise exception using errcode='PT422',message='invalid_program_command';end if;
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 if s.revision_hash<>p_revision then raise exception using errcode='PT409',message='source_revision_conflict';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 item:=public.admin_program_detail(p_id);
 if item->>'version'<>p_version then raise exception using errcode='PT409',message='program_version_conflict';end if;
 if item->>'status'<>'open' or not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='content_review' and status='queued') then
 raise exception using errcode='PT409',message='program_already_processed';end if;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
 raise exception using errcode='PT409',message='program_processing_active';end if;
 perform machimoa_review.ai_recheck_edit_guard(p_id,p_revision);
 if machimoa_review.ai_recheck_pending(p_id,p_revision) then allowed:=machimoa_review.ai_recheck_edit_fields(s.source_id);end if;
 active:=array(select jsonb_array_elements_text(f.result->'reasons'));
 foreach reason in array active loop allowed:=allowed||machimoa_review.program_reason_fields(reason);end loop;
 for field in select jsonb_object_keys(p_patch) loop
   if not field=any(allowed) then raise exception using errcode='PT422',message='program_field_read_only';end if;
   if p_patch->field is distinct from f.facts->field then changed:=array_append(changed,field);end if;
 end loop;
 same_period:=cardinality(changed)=0 and p_patch=jsonb_build_object('periods',f.facts->'periods')
 and p_resolve=array['body_period_needs_confirmation']::text[]
 and active @> p_resolve and machimoa_review.seoul_same_period_supported(f.facts);
 if p_decision is not null then
   if p_decision not in ('keep','edit','hold','annual') or p_note <> '' or (not (p_patch ? 'periods') or p_patch - 'periods' <> '{}'::jsonb)
      or not (active @> p_resolve and p_resolve @> array(select r from unnest(active) r where r=any(array['body_period_needs_confirmation','body_api_period_conflict','date_weekday_conflict','invalid_body_date','period_missing_or_unparsed','period_order_conflict'])))
      or cardinality(p_resolve)=0 or not (p_resolve <@ array['body_period_needs_confirmation','body_api_period_conflict','date_weekday_conflict','invalid_body_date','period_missing_or_unparsed','period_order_conflict'])
      or item->>'restoredReviewPending'='true' or machimoa_review.ai_recheck_pending(p_id,p_revision)
      or ((p_decision='edit') <> (cardinality(changed)>0)) then
      raise exception using errcode='PT422',message='invalid_period_decision';
   end if;
   if p_decision='annual' and (p_resolve<>array['body_period_needs_confirmation']
      or machimoa_review.seoul_annual_period(f.facts) is not true
      or f.facts->'periods' is distinct from item->'observedFacts'->'periods'
      or f.facts->'period_evidence' is distinct from item->'observedFacts'->'period_evidence'
      or f.facts->'description' is distinct from item->'observedFacts'->'description'
      or exists(select 1 from machimoa_review.admin_review_events e where e.source_item_id=p_id and e.revision_hash=p_revision
                and e.changed_fields && array['periods','period_evidence','period:hold','period:edit','period:keep'])) then
      raise exception using errcode='PT409',message='annual_review_ineligible';
   end if;
   same_period:=p_decision in ('keep','annual','hold');
 end if;
 if cardinality(changed)=0 and not same_period then raise exception using errcode='PT422',message='program_change_required';end if;
 if same_period or p_decision='edit' then
   perform pg_advisory_xact_lock(hashtextextended('seoul_reservation'||':'||s.external_key,0));
   perform 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key for update;
   if exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
   or exists(select 1 from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision)
   or exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='ai_enrichment' and status in ('completed','failed'))
   then raise sqlstate 'PT409' using message='program_reconfirmation_blocked';end if;
 end if;
 if p_decision='hold' then
   update machimoa_review.source_item_program_facts set facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
    where source_item_id=p_id and revision_hash=p_revision;
   insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
    values(p_id,p_revision,'save_facts',p_actor,'기간 원문 확인 보류',array['period:hold']);
   return public.admin_program_detail(p_id);
 end if;
 next_facts:=f.facts||p_patch;
 foreach reason in array p_resolve loop
   if reason is null or not reason=any(active) or not (same_period or changed && array(select x from unnest(machimoa_review.program_reason_fields(reason)) x where x not in ('activity_evidence','residence_evidence','period_evidence'))) then
   raise exception using errcode='PT422',message='program_reason_not_resolved';end if;
   next_facts:=jsonb_set(next_facts,'{missing}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'missing') where value#>>'{}'<>reason),'[]'));
   next_facts:=jsonb_set(next_facts,'{conflicts}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'conflicts') where value#>>'{}'<>reason),'[]'));
 end loop;
 if p_decision='edit' then
   select string_agg(x.key||': '||coalesce(f.facts->'periods'->x.key->>'value','—')||' → '||coalesce(x.value->>'value','—'), '; ' order by x.key)
    into p_note from jsonb_each(p_patch->'periods') x where x.value is distinct from f.facts->'periods'->x.key;
 end if;
 perform machimoa_review.program_validate(next_facts);
 -- A resolution must supply actual facts, not merely remove a diagnostic flag.
 if next_facts->>'official_url'='' and 'missing_source_url'=any(p_resolve) or
 char_length(btrim(next_facts->>'description'))<20 and p_resolve && array['attachment_dependent','program_description_missing'] then
 raise exception using errcode='PT422',message='program_evidence_required';end if;
 if p_resolve && array['period_missing_or_unparsed','period_order_conflict','body_period_needs_confirmation','date_weekday_conflict','body_api_period_conflict','invalid_body_date'] then
   for d in select value from jsonb_each(next_facts->'periods') loop
     if d->>'status'<>'ok' then raise exception using errcode='PT422',message='period_still_missing';end if;
   end loop;
   if machimoa_review.program_evaluate(next_facts,clock_timestamp())->'reasons' ? 'period_order_conflict' then
     raise exception using errcode='PT422',message='invalid_period_order';end if;
 end if;
 update machimoa_review.source_item_program_facts set facts=next_facts,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,p_note,(case when same_period then array['reconfirmed:periods'] else changed end)||(case when p_decision is null then '{}'::text[] else array['period:'||p_decision] end)||array(select 'resolved:'||x from unnest(p_resolve) x));
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $function$;

revoke all on function machimoa_review.seoul_annual_period(jsonb), machimoa_review.program_save_decision(uuid,text,text,jsonb,text[],text,uuid,text) from public,anon,authenticated,service_role;

create or replace function public.admin_program_save(p_id uuid,p_revision text,p_version text,p_patch jsonb,p_resolve text[],p_note text,p_actor uuid)
returns jsonb language sql security definer set search_path='' as $$
 select machimoa_review.program_save_decision(p_id,p_revision,p_version,p_patch,p_resolve,p_note,p_actor,null)
$$;

create function public.admin_program_period_decision(p_id uuid,p_revision text,p_version text,p_patch jsonb,p_resolve text[],p_note text,p_actor uuid,p_decision text)
returns jsonb language sql security definer set search_path='' as $$
 select machimoa_review.program_save_decision(p_id,p_revision,p_version,p_patch,p_resolve,p_note,p_actor,p_decision)
$$;
revoke all on function public.admin_program_period_decision(uuid,text,text,jsonb,text[],text,uuid,text) from public,anon,authenticated;
grant execute on function public.admin_program_period_decision(uuid,text,text,jsonb,text[],text,uuid,text) to service_role;
commit;
