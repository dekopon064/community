-- LOCAL ONLY. Additive My editor contract; legacy save/exclude and gates remain.
begin;
create table machimoa_review.myseoul_fact_edits (
 event_id bigint primary key references machimoa_review.admin_review_events(id) on delete restrict,
 before_patch jsonb not null check(jsonb_typeof(before_patch)='object'),
 after_patch jsonb not null check(jsonb_typeof(after_patch)='object')
);
alter table machimoa_review.myseoul_fact_edits enable row level security;
revoke all on machimoa_review.myseoul_fact_edits from public,anon,authenticated,service_role;

create function public.admin_myseoul_program_save_v2(p_id uuid,p_revision text,p_version text,p_patch jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare item jsonb; f jsonb; candidate jsonb; r text; k text; axis text; v text; result jsonb;
 changed text[]:='{}'; resolved text[]:='{}'; submitted text[]; before_patch jsonb:='{}'; after_patch jsonb:='{}'; event_id bigint;
begin
 if p_patch is null or jsonb_typeof(p_patch)<>'object' or p_patch='{}'::jsonb or octet_length(p_patch::text)>200000 then
 raise exception using errcode='PT422',message='invalid_myseoul_command';end if;
 item:=machimoa_review.myseoul_admin_lock(p_id,p_revision,p_version,p_actor);
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
 if not exists(select 1 from jsonb_array_elements_text(item->'result'->'reasons') q(reason)
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

 -- Submitted fields are a scoped confirmation, including an unchanged value.
 -- No client resolve list; period axes and fee components stay independent.
 for r in select jsonb_array_elements_text(item->'result'->'reasons') loop
 if not submitted && machimoa_review.myseoul_reason_fields(r) then continue;end if;
 axis:=case when r in ('application_period_unknown','source_fact_conflict:application','source_change_conflict:application') then 'application'
 when r in ('operation_period_unknown','source_fact_conflict:operation','source_change_conflict:operation') then 'operation' end;
 if axis is not null and not coalesce((p_patch->'periods') ? axis,false) then continue;end if;
 if r='source_fact_conflict:mode' and not p_patch ? 'delivery_mode' or
 r='source_fact_conflict:venue' and not p_patch ? 'venue' then continue;end if;
 if r='nationality_or_visa_unresolved' and char_length(btrim(f->>'qualification_note'))<10 then continue;end if;
 if r='category_unresolved' and char_length(btrim(f->>'purpose'))<10 then continue;end if;
 if r='fee_components_unresolved' and exists(select 1 from jsonb_array_elements(f->'fees') fee
 where fee->>'component'='extra_fee' and exists(select 1 from jsonb_array_elements_text(fee->'evidence') value
 where (value ~ '수강료' and value ~ '입장료') or (value ~ '재료비' and value ~ '입장료') or (value ~ '수강료' and value ~ '재료비'))) then continue;end if;
 candidate:=jsonb_set(f,'{issues}',coalesce((select jsonb_agg(value) from jsonb_array_elements(f->'issues') where value->>'code'<>r),'[]'::jsonb));
 result:=machimoa_review.myseoul_evaluate(candidate,clock_timestamp());
 if not (result->'reasons') ? r then
 f:=candidate;resolved:=array_append(resolved,r);end if;
 end loop;
 if cardinality(changed)=0 and cardinality(resolved)=0 then
 raise exception using errcode='PT422',message='myseoul_no_resolved_fact';end if;
 if f->'activity_evidence' is distinct from item->'facts'->'activity_evidence' then
 before_patch:=before_patch||jsonb_build_object('activity_evidence',item->'facts'->'activity_evidence');
 after_patch:=after_patch||jsonb_build_object('activity_evidence',f->'activity_evidence');end if;
 update machimoa_review.source_item_program_facts set facts=f,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,'사실 확인 저장 · 시스템 처리 기록',changed||array(select 'resolved:'||q.code from unnest(resolved) q(code))) returning id into event_id;
 insert into machimoa_review.myseoul_fact_edits values(event_id,before_patch,after_patch);
 perform machimoa_review.myseoul_refresh(p_id);
 return public.admin_myseoul_program_detail(p_id);
end $$;
revoke all on function public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid) to service_role;
commit;
