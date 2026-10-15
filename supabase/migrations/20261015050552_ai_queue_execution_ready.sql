begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- Read projection only: no job/fact/filter backfill or claim execution.
do $$ declare r record;f record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values
 ('machimoa_review.ai_recheck_base_queue(integer,integer,uuid[])','611fbe9363c740c063215f367cb4d666c6a029ef558a422558347cc3f6f17b70'),
 ('public.admin_review_ai_queue(integer,integer,uuid[])','8bc2f1b3073fd797b96dfec0cc40d24177108ed7578d216245e974e69e070082'),
 ('machimoa_review.program_ai_check(uuid,text,bigint)','be87004e7ff2aadbe14c551bf7c119d2bef3652f30130ebd7527ea2e0233c326'),
 ('machimoa_review.myseoul_ai_preparation_check(uuid,text,bigint)','4bb1b878e20fcb56c888912f65b86209fdb2a0fbee912e9930e5d38e7590c98e'),
 ('machimoa_review.classification_ready(uuid)','a7c3bfa08afcdd074791555cbf23c4b84d3b933cd0f38d17fbf12d54158c8ab9'),
 ('machimoa_review.claim_processing_jobs(text,integer,text,integer)','79b45577e18f15421e6213fde05d728f3b352af60dca97efd22729c8e1c252ef')
 ) x(signature,hash) loop
  select * into f from pg_proc where oid=to_regprocedure(r.signature);
  if f.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(f.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash
   or pg_get_userbyid(f.proowner)<>'postgres' or f.proconfig is distinct from array['search_path=""']::text[]
   or f.proacl::text is distinct from (case when r.signature like 'public.%' then '{postgres=X/postgres,service_role=X/postgres}' else '{postgres=X/postgres}' end)
  then raise exception 'ai_queue_ready_predecessor_changed: %',r.signature;end if;
 end loop;
end $$;

-- A non-locking snapshot of the existing claim prerequisites. Never invoke the
-- locking/mutating claim/check functions from a GET. Actual claims still recheck
-- current versions, leases and snapshots under their original transaction locks.
create function machimoa_review.ai_queue_executable(p_job uuid) returns boolean
language plpgsql stable set search_path='' as $$
declare s machimoa_review.source_items%rowtype;j machimoa_review.processing_jobs%rowtype;
 f machimoa_review.source_item_program_facts%rowtype;p machimoa_review.source_item_product_types%rowtype;
begin
 select * into j from machimoa_review.processing_jobs where id=p_job;
 if not found or j.processing_stage<>'ai_enrichment' or j.status<>'queued'
  or j.available_at>statement_timestamp() or j.next_retry_at>statement_timestamp() then return false;end if;
 select * into s from machimoa_review.source_items where id=j.source_item_id;
 if not found or s.revision_hash is distinct from j.revision_hash
  or s.disposition in ('non_target','excluded','outside_scope')
  or not exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id and enabled and permission_status in ('approved_noncommercial','approved_commercial'))
  or machimoa_review.admin_trash_pending(s.id,j.revision_hash)
  or machimoa_review.ai_recheck_pending(s.id,j.revision_hash)
  or exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
  or exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=j.revision_hash and processing_stage<>'ai_enrichment' and status in ('queued','claimed'))
  or exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key and source_revision_hash=j.revision_hash)
 then return false;end if;
 if exists(select 1 from machimoa_review.review_classifications where source_item_id=s.id and revision_hash=j.revision_hash) then
  return coalesce(machimoa_review.classification_ready(s.id)
   and (public.admin_review_classification_detail(s.id)->>'editable')::boolean,false);
 end if;
 if not machimoa_review.content_filter_ready(s.id,j.revision_hash) then return false;end if;
 if s.source_id in ('seoul_reservation','myseoul_program') then
  select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=j.revision_hash;
  if not found or f.manual_excluded then return false;end if;
  if s.source_id='seoul_reservation' then
   return coalesce(f.schema_version='program-scope-v1-local' and f.evaluated_profile='program_capital_v1_local'
    and s.normalized_payload->'provider_fields'->>'MAXCLASSNM'='문화체험'
    and machimoa_review.publication_temporal_ready(machimoa_review.program_evaluate_reviewed(f.facts,statement_timestamp(),s.id,j.revision_hash)),false);
  end if;
  return coalesce(f.schema_version='myseoul-program-facts-v1-local' and f.evaluated_profile='myseoul-program-v1-local'
   and f.facts->>'public_category' in ('program','event')
   and machimoa_review.myseoul_ai_ready(machimoa_review.myseoul_evaluate(f.facts,statement_timestamp())),false);
 end if;
 if s.source_id not in ('youthcenter_policy','youthcenter_content') or s.disposition<>'target' or not s.body_usable or not s.has_source_url
  or not machimoa_review.category_period_ready(s.id,j.revision_hash)
  or exists(select 1 from machimoa_review.content_filter_claim_inputs where job_id=j.id) then return false;end if;
 select * into p from machimoa_review.source_item_product_types where source_item_id=s.id and revision_hash=j.revision_hash;
 if not found then return false;end if;
 if p.gate_facts is null and p.assessment_schema_version is null and p.evaluated_profile is null and p.evaluated_at is null then
  return exists(select 1 from machimoa_review.ingest_review_decisions where source_item_id=s.id and revision_hash=j.revision_hash and decision='approve_ai');
 end if;
 if machimoa_review.gate_facts_row_is_complete_v1(p.product_type,p.gate_facts,p.assessment_schema_version,p.evaluated_profile,p.evaluated_at,'capital_v1') is not true then return false;end if;
 return exists(select 1 from machimoa_review.evaluate_source_item_gates(s.body_usable,s.has_source_url,s.attachment_present,p.product_type,p.reason_codes,p.gate_facts) ev where ev.disposition='target');
end $$;
alter function machimoa_review.ai_queue_executable(uuid) owner to postgres;
revoke all on function machimoa_review.ai_queue_executable(uuid) from public,anon,authenticated,service_role;

do $$ declare d text;before_page text;after_page text;begin
 d:=pg_get_functiondef('machimoa_review.ai_recheck_base_queue(integer,integer,uuid[])'::regprocedure);
 before_page:=$old$), page as (select * from projected where entry->>'currentRevision'='true' and entry->>'status' in ('queued','claimed','failed')$old$;
 after_page:=$new$), page as (select * from projected where entry->>'currentRevision'='true'
 and (entry->>'status' in ('claimed','failed') or entry->>'status'='queued' and machimoa_review.ai_queue_executable(job_id))$new$;
 if strpos(d,before_page)=0 then raise exception 'ai_queue_ready_page_anchor_changed';end if;
 -- Filter before OFFSET/LIMIT, while leaving watched outcomes/held recovery intact.
 execute replace(d,before_page,after_page);
end $$;
commit;
