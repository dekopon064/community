begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
-- DDL only; no backfill or reassessment of existing rows.
do $$ declare r record;p record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values
 ('admin_program_save(uuid,text,text,jsonb,text[],text,uuid)','1fb3ec3da3da97a3d4979a5cf4afd8f4b5caaf2fdd0b99e8db7da2ff622dddc7','{postgres=X/postgres,service_role=X/postgres}'),
 ('machimoa_review.program_evaluate_with_confirmation(jsonb,timestamp with time zone,boolean)','f15c8062e4faba13e5bcd761f5257b7c663851e023de7a229f0722d53bfeb976','{postgres=X/postgres}'),
 ('machimoa_review.classification_validate(jsonb,jsonb)','a6dbe7e60652dea32953ec8b938c9c2ec69672ffaff518e7059234db686616f7','{postgres=X/postgres}'),
 ('admin_review_reclassify(uuid,text,text,bigint,jsonb,jsonb,text,uuid)','84a635a680140c0999528d01d9a413e05cd85ca92e05156ddb8887ab064ec10b','{postgres=X/postgres,service_role=X/postgres}'),
 ('machimoa_review.myseoul_evaluate(jsonb,timestamp with time zone)','b44ea7d872e39133ed9a5291a279dbd893f829c3cd2f28bb4dffc7209435200f','{postgres=X/postgres}'),
 ('admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)','5646b279113d847efd1c2bec01f4fa11a8ce68f6e88e3b76c7a4f96fb13a3a21','{postgres=X/postgres,service_role=X/postgres}'),
 ('machimoa_review.myseoul_reason_fields(text)','34efa4fac23acbbfdbd8b49ebfceb3219445c5c5e3993d91fcaee09aece1ded9','{postgres=X/postgres}')
 ) v(signature,hash,acl) loop
 select * into p from pg_proc where oid=to_regprocedure(r.signature);
 if p.oid is null or pg_get_userbyid(p.proowner)<>'postgres' or p.proconfig is distinct from array['search_path=""']::text[] or p.proacl::text is distinct from r.acl or encode(sha256(convert_to(replace(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash then raise exception 'optional_review_predecessor_changed: %',r.signature;end if;
 end loop;end $$;
CREATE OR REPLACE FUNCTION public.admin_program_save(p_id uuid, p_revision text, p_version text, p_patch jsonb, p_resolve text[], p_note text, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; item jsonb;
 next_facts jsonb; field text; reason text; allowed text[]:='{}'; active text[]; changed text[]:='{}'; d jsonb;
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
 if cardinality(changed)=0 then raise exception using errcode='PT422',message='program_change_required';end if;
 next_facts:=f.facts||p_patch;
 foreach reason in array p_resolve loop
   if reason is null or not reason=any(active) or not (changed && array(select x from unnest(machimoa_review.program_reason_fields(reason)) x where x not in ('activity_evidence','residence_evidence','period_evidence'))) then
   raise exception using errcode='PT422',message='program_reason_not_resolved';end if;
   next_facts:=jsonb_set(next_facts,'{missing}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'missing') where value#>>'{}'<>reason),'[]'));
   next_facts:=jsonb_set(next_facts,'{conflicts}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'conflicts') where value#>>'{}'<>reason),'[]'));
 end loop;
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
 values(p_id,p_revision,'save_facts',p_actor,p_note,changed||array(select 'resolved:'||x from unnest(p_resolve) x));
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $function$;
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
 if p->>'delivery_mode' in ('offline','hybrid') and (p->>'activity_region'<>'capital') then reasons:=array_append(reasons,'activity_location_unknown'); end if;
 if p->>'delivery_mode'='online' and p->>'residence_scope' not in ('nationwide','includes_capital','capital') then reasons:=array_append(reasons,'residence_scope_unknown'); end if;
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
end $function$;
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
 if f->>'productType'<>'living_guide' and not (f->>'productType'='event_program' and cat in ('program','event','youth_space') and f->>'delivery' in ('offline','hybrid') and (cat<>'youth_space' or d->'spaceKind'->>'value' is distinct from 'news')) and (f->>'scope'='unknown') or f->>'productType'='policy_reference' and f->>'foreignEligibility'='unknown' then raise sqlstate 'PT422' using message='classification_missing_evidence';end if;
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
end $function$;
CREATE OR REPLACE FUNCTION public.admin_review_reclassify(p_id uuid, p_revision text, p_version text, p_classification_version bigint, p_facts jsonb, p_filters jsonb, p_note text, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype;before_row jsonb;item jsonb;v bigint;codes text[];requested_id uuid:=p_id;
begin
 p_note:=btrim(coalesce(p_note,''));
 p_id:=machimoa_review.classification_source(p_id);
 if p_actor is null or char_length(btrim(coalesce(p_note,'')))>4000 then raise sqlstate 'PT422' using message='classification_invalid_command';end if;
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
end $function$;
CREATE OR REPLACE FUNCTION machimoa_review.myseoul_evaluate(f jsonb, p_now timestamp with time zone)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare reasons text[]:=array(select value->>'code' from jsonb_array_elements(f->'issues'));
 exclusions text[]:=array(select jsonb_array_elements_text(f->'scope_exclusions')); app text:='unknown'; mode text:=f->>'delivery_mode';
 k text; p jsonb; app_period jsonb; op_period jsonb; endpoint jsonb; boundary timestamptz; decision text; quality text; scope text; status text;
begin
 perform machimoa_review.myseoul_validate(f);
 if p_now is null then raise exception using errcode='PT422',message='evaluation_time_required';end if;
 if f->>'application_actor'='institution_only' then exclusions:=array_append(exclusions,'institution_only');end if;
 if exists(select 1 from machimoa_review.source_items s where s.source_id='myseoul_program' and s.revision_hash=f->>'source_revision' and s.normalized_payload->>'official_url'=f->>'official_url' and not s.body_usable and s.attachment_present) and not machimoa_review.myseoul_body_confirmed(f) then reasons:=array_append(reasons,'attachment_dependent');end if;
 if char_length(btrim(f->>'description'))<20 then reasons:=array_append(reasons,'description_missing');end if;
 if btrim(f->>'target')='' then reasons:=array_append(reasons,'target_missing');end if;
 if f->>'application_actor'='unknown' then reasons:=array_append(reasons,'application_actor_unknown');end if;
 if f->>'public_category'='unknown' then reasons:=array_append(reasons,'category_unresolved');end if;
 if mode in ('unknown','course_unresolved') then reasons:=array_append(reasons,case when mode='unknown' then 'delivery_mode_unknown' else 'course_modes_unresolved' end);end if;
 if mode in ('offline','mixed') then
 if f->>'activity_region'='noncapital' then exclusions:=array_append(exclusions,'noncapital_venue');
 elsif (f->>'activity_region'<>'capital' or btrim(f->>'venue')='') and not machimoa_review.myseoul_region_confirmed(f) then reasons:=array_append(reasons,'activity_region_unknown');end if;end if;
 if mode='online' then
 if f->>'residence_scope'='noncapital_only' then exclusions:=array_append(exclusions,'online_noncapital_only');
 elsif (f->>'residence_scope' not in ('nationwide','includes_capital','capital')) and not machimoa_review.myseoul_residence_confirmed(f) then reasons:=array_append(reasons,'online_residence_unknown');end if;end if;
 if f->'application_methods'='[]'::jsonb then reasons:=array_append(reasons,'application_method_missing');end if;
 if f->'fees'='[]'::jsonb or exists(select 1 from jsonb_array_elements(f->'fees') fee cross join lateral jsonb_array_elements_text(fee->'evidence') v
 where v !~ '무료|[0-9][0-9,]*[[:space:]]*원|별도[[:space:]]*(부담|납부)') then reasons:=array_append(reasons,'fee_unknown');end if;
 for k in select fee->>'component' from jsonb_array_elements(f->'fees') fee cross join lateral jsonb_array_elements_text(fee->'evidence') v
 group by fee->>'component' having count(distinct machimoa_review.myseoul_comparison(fee->>'component',v))>1 loop
 reasons:=array_append(reasons,'source_fact_conflict:'||k);end loop;
 foreach k in array array['application','operation'] loop
 if exists(select 1 from jsonb_array_elements(f->'periods'->k) v where v->>'status'<>'ok') or k='operation' and not exists(
 select 1 from jsonb_array_elements(f->'periods'->k) v where v->>'status'='ok') then reasons:=array_append(reasons,k||'_period_unknown');end if;
 if (select count(distinct v->'endpoints') from jsonb_array_elements(f->'periods'->k) v where v->>'status'='ok')>1 then reasons:=array_append(reasons,'source_fact_conflict:'||k);end if;end loop;
 if (select count(distinct machimoa_review.myseoul_comparison('status',v)) from jsonb_array_elements_text(f->'source_status') v)>1 then reasons:=array_append(reasons,'source_fact_conflict:status');end if;
 select value into app_period from jsonb_array_elements(f->'periods'->'application') where value->>'status'='ok' limit 1;
 select value into op_period from jsonb_array_elements(f->'periods'->'operation') where value->>'status'='ok' limit 1;
 status:=array_to_string(array(select jsonb_array_elements_text(f->'source_status')),E'\n');
 if status ~ '접수[[:space:]]*종료|모집[[:space:]]*종료|예약[[:space:]]*마감|접수[[:space:]]*마감|신청[[:space:]]*(마감|종료)' then app:='closed';
 elsif app_period is not null then
 endpoint:=app_period->'endpoints'->(jsonb_array_length(app_period->'endpoints')-1);
 boundary:=machimoa_review.myseoul_boundary(endpoint,true);
 app:=case when p_now<machimoa_review.myseoul_boundary(app_period->'endpoints'->0,false) then 'not_started'
 when endpoint->>'precision'='day' and p_now>=boundary or endpoint->>'precision'='minute' and p_now>boundary then 'closed' else 'open' end;
 elsif status ~ '접수[[:space:]]*중|모집[[:space:]]*중|신청[[:space:]]*중|추가[[:space:]]*모집|현장[[:space:]]*접수' then app:='open';
 else reasons:=array_append(reasons,'application_period_unknown');end if;
 if op_period is not null then endpoint:=op_period->'endpoints'->(jsonb_array_length(op_period->'endpoints')-1);
 boundary:=machimoa_review.myseoul_boundary(endpoint,true);
 if endpoint->>'precision'='day' and p_now>=boundary or endpoint->>'precision'='minute' and p_now>boundary then app:='ended';end if;end if;
 if reasons && array['source_fact_conflict:application','source_fact_conflict:operation','source_fact_conflict:status'] then app:='unknown';end if;
 if app='unknown' then reasons:=array_append(reasons,'application_state_unknown');end if;
 select coalesce(array_agg(code order by ord),'{}') into reasons from (select code,min(ord) ord from unnest(reasons) with ordinality q(code,ord) group by code) q;
 select coalesce(array_agg(code order by ord),'{}') into exclusions from (select code,min(ord) ord from unnest(exclusions) with ordinality q(code,ord) group by code) q;
 scope:=case when cardinality(exclusions)>0 then 'excluded' when reasons && array['target_missing','application_actor_unknown','delivery_mode_unknown',
 'course_modes_unresolved','activity_region_unknown','online_residence_unknown','category_unresolved','nationality_or_visa_unresolved'] then 'unknown' else 'included' end;
 quality:=case when exists(select 1 from unnest(reasons) r where r like 'source_fact_conflict:%' or r like 'source_change_conflict:%') then 'conflict' when cardinality(reasons)>0 then 'insufficient' else 'sufficient' end;
 decision:=case when cardinality(exclusions)>0 then 'out_of_scope' when cardinality(reasons)>0 then 'review_required' when app='open' then 'in_scope' else 'not_currently_available' end;
 reasons:=exclusions||reasons;
 if app in ('closed','not_started','ended') then reasons:=array_append(reasons,case when app='ended' then 'operation_ended' else 'application_'||app end);end if;
 select coalesce(array_agg(code order by ord),'{}') into reasons from (select code,min(ord) ord from unnest(reasons) with ordinality q(code,ord) group by code) q;
 return jsonb_build_object('decision',decision,'disposition',case when cardinality(exclusions)>0 then 'non_target' when decision='in_scope' then 'target' else 'observe_only' end,
 'scope',scope,'application',app,'quality',quality,'public_category',f->>'public_category','reasons',to_jsonb(reasons),'ai_status','blocked');
end $function$;
CREATE OR REPLACE FUNCTION public.admin_myseoul_program_save_v2(p_id uuid, p_revision text, p_version text, p_patch jsonb, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
<<myseoul_save>>
declare item jsonb; f jsonb; candidate jsonb; r text; k text; axis text; v text; result jsonb;
 changed text[]:='{}'; resolved text[]:='{}'; submitted text[]; before_patch jsonb:='{}'; after_patch jsonb:='{}'; event_id bigint;
begin
 if p_patch is null or jsonb_typeof(p_patch)<>'object' or (p_patch='{}'::jsonb and not machimoa_review.admin_trash_pending(p_id,p_revision)) or octet_length(p_patch::text)>200000 then
 raise exception using errcode='PT422',message='invalid_myseoul_command';end if;
 item:=machimoa_review.myseoul_admin_lock(p_id,p_revision,p_version,p_actor);
 perform machimoa_review.ai_recheck_edit_guard(p_id,p_revision);
 f:=item->'facts';
 submitted:=array(select jsonb_object_keys(p_patch));
 foreach k in array submitted loop
 if not (item->'editableFields') ? k or k='activity_evidence' then
 raise exception using errcode='PT422',message='myseoul_field_read_only';end if;
 before_patch:=before_patch||jsonb_build_object(k,f->k);
 if k='periods' then
 if jsonb_typeof(p_patch->k)<>'object' or p_patch->k='{}'::jsonb or
 exists(select 1 from jsonb_object_keys(p_patch->k) a where a not in ('application','operation')) then
 raise exception using errcode='PT422',message='invalid_myseoul_periods';end if;
 for axis in select jsonb_object_keys(p_patch->'periods') loop
 if not machimoa_review.ai_recheck_pending(p_id,p_revision) and not exists(select 1 from jsonb_array_elements_text(item->'result'->'reasons') q(reason)
 where q.reason in (axis||'_period_unknown','source_fact_conflict:'||axis,'source_change_conflict:'||axis,
 'source_change_conflict:periods','application_state_unknown','source_fact_conflict:status')) then
 raise exception using errcode='PT422',message='myseoul_period_axis_read_only';end if;end loop;
 f:=jsonb_set(f,'{periods}',(f->'periods')||(p_patch->'periods'));
 else f:=jsonb_set(f,array[k],p_patch->k);end if;
 if f->k is distinct from item->'facts'->k then changed:=array_append(changed,k);end if;
 after_patch:=after_patch||jsonb_build_object(k,f->k);
 end loop;

 -- Reuse saved source evidence, never manufacture a source quote from a choice.
 -- The original observedFacts/evidence/conflicts remain unchanged.
 if submitted && array['delivery_mode','venue','activity_region'] then
 for v in select e->>'value' from jsonb_array_elements(item->'facts'->'evidence') e
 where e->>'field' in ('mode','venue') union
 select line from regexp_split_to_table(item->'source'->>'body',E'\n') line
 where btrim(f->>'venue')<>'' and position(f->>'venue' in line)>0 loop
 if char_length(v) between 1 and 4000 and not (f->'activity_evidence') ? v then
 f:=jsonb_set(f,'{activity_evidence}',f->'activity_evidence'||jsonb_build_array(v));end if;
 end loop;end if;
 perform machimoa_review.myseoul_validate(f);
 -- Insert the server audit in this same transaction before scoped evaluation.
 -- Only a complete, valid three-field submission can confirm a venue.
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,'사실 확인 저장 · 시스템 처리 기록',changed) returning id into event_id;
 insert into machimoa_review.myseoul_fact_edits(event_id,before_patch,after_patch,activity_confirmed)
 values(event_id,before_patch,after_patch,
 submitted @> array['delivery_mode','activity_region','venue'] and
 f->>'delivery_mode' in ('offline','mixed') and f->>'activity_region'='capital' and btrim(f->>'venue')<>'');


 -- Submitted fields are a scoped confirmation, including an unchanged value.
 -- No client resolve list; period axes and fee components stay independent.
 for r in select jsonb_array_elements_text(item->'result'->'reasons') loop
 if not submitted && machimoa_review.myseoul_reason_fields(r) then continue;end if;
 axis:=case when r in ('application_period_unknown','source_fact_conflict:application','source_change_conflict:application') then 'application'
 when r in ('operation_period_unknown','source_fact_conflict:operation','source_change_conflict:operation') then 'operation' end;
 if axis is not null and not coalesce((p_patch->'periods') ? axis,false) then continue;end if;
 if r='source_fact_conflict:mode' and not p_patch ? 'delivery_mode' or
 r='source_fact_conflict:venue' and not p_patch ? 'venue' then continue;end if;
 if r='nationality_or_visa_unresolved' and (not (changed && array['target','conditions']) or btrim(f->>'target')='' or f->>'application_actor'='unknown') then continue;end if;
 if r='category_unresolved' and f->>'public_category'='unknown' then continue;end if;
 if r='fee_components_unresolved' and exists(select 1 from jsonb_array_elements(f->'fees') fee
 where fee->>'component'='extra_fee' and exists(select 1 from jsonb_array_elements_text(fee->'evidence') value
 where (value ~ '수강료' and value ~ '입장료') or (value ~ '재료비' and value ~ '입장료') or (value ~ '수강료' and value ~ '재료비'))) then continue;end if;
 candidate:=jsonb_set(f,'{issues}',coalesce((select jsonb_agg(value) from jsonb_array_elements(f->'issues') where value->>'code'<>r),'[]'::jsonb));
 result:=machimoa_review.myseoul_evaluate(candidate,clock_timestamp());
 if not (result->'reasons') ? r then
 f:=candidate;resolved:=array_append(resolved,r);end if;
 end loop;
 if cardinality(changed)=0 and cardinality(resolved)=0 and not machimoa_review.admin_trash_pending(p_id,p_revision) then
 raise exception using errcode='PT422',message='myseoul_no_resolved_fact';end if;
 if f->'activity_evidence' is distinct from item->'facts'->'activity_evidence' then
 before_patch:=before_patch||jsonb_build_object('activity_evidence',item->'facts'->'activity_evidence');
 after_patch:=after_patch||jsonb_build_object('activity_evidence',f->'activity_evidence');end if;
 update machimoa_review.source_item_program_facts set facts=f,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 update machimoa_review.admin_review_events
 set changed_fields=changed||array(select 'resolved:'||q.code from unnest(resolved) q(code)) where id=event_id;
 update machimoa_review.myseoul_fact_edits x
 set before_patch=myseoul_save.before_patch,after_patch=myseoul_save.after_patch
 where x.event_id=myseoul_save.event_id;
 update machimoa_review.admin_exclusion_episodes set review_completed_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision and restored_at is not null and review_completed_at is null;
 perform machimoa_review.myseoul_refresh(p_id);
 return public.admin_myseoul_program_detail(p_id);
end $function$;
CREATE OR REPLACE FUNCTION machimoa_review.myseoul_reason_fields(reason text)
 RETURNS text[]
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO ''
AS $function$
 select case when reason in ('source_change_conflict:application','source_change_conflict:operation') then array['periods'] when reason like 'source_change_conflict:%' and split_part(reason,':',2) in ('description','official_url','public_category','purpose','target','residence','age','companion','language','conditions','application_actor','venue','delivery_mode','activity_region','activity_evidence','residence_scope','residence_evidence','qualification_note','fees','periods','session_evidence','meeting_evidence','application_methods','application_links','source_status') then array[split_part(reason,':',2)]
 when reason in ('description_missing','attachment_dependent') then array['description']
 when reason='target_missing' then array['target','conditions','application_actor']
 when reason='application_actor_unknown' then array['application_actor','target','conditions']
 when reason in ('delivery_mode_unknown','course_modes_unresolved','activity_region_unknown') then array['delivery_mode','activity_region','venue','activity_evidence']
 when reason='online_residence_unknown' then array['residence_scope','residence','residence_evidence']
 when reason='category_unresolved' then array['public_category','purpose']
 when reason='nationality_or_visa_unresolved' then array['target','conditions','qualification_note']
 when reason in ('application_period_unknown','operation_period_unknown') then array['periods','session_evidence']
 when reason='application_method_missing' then array['application_methods','application_links']
 when reason in ('fee_unknown','fee_components_unresolved') then array['fees']
 when reason='application_state_unknown' then array['source_status','periods']
 when reason='source_fact_conflict:application_method' then array['application_methods','application_links']
 when reason in ('source_fact_conflict:application','source_fact_conflict:operation') then array['periods','session_evidence']
 when reason='source_fact_conflict:target' then array['target','conditions']
 when reason='source_fact_conflict:mode' then array['delivery_mode','activity_evidence']
 when reason='source_fact_conflict:venue' then array['venue','activity_region','activity_evidence']
 when reason='source_fact_conflict:status' then array['source_status','periods']
 when reason in ('source_fact_conflict:tuition','source_fact_conflict:admission','source_fact_conflict:materials','source_fact_conflict:extra_fee') then array['fees']
 else '{}'::text[] end
$function$;
commit;
