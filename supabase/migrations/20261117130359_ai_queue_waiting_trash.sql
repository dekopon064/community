begin;
-- Keep the public diagnostic wrappers and the existing locked exclusion RPC.
CREATE OR REPLACE FUNCTION machimoa_review.seoul_expired_base_detail(p_job_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 d jsonb;h jsonb;permission jsonb;classification jsonb;idle_queue boolean; ready boolean; exclude_ready boolean;
begin
 select * into j from machimoa_review.processing_jobs where id=p_job_id and processing_stage='ai_enrichment';
 if not found then raise sqlstate 'PT404' using message='ai_job_not_found';end if;
 select * into s from machimoa_review.source_items where id=j.source_item_id;
 if s.revision_hash is distinct from j.revision_hash then raise sqlstate 'PT409' using message='source_revision_conflict';end if;
 if s.source_id='seoul_reservation' then d:=public.admin_program_detail(s.id);
 elsif s.source_id='myseoul_program' then d:=public.admin_myseoul_program_detail(s.id);
 elsif s.source_id in ('youthcenter_policy','youthcenter_content') then d:=public.admin_review_detail('facts',s.id);
 else raise sqlstate 'PT409' using message='unsupported_source';end if;
 classification:=public.admin_review_classification_detail(s.id);
 if classification->>'active'<>'true' then classification:=null;end if;
 select to_jsonb(r) into h from machimoa_review.ai_rechecks r where r.job_id=j.id and r.completed_at is null;
 select jsonb_build_object('enabled',enabled,'permission',permission_status,'legacy',legacy_curation_source) into permission
 from machimoa_review.ingest_sources where source_id=s.source_id;
 -- A legacy retry keeps the previous claimed_at after releasing the worker and lease.
 idle_queue:=j.status='queued'
 and j.claimed_by is null and j.claim_lease_until is null and h is null and s.disposition<>'non_target'
 and permission->>'enabled'='true' and permission->>'permission' in ('approved_noncommercial','approved_commercial')
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 and not exists(select 1 from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key);
 ready:=idle_queue and j.retry_count=0 and j.next_retry_at is null and j.claimed_at is null;
 exclude_ready:=(idle_queue and (j.claimed_at is null or j.retry_count>0 or j.next_retry_at is not null) or h is not null and j.status='cancelled') and s.disposition<>'non_target'
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 and not exists(select 1 from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key);
 return jsonb_build_object('jobId',j.id,'sourceItemId',s.id,'sourceName',s.source_id,'revision',s.revision_hash,
 'version',encode(sha256(convert_to(jsonb_build_array('ai-queue-recheck-v2',to_jsonb(j),d->>'version',classification->>'version',h,permission)::text,'UTF8')),'hex'),
 'status',j.status,'canRecheck',coalesce(ready,false),'canExclude',coalesce(exclude_ready,false),'recheckPending',h is not null,'note',coalesce(h->>'note',''),'review',d,'classification',classification);
end $function$
;
commit;
