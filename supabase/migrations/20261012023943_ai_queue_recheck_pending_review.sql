begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- Holding is not permission to execute AI. Preserve all existing review reasons.
-- No record backfill, candidate/content edit, source activation or AI execution.
do $$ declare f record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 select * into f from pg_proc where oid=to_regprocedure('public.admin_ai_queue_review_detail(uuid)');
 if f.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(f.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'5d0688d741591e5b9726810375ec28e1b1f592666bc45c142f4d58f206ae92bc'
 or pg_get_userbyid(f.proowner)<>'postgres' or f.proacl::text is distinct from '{postgres=X/postgres,service_role=X/postgres}'
 or f.proconfig is distinct from array['search_path=""']::text[] or not f.prosecdef
 then raise exception 'ai_recheck_pending_predecessor_changed';end if;
end $$;
create or replace function public.admin_ai_queue_review_detail(p_job_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 d jsonb;h jsonb;permission jsonb;classification jsonb;ready boolean;
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
 ready:=j.status='queued' and j.retry_count=0 and j.next_retry_at is null and j.claimed_at is null
 and j.claimed_by is null and j.claim_lease_until is null and h is null and s.disposition<>'non_target'
 and permission->>'enabled'='true' and permission->>'permission' in ('approved_noncommercial','approved_commercial')
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 and not exists(select 1 from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key);
 return jsonb_build_object('jobId',j.id,'sourceItemId',s.id,'sourceName',s.source_id,'revision',s.revision_hash,
 'version',encode(sha256(convert_to(jsonb_build_array('ai-queue-recheck-v1.1',to_jsonb(j),d->>'version',classification->>'version',h,permission)::text,'UTF8')),'hex'),
 'status',j.status,'canRecheck',coalesce(ready,false),'recheckPending',h is not null,'note',coalesce(h->>'note',''),'review',d,'classification',classification);
end $$;

commit;
