-- Preserve candidates/inputs/history and guarded read/publish contracts. Forward recovery required.
begin;
do $$ begin
 perform 1 from machimoa_review.source_items where source_id='myseoul_program' order by id for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id in(select id from machimoa_review.source_items where source_id='myseoul_program') order by source_item_id,revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id in(select id from machimoa_review.source_items where source_id='myseoul_program') and status='claimed') then raise exception using errcode='PT409',message='myseoul_processing_active';end if;
 update machimoa_review.ingest_sources set enabled=false where source_id='myseoul_program';
 update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp() where source_item_id in(select id from machimoa_review.source_items where source_id='myseoul_program') and processing_stage='ai_enrichment' and status in ('queued','failed');
 end $$;
drop function public.claim_myseoul_program_ai(uuid,text,text,integer);
drop function public.finish_myseoul_program_ai(uuid,text,bigint,timestamptz,timestamptz,text,jsonb);
drop function public.fail_myseoul_program_ai(uuid,timestamptz,timestamptz,text,text);

create or replace function machimoa_review.myseoul_refresh(p_id uuid,p_now timestamptz default clock_timestamp()) returns void
language plpgsql set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; v_result jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='myseoul_program' for update;
 if not found then raise exception using errcode='PT404',message='myseoul_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash for update;
 if not found or f.schema_version<>'myseoul-program-facts-v1-local' or f.evaluated_profile<>'myseoul-program-v1-local' then
 raise exception using errcode='PT409',message='myseoul_contract_conflict';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
 raise exception using errcode='PT409',message='myseoul_processing_active';end if;
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 v_result:=case when f.manual_excluded then jsonb_build_object('decision','out_of_scope','disposition','non_target','scope','excluded','application','unknown',
 'quality','sufficient','public_category',f.facts->>'public_category','reasons',jsonb_build_array('manual_service_scope_excluded'),'ai_status','blocked')
 else machimoa_review.myseoul_evaluate(f.facts,p_now) end;
 update machimoa_review.source_item_program_facts set result=v_result where source_item_id=p_id and revision_hash=s.revision_hash;
 update machimoa_review.source_items set disposition=v_result->>'disposition' where id=p_id;
 update machimoa_review.processing_jobs set status=case when revision_hash=s.revision_hash and processing_stage='content_review'
 and v_result->>'decision'='in_scope' then 'completed' else 'cancelled' end,completed_at=clock_timestamp()
 where source_item_id=p_id and status in ('queued','failed') and (revision_hash<>s.revision_hash or processing_stage<>'content_review' or v_result->>'decision'<>'review_required');
 if v_result->>'decision'='review_required' then
 insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
 values(p_id,s.revision_hash,'content_review','queued',clock_timestamp(),clock_timestamp(),array(select jsonb_array_elements_text(v_result->'reasons')))
 on conflict(source_item_id,revision_hash,processing_stage) do update set reason_codes=excluded.reason_codes,status='queued',completed_at=null
 where machimoa_review.processing_jobs.status in ('queued','cancelled','failed');end if;
 -- No AI insertion, including enabled/approved sources. Worker connection is separate.
end $$;
create or replace function public.admin_myseoul_program_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; jobs jsonb; permission jsonb; history jsonb; editable text[];
 result jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='myseoul_program';
 if not found then raise exception using errcode='PT404',message='myseoul_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash;
 if not found or f.schema_version<>'myseoul-program-facts-v1-local' or f.evaluated_profile<>'myseoul-program-v1-local' then
 raise exception using errcode='PT409',message='myseoul_contract_conflict';end if;
 -- Current-time read gate without writes. Stored review/result remain audit state.
 result:=case when f.manual_excluded then f.result else machimoa_review.myseoul_evaluate(f.facts,statement_timestamp()) end;
 select coalesce(jsonb_agg(jsonb_build_object('revision',revision_hash,'stage',processing_stage,'status',status,'reasons',reason_codes) order by revision_hash,processing_stage),'[]')
 into jobs from machimoa_review.processing_jobs where source_item_id=p_id;
 select jsonb_build_object('enabled',enabled,'permission',permission_status) into permission from machimoa_review.ingest_sources where source_id=s.source_id;
 select coalesce(array_agg(distinct field order by field),'{}') into editable
 from jsonb_array_elements_text(result->'reasons') reason cross join lateral unnest(machimoa_review.myseoul_reason_fields(reason)) field;
 select coalesce(jsonb_agg(jsonb_build_object('action',action,'actor',actor,'at',occurred_at,'note',note,'fields',changed_fields) order by id desc),'[]') into history
 from (select * from machimoa_review.admin_review_events where source_item_id=p_id order by id desc limit 25) e;
 return jsonb_build_object('id',p_id,'revision',s.revision_hash,'version',encode(sha256(convert_to(jsonb_build_array(s.revision_hash,f.facts_version,f.facts,jobs,permission)::text,'UTF8')),'hex'),
 'schema',f.schema_version,'profile',f.evaluated_profile,'factsVersion',f.facts_version,
 'source',jsonb_build_object('name',s.source_id,'title',s.min_fields->>'title','url',s.normalized_payload->>'official_url','body',s.normalized_payload->>'description'),
 'facts',f.facts,'observedFacts',f.observed_facts,'result',result,'editableFields',to_jsonb(editable),
 'status',case when f.manual_excluded or result->>'decision'='out_of_scope' then 'excluded' when result->>'decision'='review_required' then 'open' else 'resolved' end,
 'aiStatus','blocked','history',history);
end $$;
notify pgrst,'reload schema';
commit;
